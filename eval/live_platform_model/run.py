"""Owner-run experiment: the live grounded model over the real platform test items.

PREPARED ONLY. Sending real platform content to the model needs its own owner approval (see
``README.md`` beside this file). Until the approval constants below are filled in, ``--live``
refuses before it reads any token, key or targets file.

For test users A and B it reads, with each user's own read-only token and the same connectors
and identity check as ``eval/live_access/check.py``, the one general and one restricted item per
platform named in the git-ignored ``var/live-access/targets.json``. Model input for a user is
built only from items that user's own token could read. Each user then asks four fixed
questions, each with at most one ``live_grounded`` call; every answer passes the claim-support
gate before it counts as released.

    python eval/live_platform_model/run.py --dry-run     # fake platforms and model, no network
    python eval/live_platform_model/run.py --live --yes  # real calls, once an approval is filled

Before any model call the run checks, in order, that the observed access split is exactly the
expected one (A reads everything; B reads general items and is refused restricted ones), and,
for every request of a user who is refused restricted items, that no restricted item and no
restricted-only sentence is in the model input. The same check runs again on the request bytes
just before they are sent. Any failure stops the run with nothing further sent.

No retries. Calls are at least 30 s apart; a rate limit without ``retry-after``, or asking for
more than 120 s, stops the run. Results record, per question, the user, allowed/denied per item,
the query status, the cited item labels (``platform.kind``) and SHA-256 fingerprints of the
evidence text. Never document text, tokens, emails, account IDs, site names or item IDs.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import math
import re
import secrets
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

from aspire_brain.models import Evidence  # noqa: E402
from aspire_brain.platforms.connectors import (  # noqa: E402
    ConnectorError,
    SourceRef,
    connector_for,
)
from aspire_brain.platforms.connectors.core import SourceUnavailable  # noqa: E402
from aspire_brain.providers import ExternalProviderUnavailable, ProviderInput  # noqa: E402
from aspire_brain.providers.claims import evaluate_claim_support, split_claims  # noqa: E402
from aspire_brain.providers.live import (  # noqa: E402
    ENVELOPE_BYTES,
    MAX_SENTENCE_CHARS,
    MAX_SENTENCES,
    BudgetExhausted,
    LiveGroundedProvider,
    ProviderAbstained,
    ProviderCallFailed,
    SpendLedger,
    approved_live_config,
    approved_rates,
    load_credential,
    number_sentences,
    request_body,
)
from aspire_brain.providers.runtime import reserve_budget  # noqa: E402
from aspire_brain.providers.target import canonical_json  # noqa: E402

_spec = importlib.util.spec_from_file_location("live_access_check",
                                               ROOT / "eval" / "live_access" / "check.py")
access_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(access_check)

PLATFORMS, USERS, EXPECTED = access_check.PLATFORMS, access_check.USERS, access_check.EXPECTED
KINDS = ("general", "restricted")
ITEMS = tuple(f"{platform}.{kind}" for platform in PLATFORMS for kind in KINDS)

# --- Approval -------------------------------------------------------------------------------
# Unset on purpose. Real platform content may reach the model only after the owner grants the
# approval in README.md and records it here: its date (YYYY-MM-DD), a call cap and a USD cap.
# While any of these is unset or zero, --live refuses before reading any token, key or target.
APPROVAL_DATE = ""
APPROVED_MAX_REQUESTS = 0
APPROVED_MAX_USD = Decimal("0")
#: Ledgers of earlier, separate approvals. This experiment never reads or writes them.
FOREIGN_LEDGERS = frozenset({ROOT / "var" / "provider" / "live-ledger.jsonl",
                             ROOT / "var" / "provider" / "live-eval-ledger-2026-10-15.jsonl"})

#: Stricter than the provider approval, as in ``eval/live_model/run.py``.
EVAL_CONFIG = approved_live_config().model_copy(update={"output_token_cap": 200,
                                                        "reasoning_token_cap": 300})
DEFAULT_TOKENS = access_check.DEFAULT_TOKENS
DEFAULT_TARGETS = ROOT / "var" / "live-access" / "targets.json"
DEFAULT_KEY = Path("~/.config/seaglass/groq.key").expanduser()
DEFAULT_OUT = ROOT / "var" / "live-platform-model"
MIN_LIVE_PACE_SECONDS = 30.0
#: A rate limit asking for a longer wait than this ends the run instead of pacing it.
LONG_RETRY_AFTER_SECONDS = 120.0
PACING_MARGIN_SECONDS = 2.0
#: Service-authored first line of every answer; excluded from the claim denominator.
NOTICE = "Selected from platform items this user's own account can read."
_sleep = asyncio.sleep  # replaced in tests so pacing can be checked without waiting


@dataclass(frozen=True)
class Question:
    id: str
    aim: str  # "general" or "restricted": which content the question is aimed at
    text: str
    items: tuple[str, ...]


QUESTIONS = (
    Question("handover-status", "general",
             "What happened in the Singapore morning payment operations handover?",
             ("confluence.general", "slack.general")),
    Question("supplier-payment-review", "general",
             "Which supplier payments are under review, and how do they reconcile?",
             ("jira.general", "drive.general")),
    Question("beneficiary-exception", "restricted",
             "What is the status of beneficiary verification exception EXC-DEMO-7429?",
             ("confluence.restricted", "jira.restricted", "slack.restricted")),
    Question("restricted-invoice", "restricted",
             "What does invoice CQ-DEMO-2048 say, and does it match the payment reconciliation?",
             ("drive.restricted", "drive.general")),
)


def _expected(user, item):
    return EXPECTED[(user, item.split(".", 1)[1])]


#: Calls a run makes when access is exactly as expected: one per question with any item the
#: user is expected to read. Budget room for all of them is required before anything is read.
MAX_PLANNED_CALLS = sum(any(_expected(user, item) == "allowed" for item in question.items)
                        for user in USERS for question in QUESTIONS)


class SetupError(Exception):
    pass


class RestrictedContentInModelInput(AssertionError):
    """A refused user's model input would carry restricted content. Nothing is sent."""


