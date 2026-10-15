"""Owner-run check of the integrated application path against real platform accounts.

It runs the same code the web application runs with ``ASPIRE_PLATFORM_SOURCE=connectors``:
discovery and ingestion through each user's own token, the synchronizer, the shared index, the
query service with its query-time re-check, and saved-answer re-reads. Three steps:

* ``ingest``: sync all four platforms, then ask questions as user A and user B. A pass needs
  positive evidence, not just the absence of a leak: every platform synced and indexed at least
  one record; on every platform the general target item is readable by both users and the
  restricted one by A alone; every general question is answered, with citations, for both
  users; A's restricted question cites a restricted item and B's never does; and the citations
  together span all four platforms. An empty or unreachable workspace therefore fails.
* ``freshness`` (interactive): you edit the general Confluence page, adding a phrase you choose;
  the script syncs every ``--poll`` seconds and measures, on the wall clock, how long until an
  answer quotes the phrase. Pass means within the one-hour budget.
* ``revocation`` (interactive): you remove A's access to the restricted Confluence page; the
  script asks again at once, without a sync, and confirms the page is no longer quoted and A's
  earlier saved answer is closed; then it syncs and confirms the grant is gone from the index.

Results keep outcomes, counts, timings and hashes only. No document text, tokens, emails or
item IDs are written. Usage, from the repository root:

    python eval/live_platform/check.py ingest
    python eval/live_platform/check.py freshness --phrase "standby failover drill"
    python eval/live_platform/check.py revocation --question "Why is the payment held?"
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aspire_brain.audit import AuditWriter  # noqa: E402
from aspire_brain.auth import AccessDenied, AuthService  # noqa: E402
from aspire_brain.db import Database  # noqa: E402
from aspire_brain.platforms.connected import (  # noqa: E402
    ConnectorConfigError,
    load_connector_config,
    load_tokens,
)
from aspire_brain.platforms.runtime import connector_runtime  # noqa: E402
from aspire_brain.web.cases import run_typed_query, typed_service  # noqa: E402

DEFAULT_TARGETS = ROOT / "var" / "live-access" / "targets.json"
DEFAULT_TOKENS = Path("~/.config/seaglass/live-access-tokens.json").expanduser()
DEFAULT_OUT = ROOT / "var" / "live-platform"
#: ``(question, kind)``. A ``general`` question must be answered, with citations, for both users;
#: a ``restricted`` one must cite a restricted item for A and none for B. Pass ``--questions``
#: with a JSON list of ``{"question": ..., "kind": ...}`` to match your own workspace content.
DEFAULT_QUESTIONS = (
    ("How many supplier payments need manual review in the morning handover?", "general"),
    ("Why is the Cedar Quay payment held?", "restricted"),
    ("What is being done about processing payments and what evidence remains missing?", "general"),
)
PLATFORMS = ("confluence", "jira", "slack", "drive")
ANSWERED = {"answered", "partial"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


class Harness:
    """Builds the connector runtime and a throwaway database holding the demo principals."""

    def __init__(self, targets_path: Path, tokens: dict, *, transport_for=None, clock=None):
        config_path = Path(tempfile.mkdtemp()) / "connectors.json"
        config_path.write_text(json.dumps({"targets_file": str(targets_path), "allow_live": True}))
        self.config = load_connector_config(config_path, project_root=ROOT)
        self.targets = json.loads(Path(targets_path).read_text())
        self.runtime = connector_runtime(self.config, tokens, sync_interval_seconds=0,
                                         transport_for=transport_for, clock=clock)
        db = Database(Path(tempfile.mkdtemp()) / "live-check.db")
        db.initialize()
        db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
        self.audit = AuditWriter(db.path, secrets.token_bytes(32))
        self.audit.initialize()
        self.auth = AuthService(db)

    def restricted_ids(self) -> set[str]:
        items = self.targets.get("items", {})
        return {item.get("id") for platform in items.values()
                for kind, item in platform.items() if kind == "restricted" and item.get("id")}

    def cited_restricted(self, packet) -> bool:
        restricted = self.restricted_ids()
        return any(citation["source_id"] in restricted
                   or citation.get("parent_id") in restricted for citation in packet["citations"])

    def readable(self, principal, item_id) -> bool | None:
        """Whether ``principal`` can read the indexed item, or the items in the container,
        named ``item_id``. ``None`` when nothing with that ID was indexed at all."""
        index = self.runtime.index
        keys = [key for key, record in index.records.items()
                if item_id in (record.source_id, record.parent_id)]
        if not keys:
            return None
        person = {"id": principal, "tenant_id": self.runtime.tenant_id, "active": True}
        return any(index.can_read(person, *key) for key in keys)

    def ask(self, principal, question):
        return asyncio.run(run_typed_query(self.auth, self.audit, principal, question,
                                           runtime=self.runtime))["packet"]


def ingest(harness: Harness, questions=DEFAULT_QUESTIONS) -> dict:
    runs = harness.runtime.sync_all("live-check")
    index = harness.runtime.index
    rows = []
    for run in runs:
        indexed = sum(1 for key in index.records if key[0] == run["platform"])
        rows.append({"step": "sync", "platform": run["platform"], "outcome": run["outcome"],
                     "error": run.get("error"), "indexed_records": indexed,
                     "pass": run["outcome"] == "completed" and indexed > 0})
    synced = {run["platform"] for run in runs}
    rows += [{"step": "sync", "platform": platform, "outcome": "not_configured",
              "indexed_records": 0, "pass": False} for platform in PLATFORMS if platform not in synced]
    # Index coverage: each platform's general item is shared, its restricted item is A's alone.
    items = harness.targets.get("items", {})
    for platform in PLATFORMS:
        general = items.get(platform, {}).get("general", {}).get("id")
        restricted = items.get(platform, {}).get("restricted", {}).get("id")
        checks = {
            "general_readable_by_a": bool(general) and harness.readable("user-a", general) is True,
            "general_readable_by_b": bool(general) and harness.readable("user-b", general) is True,
            "restricted_readable_by_a": (bool(restricted)
                                         and harness.readable("user-a", restricted) is True),
            "restricted_hidden_from_b": (bool(restricted)
                                         and harness.readable("user-b", restricted) is False),
        }
        rows.append({"step": "coverage", "platform": platform, **checks,
                     "pass": all(checks.values())})
    cited_platforms = set()
    for question, kind in questions:
        for principal in ("user-a", "user-b"):
            packet = harness.ask(principal, question)
            restricted = harness.cited_restricted(packet)
            platforms = {citation["platform"] for citation in packet["citations"]}
            cited_platforms |= platforms
            answered = packet["query_status"] in ANSWERED and bool(packet["citations"])
            if principal == "user-b":
                ok = not restricted and (answered or kind == "restricted")
            else:
                ok = restricted if kind == "restricted" else answered
            rows.append({"step": "query", "principal": principal, "kind": kind,
                         "question_sha": _digest(question), "status": packet["query_status"],
                         "citations": len(packet["citations"]),
                         "cited_platforms": sorted(platforms), "restricted_cited": restricted,
                         "pass": ok})
    rows.append({"step": "answer_coverage", "cited_platforms": sorted(cited_platforms),
                 "missing_platforms": [p for p in PLATFORMS if p not in cited_platforms],
                 "pass": cited_platforms >= set(PLATFORMS)})
    return {"step": "ingest", "pass": all(row["pass"] for row in rows), "rows": rows}


def freshness(harness: Harness, phrase: str, *, prompt=input, sleep=time.sleep,
              monotonic=time.monotonic, poll_seconds=60, budget_seconds=3600) -> dict:
    harness.runtime.sync_all("live-check")
    prompt(f"Add the phrase {phrase!r} to the general Confluence page, save it, then press Enter. ")
    started = monotonic()
    while True:
        harness.runtime.sync_all("live-check")
        packet = harness.ask("user-b", phrase)
        if phrase.lower() in packet["answer"].lower():
            elapsed = round(monotonic() - started, 1)
            lags = [m for m in harness.runtime.status()["measurements"]
                    if m["platform"] == "confluence"]
            return {"step": "freshness", "pass": elapsed <= budget_seconds,
                    "visible_after_seconds": elapsed, "budget_seconds": budget_seconds,
                    "poll_seconds": poll_seconds,
                    "platform_reported_lag_seconds": lags[-1]["propagation_seconds"] if lags else None}
        if monotonic() - started > budget_seconds:
            return {"step": "freshness", "pass": False, "visible_after_seconds": None,
                    "budget_seconds": budget_seconds, "poll_seconds": poll_seconds}
        sleep(poll_seconds)


def revocation(harness: Harness, question: str, *, prompt=input, monotonic=time.monotonic) -> dict:
    harness.runtime.sync_all("live-check")
    before = harness.ask("user-a", question)
    rows = [{"check": "a_sees_restricted_before", "pass": harness.cited_restricted(before)}]
    prompt("Remove user A's access to the restricted Confluence page, then press Enter. ")
    started = monotonic()
    after = harness.ask("user-a", question)
    rows.append({"check": "not_quoted_before_any_sync", "pass": not harness.cited_restricted(after),
                 "seconds_after_change": round(monotonic() - started, 1)})
    service = typed_service(harness.auth, harness.audit, harness.runtime)
    try:
        service.packet("user-a", before["request_id"])
        closed = False
    except AccessDenied:
        closed = True
    rows.append({"check": "saved_answer_closed", "pass": closed})
    harness.runtime.sync_all("live-check")
    page = (harness.targets.get("items", {}).get("confluence", {}).get("restricted", {}).get("id"))
    account = harness.runtime.index.principal_map["user-a"]["confluence"]
    granted = account in harness.runtime.index.confluence_page_grants.get(page, frozenset())
    rows.append({"check": "grant_removed_after_sync", "pass": not granted})
    prompt("Give user A access again if you want to repeat the check, then press Enter. ")
    return {"step": "revocation", "pass": all(row["pass"] for row in rows), "rows": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=("ingest", "freshness", "revocation"))
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    parser.add_argument("--phrase", default="standby failover drill")
    parser.add_argument("--question", default="Why is the Cedar Quay payment held?")
    parser.add_argument("--poll", type=int, default=60)
    parser.add_argument("--questions", type=Path,
                        help='JSON list of {"question": ..., "kind": "general"|"restricted"}')
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        harness = Harness(args.targets, load_tokens(args.tokens, project_root=ROOT))
    except (ConnectorConfigError, OSError, ValueError) as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 2
    if args.step == "ingest":
        questions = DEFAULT_QUESTIONS
        if args.questions:
            questions = tuple((row["question"], row["kind"])
                              for row in json.loads(args.questions.read_text()))
            if not questions or any(kind not in {"general", "restricted"} for _, kind in questions):
                print("Setup error: questions need a kind of general or restricted", file=sys.stderr)
                return 2
        result = ingest(harness, questions)
    elif args.step == "freshness":
        result = freshness(harness, args.phrase, poll_seconds=args.poll)
    else:
        result = revocation(harness, args.question)
    result |= {"mode": "live", "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
               "stores": "outcomes, counts, timings and short hashes only"}
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"{args.step}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"\n{'PASS' if result['pass'] else 'FAIL'}; saved {out}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