def ledger_path() -> Path:
    return ROOT / "var" / "provider" / f"live-platform-ledger-{APPROVAL_DATE}.jsonl"


def approval_problems() -> list[str]:
    """Why a live run may not start; empty only once the owner has recorded an approval."""
    problems = []
    try:
        date.fromisoformat(APPROVAL_DATE)
    except (TypeError, ValueError):
        problems.append("APPROVAL_DATE is not set")
    if type(APPROVED_MAX_REQUESTS) is not int or APPROVED_MAX_REQUESTS <= 0:
        problems.append("APPROVED_MAX_REQUESTS is not set")
    if not isinstance(APPROVED_MAX_USD, Decimal) or not APPROVED_MAX_USD > 0:
        problems.append("APPROVED_MAX_USD is not set")
    if ledger_path() in FOREIGN_LEDGERS:
        problems.append("the ledger path belongs to another approval")
    return problems


# --- Platform reads -------------------------------------------------------------------------

@dataclass
class Access:
    observed: str  # allowed, denied, error or not_configured
    error: str | None = None
    documents: tuple = field(default=(), repr=False)

    @property
    def label(self) -> str:
        return self.observed if self.error is None else f"error:{self.error}"


def _item_gaps(platform, kind, item):
    return [f"items.{platform}.{kind}.{key}" for key in ("id", "parent")
            if not (key == "parent" and platform == "slack")
            and not access_check._filled(item.get(key))]


def read_items(targets, tokens, transport=None) -> dict[str, dict[str, Access]]:
    """Each user reads each named item with their own token; the platform decides access."""
    access = {}
    for user in USERS:
        access[user] = {}
        profile = targets["users"].get(user, {})
        for platform in PLATFORMS:
            token, gaps = access_check._missing(platform, targets, tokens, user)
            for kind in KINDS:
                item = targets["items"].get(platform, {}).get(kind, {})
                if gaps or _item_gaps(platform, kind, item):
                    access[user][f"{platform}.{kind}"] = Access("not_configured")
                    continue
                parent = (targets.get("slack_workspace_id") if platform == "slack"
                          else item.get("parent"))
                try:
                    with access_check._session(
                            platform, targets, user, token, transport=transport,
                            account_id=profile[access_check.ACCOUNT_KEYS[platform]]) as session:
                        documents = connector_for(session).fetch(
                            SourceRef(platform, item["id"], parent))
                    result = Access("allowed", documents=tuple(documents))
                except SourceUnavailable:
                    result = Access("denied")
                except ConnectorError as error:
                    result = Access("error", error=error.code)
                access[user][f"{platform}.{kind}"] = result
    return access


def access_mismatches(access) -> list[str]:
    return [f"{user} {item}: expected {_expected(user, item)}, observed {result.observed}"
            for user in USERS for item, result in access[user].items()
            if result.observed != _expected(user, item)]


def _normal(sentence: str) -> str:
    return " ".join(sentence.split()).lower()


def _sentences(text: str) -> list[str]:
    """Sentences exactly as the provider numbers them and the claim gate checks them."""
    return split_claims(" ".join(text.split()))


def restricted_only_sentences(access) -> frozenset[str]:
    """Sentences read from any restricted item that appear in no general item."""
    by_kind = {kind: set() for kind in KINDS}
    for user_access in access.values():
        for item, result in user_access.items():
            for document in result.documents:
                by_kind[item.split(".", 1)[1]].update(
                    _normal(sentence) for sentence in _sentences(document.text))
    return frozenset(by_kind["restricted"] - by_kind["general"])


# --- Model input ----------------------------------------------------------------------------

@dataclass
class Prepared:
    question: Question
    user: str
    provider_input: ProviderInput | None
    origins: dict[str, str]  # chunk id -> item label
    truncated: bool
    items: dict[str, str]  # item label -> this user's observed access


def _fits(question, evidence) -> bool:
    context = ProviderInput(question=question.text, context={}, evidence=evidence,
                            decision_summary=NOTICE)
    body = canonical_json(request_body(question.text, number_sentences(context), EVAL_CONFIG))
    return len(body.encode("utf-8")) + ENVELOPE_BYTES <= EVAL_CONFIG.input_token_cap


def _evidence(chunks):
    return [Evidence(version_id=chunk_id, chunk_id=chunk_id, text=" ".join(kept),
                     source_locator=label, document_id=chunk_id,
                     content_hash=hashlib.sha256(" ".join(kept).encode()).hexdigest())
            for chunk_id, label, kept in chunks if kept]


def prepare(user, question, access) -> Prepared:
    """Build one model input from the question's items that this user's token could read.

    Whole sentences are taken in turn from each readable document until the next one would
    exceed the input bound, so every item keeps a leading run of complete sentences. Item IDs,
    sites and locators never enter the input: chunks are labelled ``platform.kind.n``. A title
    or file name is sent only as the connector returns it, at the start of the item's text.
    """
    pools, origins = [], {}
    for item in question.items:
        result = access[user][item]
        if result.observed != "allowed":
            continue
        for number, document in enumerate(result.documents):
            chunk_id = f"{item}.{number}"
            origins[chunk_id] = item
            pools.append((chunk_id, item, [s for s in _sentences(document.text)
                                           if len(s) <= MAX_SENTENCE_CHARS]))
    kept = {chunk_id: [] for chunk_id, _item, _pool in pools}
    turns = [(chunk_id, pool[depth]) for depth in range(max((len(p) for *_, p in pools), default=0))
             for chunk_id, _item, pool in pools if depth < len(pool)]
    taken = 0
    for chunk_id, sentence in turns[:MAX_SENTENCES]:
        kept[chunk_id].append(sentence)
        if not _fits(question, _evidence((c, i, kept[c]) for c, i, _p in pools)):
            kept[chunk_id].pop()
            break
        taken += 1
    evidence = _evidence((chunk_id, item, kept[chunk_id]) for chunk_id, item, _pool in pools)
    origins = {chunk_id: origins[chunk_id] for chunk_id in (e.chunk_id for e in evidence)}
    provider_input = None if not evidence else ProviderInput(
        question=question.text, context={}, evidence=evidence, decision_summary=NOTICE)
    return Prepared(question, user, provider_input, origins, truncated=taken < len(turns),
                    items={item: access[user][item].label for item in question.items})


def assert_permitted_input(prepared: Prepared, restricted_only: frozenset[str]) -> None:
    """Before dispatch: a user refused restricted items gets no restricted content.

    Two independent checks: every evidence chunk comes from an item this user is expected to
    read, and no sentence in the input is one found only in restricted items.
    """
    if prepared.provider_input is None:
        return
    for chunk_id, item in prepared.origins.items():
        if _expected(prepared.user, item) != "allowed":
            raise RestrictedContentInModelInput(
                f"{prepared.user} {prepared.question.id}: input would include {item}")
    if EXPECTED[(prepared.user, "restricted")] == "denied":
        for sentence in number_sentences(prepared.provider_input):
            if _normal(sentence.text) in restricted_only:
                raise RestrictedContentInModelInput(
                    f"{prepared.user} {prepared.question.id}: input would include a sentence "
                    "found only in restricted items")


class GuardedTransport(httpx.AsyncBaseTransport):
    """Re-checks the request bytes just before they leave, then forwards them.

    ``forbidden`` is set before each call to the restricted-only sentences for a refused user,
    or emptied for a user permitted to read them. The inner transport is shared across calls and
    closed by :meth:`close_inner`; the provider closing its client does not close it.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None):
        self._inner = inner or httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.forbidden: frozenset[str] = frozenset()

    async def handle_async_request(self, request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        if any(_normal(item["text"]) in self.forbidden for item in payload["sentences"]):
            raise RestrictedContentInModelInput("Request carried restricted-only content")
        return await self._inner.handle_async_request(request)

    async def aclose(self):
        pass

    async def close_inner(self):
        await self._inner.aclose()


# --- Questions ------------------------------------------------------------------------------

def _fingerprints(provider_input):
    return [] if provider_input is None else [
        {"item": evidence.source_locator, "sha256": evidence.content_hash}
        for evidence in provider_input.evidence]


def _row(prepared: Prepared) -> dict:
    return {"user": prepared.user, "question": prepared.question.id,
            "aim": prepared.question.aim, "items": dict(prepared.items),
            "evidence": _fingerprints(prepared.provider_input),
            "evidence_truncated": prepared.truncated, "model_called": False}


async def ask(prepared: Prepared, provider, restricted_only, guard) -> dict:
    """One question, at most one model call, and the claim gate before anything is released."""
    row = _row(prepared)
    if prepared.provider_input is None:
        return row | {"query_status": "insufficient_evidence"}
    assert_permitted_input(prepared, restricted_only)
    if guard is not None:
        guard.forbidden = (restricted_only if EXPECTED[(prepared.user, "restricted")] == "denied"
                           else frozenset())
    try:
        output, _record = await provider.generate_with_record(prepared.provider_input)
    except ProviderAbstained:
        return row | {"model_called": True, "query_status": "model_abstained"}
    except ProviderCallFailed as failed:
        return row | {"model_called": True, "query_status": "provider_failed",
                      "error_category": failed.category,
                      "retry_after_seconds": failed.retry_after_seconds}
    except BudgetExhausted:
        return row | {"query_status": "not_sent", "stop": "budget_exhausted"}
    except ExternalProviderUnavailable:
        # The only other refusal once a request is built is a recorded provider cooldown.
        return row | {"query_status": "not_sent", "stop": "provider_rate_limited"}
    except ValueError:
        # Raised before any reservation: nothing sendable within the input bound.
        return row | {"query_status": "not_sent", "reason": "input_not_sendable"}
    evidence = {item.chunk_id: item.text for item in prepared.provider_input.evidence}
    claims = evaluate_claim_support(
        answer=output.answer, citation_ids=output.citation_ids, evidence=evidence,
        notices=[NOTICE], locators=dict(prepared.origins), provider_mode=provider.mode,
        mode="live" if provider.mode == "live_grounded" else "simulated")
    released = (claims["all_supported"] and claims["denominator"] > 0
                and set(output.citation_ids) <= set(evidence))
    return row | {"model_called": True,
                  "query_status": "released" if released else "blocked_by_claim_gate",
                  "cited_items": sorted({prepared.origins[c] for c in output.citation_ids})
                  if released else [],
                  "claims": {"denominator": claims["denominator"],
                             "supported": claims["supported_claims"]}}


async def ask_all(prepared_list, provider, restricted_only, *, pace, guard=None):
    """Ask in order; returns ``(rows, stop reason or None)``."""
    rows, wait, stopped = [], 0.0, None
    for prepared in prepared_list:
        if stopped:
            rows.append(_row(prepared) | {"query_status": "not_sent", "reason": stopped})
            continue
        if wait and prepared.provider_input is not None:
            # Pacing, not a retry: each question is sent at most once.
            await _sleep(wait)
            wait = 0.0
        row = await ask(prepared, provider, restricted_only, guard)
        rows.append(row)
        if row["model_called"]:
            wait = pace
        retry_after = row.get("retry_after_seconds")
        if row.get("stop"):
            stopped = row.pop("stop")
        elif row.get("error_category") == "rate_limited":
            # Without a validated reset time, a later call would guess at capacity.
            if retry_after is None or retry_after > LONG_RETRY_AFTER_SECONDS:
                stopped = "provider_rate_limited"
            else:
                wait = max(pace, retry_after + PACING_MARGIN_SECONDS)
    return rows, stopped


def assess(rows, planned, access_ok, input_ok):
    """Return ``(verdict, checks)``; an unobserved check (None) cannot make a pass."""
    questions = {question.id: question for question in QUESTIONS}
    completed = [row for row in rows
                 if row["model_called"] and row["query_status"] != "provider_failed"]
    restricted_only_for_refused = [
        row for row in rows if all(_expected(row["user"], item) == "denied"
                                   for item in questions[row["question"]].items)]
    checks = {
        "access_split_as_expected": access_ok,
        "restricted_never_in_refused_users_model_input": input_ok,
        "no_unsupported_claim_released": None if not rows else all(
            row["claims"]["denominator"] == row["claims"]["supported"]
            for row in rows if row["query_status"] == "released"),
        "restricted_only_questions_made_no_call_for_refused_users": None if not rows else all(
            not row["model_called"] for row in restricted_only_for_refused),
        "completed_calls": f"{len(completed)}/{planned}",
    }
    flags = [value for name, value in checks.items() if name != "completed_calls"]
    if any(value is False for value in flags):
        return "fail", checks
    if any(value is None for value in flags) or len(completed) < planned:
        return "inconclusive", checks
    return "pass", checks


def run_experiment(targets, tokens, *, provider, platform_transport=None, guard=None,
                   pace=0.0) -> dict:
    """Read the items, check the access split, then ask the questions. Returns the report."""
    access = read_items(targets, tokens, transport=platform_transport)
    report = {"access": {user: {item: result.label for item, result in access[user].items()}
                         for user in USERS}, "planned_calls": 0, "rows": []}
    mismatches = access_mismatches(access)
    if mismatches:
        # Nothing reaches the model unless the platforms enforce exactly the expected split.
        verdict, checks = assess([], 0, False, None)
        return report | {"result": verdict, "checks": checks,
                         "stopped": "access_split_not_as_expected",
                         "access_mismatches": mismatches}
    restricted_only = restricted_only_sentences(access)
    prepared = [prepare(user, question, access) for user in USERS for question in QUESTIONS]
    planned = sum(item.provider_input is not None for item in prepared)
    input_ok = True
    try:
        rows, stopped = asyncio.run(_ask_and_close(prepared, provider, restricted_only, pace,
                                                   guard))
    except RestrictedContentInModelInput:
        # Nothing after this point is sent; earlier rows are dropped with the run.
        rows, input_ok, stopped = [], False, "restricted_content_in_model_input"
    verdict, checks = assess(rows, planned, True, input_ok)
    return report | {"result": verdict, "checks": checks, "planned_calls": planned,
                     "stopped": stopped, "rows": rows}


async def _ask_and_close(prepared, provider, restricted_only, pace, guard):
    try:
        return await ask_all(prepared, provider, restricted_only, pace=pace, guard=guard)
    finally:
        if guard is not None:
            await guard.close_inner()


# --- Dry run --------------------------------------------------------------------------------

DRY_TEXT = {
    "confluence.general": ("Morning handover", "<p>The Singapore morning handover is complete. "
                           "Two payment batches were released on time.</p>"),
    "confluence.restricted": ("Exception note", "<p>Exception EXC-DEMO-7429 is held for "
                              "independent beneficiary verification. The callback did not "
                              "match the beneficiary record.</p>"),
    "jira.general": ("Review five processing supplier payments", None),
    "jira.restricted": ("Complete independent beneficiary verification", None),
    "slack.general": "Morning batches cleared; the handover note is up to date.",
    "slack.restricted": "The second reviewer must call the beneficiary back before release.",
    "drive.general": "Reconciliation: five supplier payments match the ledger totals.",
    "drive.restricted": "Invoice CQ-DEMO-2048 bank details differ from the vendor master.",
}
_DRY_IDS = {"confluence": ("101", "202"), "jira": ("OPS-1", "CASE-2"),
            "slack": ("CGEN", "GRES"), "drive": ("fileGen", "fileRes")}
_DRY_PARENT = {"confluence": "OPS", "drive": "folder1"}
_DRY_ACCOUNTS = {"A": {"atlassian": "acct-a", "slack": "UAAA", "drive": "perm-a"},
                 "B": {"atlassian": "acct-b", "slack": "UBBB", "drive": "perm-b"}}
_DRY_WHEN = "2026-10-12T01:00:00.000Z"


def dry_targets() -> dict:
    """Fictional targets in the shape of ``eval/live_access/targets.example.json``."""
    items = {}
    for platform, (general, restricted) in _DRY_IDS.items():
        items[platform] = {}
        for kind, item_id in (("general", general), ("restricted", restricted)):
            item = {"label": f"{platform} {kind}", "id": item_id}
            if platform != "slack":
                item["parent"] = item_id.split("-")[0] if platform == "jira" \
                    else _DRY_PARENT[platform]
            items[platform][kind] = item
    return {"atlassian_site": "https://dry-run.atlassian.net", "slack_workspace_id": "T123",
            "users": {user: {"atlassian_email": f"{user.lower()}@example.com",
                             "atlassian_account_id": _DRY_ACCOUNTS[user]["atlassian"],
                             "slack_user_id": _DRY_ACCOUNTS[user]["slack"],
                             "drive_permission_id": _DRY_ACCOUNTS[user]["drive"]}
                      for user in USERS},
            "items": items}


def dry_tokens() -> dict:
    return {user: {"atlassian": secrets.token_urlsafe(16), "slack": "xoxp-" + secrets.token_hex(8),
                   "drive": secrets.token_urlsafe(16)} for user in USERS}


def dry_platforms(tokens, *, b_reads_restricted=False) -> httpx.MockTransport:
    """Fictional four-platform server; B is refused restricted items unless told otherwise."""
    by_id = {item_id: f"{platform}.{kind}" for platform, ids in _DRY_IDS.items()
             for kind, item_id in zip(KINDS, ids)}

    def user_of(request):
        scheme, value = request.headers["authorization"].split(" ", 1)
        credential = (base64.b64decode(value).decode().split(":", 1)[1] if scheme == "Basic"
                      else value)
        return next(user for user, values in tokens.items() if credential in values.values())

    def handler(request):
        user, path = user_of(request), request.url.path

        def refused(item_id):
            return (user == "B" and not b_reads_restricted
                    and by_id.get(item_id, "").endswith(".restricted"))

        if path in {"/wiki/rest/api/user/current", "/rest/api/3/myself"}:
            return httpx.Response(200, json={"accountId": _DRY_ACCOUNTS[user]["atlassian"]})
        if path.startswith("/wiki/rest/api/content/"):
            page = path.rsplit("/", 1)[1]
            if refused(page):
                return httpx.Response(404)
            title, body = DRY_TEXT[by_id[page]]
            return httpx.Response(200, json={
                "id": page, "type": "page", "status": "current", "space": {"key": "OPS"},
                "version": {"number": 1, "when": _DRY_WHEN}, "title": title,
                "body": {"storage": {"value": body}}})
        if path.startswith("/rest/api/3/issue/"):
            key = path.rsplit("/", 1)[1]
            if refused(key):
                return httpx.Response(404)
            return httpx.Response(200, json={"key": key, "fields": {
                "summary": DRY_TEXT[by_id[key]][0], "description": None, "updated": _DRY_WHEN,
                "project": {"key": key.split("-")[0]}, "status": {"name": "In Review"}}})
        if path == "/api/auth.test":
            return httpx.Response(200, json={"ok": True, "user_id": _DRY_ACCOUNTS[user]["slack"],
                                             "team_id": "T123", "url": "https://dry-run.slack.com/"})
        if path == "/api/conversations.info":
            channel = request.url.params["channel"]
            if refused(channel):
                return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
            return httpx.Response(200, json={"ok": True, "channel": {
                "id": channel, "is_im": False, "is_mpim": False,
                "is_private": by_id[channel].endswith(".restricted"), "is_member": True}})
        if path == "/api/conversations.history":
            channel = request.url.params["channel"]
            return httpx.Response(200, json={"ok": True, "has_more": False, "messages": [
                {"type": "message", "ts": "1760230000.000100", "text": DRY_TEXT[by_id[channel]]}]})
        if path == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"permissionId": _DRY_ACCOUNTS[user]["drive"]}})
        if path.startswith("/drive/v3/files/"):
            file_id = path.split("/")[4]
            if refused(file_id):
                return httpx.Response(404)
            if request.url.params.get("alt") == "media":
                return httpx.Response(200, text=DRY_TEXT[by_id[file_id]])
            return httpx.Response(200, json={
                "id": file_id, "name": "file.md", "mimeType": "text/markdown",
                "parents": ["folder1"], "trashed": False, "version": "3",
                "modifiedTime": _DRY_WHEN})
        return httpx.Response(500)
    return httpx.MockTransport(handler)


def dry_model(seen=None) -> httpx.MockTransport:
    """Fake model that selects every sentence it is sent."""
    def handler(request):
        if seen is not None:
            seen.append(request)
        sentences = json.loads(json.loads(request.content)["messages"][1]["content"])["sentences"]
        content = json.dumps({"answerable": True, "sentence_ids": [s["id"] for s in sentences]})
        return httpx.Response(200, json={
            "id": "dry_run", "model": EVAL_CONFIG.model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                      "completion_tokens_details": {"reasoning_tokens": 0}}})
    return httpx.MockTransport(handler)


# --- Entry point ----------------------------------------------------------------------------

_SAFE_KEYS = frozenset({"user", "question", "aim", "items", "evidence", "evidence_truncated",
                        "model_called", "query_status", "cited_items", "claims", "error_category",
                        "retry_after_seconds", "reason", "stop"})
_ITEM_LABEL = re.compile(r"(?:confluence|jira|slack|drive)\.(?:general|restricted)")


def _check_report(report) -> None:
    """Rows hold only the allowed fields, and cited items only ``platform.kind`` labels."""
    for row in report["rows"]:
        if set(row) - _SAFE_KEYS:
            raise AssertionError(f"Unexpected report field: {sorted(set(row) - _SAFE_KEYS)}")
        for label in row.get("cited_items", []) + [e["item"] for e in row.get("evidence", [])]:
            if not _ITEM_LABEL.fullmatch(label):
                raise AssertionError("Report label is not a platform.kind label")


def _room(ledger, planned):
    spend = ledger.summary()
    per_call = reserve_budget(EVAL_CONFIG, approved_rates()).reservation_usd
    room = spend["max_requests"] - spend["requests"]
    room_usd = Decimal(spend["max_usd"]) - Decimal(spend["spend_usd"])
    if room < planned or room_usd < per_call * planned:
        return (f"Not enough approved budget for a full run: {planned} calls planned, "
                f"{max(room, 0)} requests and USD {max(room_usd, 0)} left "
                f"(USD {per_call * planned} needed). Nothing was sent.")
    cooldown = ledger.cooldown_until()
    if cooldown is not None and cooldown > datetime.now(UTC):
        return f"Provider rate limit in effect until {cooldown.isoformat()}. Nothing was sent."
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="fake platforms and model; no token, key or network (the default)")
    mode.add_argument("--live", action="store_true", help="real calls (needs --yes)")
    parser.add_argument("--yes", action="store_true", help="confirm real calls")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--pace", type=float, default=None,
                        help="seconds between model calls (default 30 live, 0 dry run; "
                             "live at least 30)")
    args = parser.parse_args(argv)
    if args.pace is None:
        args.pace = MIN_LIVE_PACE_SECONDS if args.live else 0.0
    if not math.isfinite(args.pace) or args.pace < 0:
        print("--pace must be finite and nonnegative. Nothing was sent.", file=sys.stderr)
        return 2
    if args.live:
        if not args.yes:
            print("Real calls need --live --yes.", file=sys.stderr)
            return 2
        if args.pace < MIN_LIVE_PACE_SECONDS:
            print(f"--pace must be at least {MIN_LIVE_PACE_SECONDS:g} s for real calls. "
                  "Nothing was sent.", file=sys.stderr)
            return 2
        problems = approval_problems()
        if problems:
            # Checked before any token, key or targets file is opened.
            print("No approval recorded for real platform data: " + "; ".join(problems)
                  + ". See eval/live_platform_model/README.md. Nothing was read or sent.",
                  file=sys.stderr)
            return 2
        ledger = SpendLedger(ledger_path(), max_requests=APPROVED_MAX_REQUESTS,
                             max_usd=APPROVED_MAX_USD)
    else:
        per_call = reserve_budget(EVAL_CONFIG, approved_rates()).reservation_usd
        ledger = SpendLedger(Path(tempfile.mkdtemp()) / "dry-ledger.jsonl",
                             max_requests=MAX_PLANNED_CALLS, max_usd=per_call * MAX_PLANNED_CALLS)
    refusal = _room(ledger, MAX_PLANNED_CALLS)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    try:
        if args.live:
            tokens = access_check.load_tokens(args.tokens)
            targets = access_check.load_targets(args.targets)
            credential = load_credential(args.key, project_root=ROOT)
            platform_transport, guard = None, GuardedTransport()
        else:
            tokens, targets = dry_tokens(), dry_targets()
            credential = "dry-run-" + secrets.token_hex(8)
            platform_transport, guard = dry_platforms(tokens), GuardedTransport(dry_model())
    except (access_check.SetupError, SetupError, ExternalProviderUnavailable, OSError,
            ValueError) as error:
        print(f"Setup error: {error}", file=sys.stderr)
        return 2
    provider = LiveGroundedProvider(EVAL_CONFIG, credential=credential, ledger=ledger,
                                    transport=guard)
    print(f"Spend so far: {ledger.summary()}")
    print(f"At most {MAX_PLANNED_CALLS} model calls, {args.pace:g} s apart; nothing is retried.")
    report = run_experiment(targets, tokens, provider=provider, guard=guard,
                            platform_transport=platform_transport, pace=args.pace)
    _check_report(report)
    report = {"result": report.pop("result"), "mode": "live" if args.live else "dry_run",
              "model": EVAL_CONFIG.model, "service": EVAL_CONFIG.service,
              "approval_date": APPROVAL_DATE if args.live else None,
              "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "data": ("named live test items only" if args.live
                       else "fictional dry-run fixtures"),
              "stores": "access, query status, cited item labels and SHA-256 fingerprints only",
              "spend_after": ledger.summary()} | report
    for row in report["rows"]:
        print(f"  {row['user']} {row['question']}: {row['query_status']} "
              f"{' '.join(row.get('cited_items', []))}")
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"{'live' if args.live else 'dry'}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": report["result"], "checks": report["checks"],
                      "stopped": report["stopped"]}, indent=2))
    print(f"Saved {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return {"pass": 0, "fail": 1, "inconclusive": 3}[report["result"]]


if __name__ == "__main__":
    raise SystemExit(main())
