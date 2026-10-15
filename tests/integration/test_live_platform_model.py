"""Owner-run platform-to-model experiment, exercised offline with fake platforms and model."""

import asyncio
import importlib.util
import json
import secrets
import socket
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from aspire_brain.providers import ProviderOutput
from aspire_brain.providers.live import ENVELOPE_BYTES, LiveGroundedProvider, SpendLedger

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_platform_model_run",
                                              ROOT / "eval/live_platform_model/run.py")
run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = run  # dataclasses look their module up while the script loads
spec.loader.exec_module(run)

KEY = "gsk_" + secrets.token_hex(16)
RESTRICTED_SENTENCES = [
    "Exception EXC-DEMO-7429 is held for independent beneficiary verification.",
    "The callback did not match the beneficiary record.",
    "The second reviewer must call the beneficiary back before release.",
    "Invoice CQ-DEMO-2048 bank details differ from the vendor master.",
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
    monkeypatch.setattr(run, "_sleep", sleep)
    return waits


def sent_sentences(request):
    payload = json.loads(json.loads(request.content)["messages"][1]["content"])
    return [item["text"] for item in payload["sentences"]]


def groq(reply=None, *, seen, status=200, headers=None):
    """Fake model: selects every sentence unless ``reply`` says otherwise."""
    def handler(request):
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"type": "rate_limit_error"}},
                                  headers=headers)
        ids = [f"S{n}" for n in range(1, len(sent_sentences(request)) + 1)]
        content = json.dumps(reply or {"answerable": True, "sentence_ids": ids})
        return httpx.Response(200, json={
            "id": "req_1", "model": run.EVAL_CONFIG.model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 40,
                      "completion_tokens_details": {"reasoning_tokens": 20}}})
    return httpx.MockTransport(handler)


def experiment(tmp_path, model_transport, *, pace=0.0, b_reads_restricted=False, provider=None):
    tokens, targets = run.dry_tokens(), run.dry_targets()
    guard = run.GuardedTransport(model_transport)
    provider = provider or LiveGroundedProvider(
        run.EVAL_CONFIG, credential=KEY, transport=guard,
        ledger=SpendLedger(tmp_path / "ledger.jsonl", max_requests=7, max_usd=Decimal("0.01")))
    report = run.run_experiment(
        targets, tokens, provider=provider, guard=guard, pace=pace,
        platform_transport=run.dry_platforms(tokens, b_reads_restricted=b_reads_restricted))
    return report, tokens, targets


def test_dry_run_passes_and_stores_no_text_identifiers_or_secrets(tmp_path):
    assert run.main(["--dry-run", "--out", str(tmp_path)]) == 0
    [saved] = tmp_path.glob("dry-*.json")
    report = json.loads(saved.read_text())
    assert report["result"] == "pass" and report["mode"] == "dry_run"
    assert report["planned_calls"] == run.MAX_PLANNED_CALLS == 7
    assert report["access"]["B"]["drive.restricted"] == "denied"
    by_key = {(row["user"], row["question"]): row for row in report["rows"]}
    assert by_key[("B", "beneficiary-exception")]["query_status"] == "insufficient_evidence"
    assert by_key[("B", "restricted-invoice")]["cited_items"] == ["drive.general"]
    assert by_key[("A", "restricted-invoice")]["cited_items"] == ["drive.general",
                                                                  "drive.restricted"]
    assert all(len(item["sha256"]) == 64 for row in report["rows"] for item in row["evidence"])
    text = saved.read_text()
    for private in ("example.com", "acct-a", "UAAA", "perm-b", "T123", "dry-run.atlassian",
                    "dry-run.slack", "fileRes", "CGEN", "OPS-1", "CASE-2", "folder1"):
        assert private not in text
    for sentence in RESTRICTED_SENTENCES + ["Morning batches cleared"]:
        assert sentence not in text
    # The dry run never creates or touches a real ledger.
    assert not run.ledger_path().exists()


def test_refused_user_model_input_never_carries_restricted_content(tmp_path):
    seen = []
    report, _tokens, _targets = experiment(tmp_path, groq(seen=seen))
    assert report["result"] == "pass", report["checks"]
    # A asks four questions first, then B three (B's restricted-only question sends nothing).
    assert len(seen) == 7
    a_wire = "".join(" ".join(sent_sentences(request)) for request in seen[:4])
    b_wire = "".join(request.content.decode() for request in seen[4:])
    for sentence in RESTRICTED_SENTENCES:
        assert sentence in a_wire  # A may read it, so the check has something to find
        assert sentence not in b_wire
    assert "Reconciliation: five supplier payments" in b_wire
    for request in seen:
        wire = request.content.decode()
        for private in ("example.com", "acct-", "T123", "atlassian.net", "fileRes", "GRES"):
            assert private not in wire


def test_wrong_access_split_stops_before_any_model_call(tmp_path):
    seen = []
    report, _tokens, _targets = experiment(tmp_path, groq(seen=seen), b_reads_restricted=True)
    assert seen == []
    assert report["result"] == "fail" and report["rows"] == []
    assert report["stopped"] == "access_split_not_as_expected"
    assert report["checks"]["access_split_as_expected"] is False
    assert "B drive.restricted: expected denied, observed allowed" in report["access_mismatches"]


def test_wrong_person_token_is_an_error_and_nothing_is_sent(tmp_path):
    seen = []
    tokens, targets = run.dry_tokens(), run.dry_targets()
    swapped = tokens | {"B": tokens["A"]}
    guard = run.GuardedTransport(groq(seen=seen))
    provider = LiveGroundedProvider(run.EVAL_CONFIG, credential=KEY, transport=guard,
                                    ledger=SpendLedger(tmp_path / "ledger.jsonl"))
    report = run.run_experiment(targets, swapped, provider=provider, guard=guard,
                                platform_transport=run.dry_platforms(swapped))
    assert seen == []
    assert report["access"]["B"]["jira.general"] == "error:identity_mismatch"
    assert report["stopped"] == "access_split_not_as_expected"


def _access(general_text, restricted_text, *, b_restricted="denied"):
    def entry(observed, text):
        documents = (SimpleNamespace(text=text),) if observed == "allowed" else ()
        return run.Access(observed, documents=documents)
    access = {}
    for user in run.USERS:
        restricted = "allowed" if user == "A" else b_restricted
        access[user] = {f"{platform}.{kind}": entry("allowed" if kind == "general"
                                                   else restricted,
                                                   general_text if kind == "general"
                                                   else restricted_text)
                        for platform in run.PLATFORMS for kind in run.KINDS}
    return access


def test_pre_dispatch_check_refuses_a_restricted_item_for_b():
    access = _access("General note.", "Restricted note.", b_restricted="allowed")
    question = next(q for q in run.QUESTIONS if q.id == "restricted-invoice")
    prepared = run.prepare("B", question, access)
    assert "drive.restricted" in prepared.origins.values()
    with pytest.raises(run.RestrictedContentInModelInput, match="drive.restricted"):
        run.assert_permitted_input(prepared, frozenset())
    # A is expected to read it, so the same input is permitted for A.
    run.assert_permitted_input(run.prepare("A", question, access), frozenset())


def test_pre_dispatch_check_refuses_restricted_only_sentences_for_b():
    access = _access("General note. Secret amount is 900.", "Secret amount is 900.")
    restricted_only = run.restricted_only_sentences(
        _access("General note.", "Secret amount is 900."))
    assert restricted_only == {"secret amount is 900."}
    question = next(q for q in run.QUESTIONS if q.id == "handover-status")
    with pytest.raises(run.RestrictedContentInModelInput, match="only in restricted"):
        run.assert_permitted_input(run.prepare("B", question, access), restricted_only)
    # A sentence that also appears in a general item is not restricted-only.
    assert run.restricted_only_sentences(access) == frozenset()


def test_restricted_content_found_before_dispatch_stops_the_run(tmp_path, monkeypatch):
    seen = []
    original = run.prepare

    def leaky(user, question, access):
        prepared = original(user, question, access)
        if user == "B" and prepared.provider_input is not None:
            prepared.origins = {chunk: "drive.restricted" for chunk in prepared.origins}
        return prepared
    monkeypatch.setattr(run, "prepare", leaky)
    report, _tokens, _targets = experiment(tmp_path, groq(seen=seen))
    assert len(seen) == 4  # A's calls only; B's first call never left
    assert report["result"] == "fail" and report["rows"] == []
    assert report["stopped"] == "restricted_content_in_model_input"
    assert report["checks"]["restricted_never_in_refused_users_model_input"] is False


def test_request_bytes_are_checked_again_before_sending(tmp_path):
    seen = []
    guard = run.GuardedTransport(groq(seen=seen))
    guard.forbidden = frozenset({"secret amount is 900."})
    provider = LiveGroundedProvider(run.EVAL_CONFIG, credential=KEY, transport=guard,
                                    ledger=SpendLedger(tmp_path / "ledger.jsonl"))
    access = _access("Secret amount is 900.", "Restricted note.")
    prepared = run.prepare("B", run.QUESTIONS[0], access)
    with pytest.raises(run.RestrictedContentInModelInput):
        asyncio.run(provider.generate_with_record(prepared.provider_input))
    assert seen == []


def test_unsupported_answer_is_blocked_by_the_claim_gate(tmp_path):
    class Inventing:
        mode = "live_grounded"

        async def generate_with_record(self, context):
            return ProviderOutput(answer=context.decision_summary + "\nAll payments are approved.",
                                  citation_ids=[context.evidence[0].chunk_id]), None
    report, _tokens, _targets = experiment(tmp_path, groq(seen=[]), provider=Inventing())
    called = [row for row in report["rows"] if row["model_called"]]
    assert len(called) == 7
    assert {row["query_status"] for row in called} == {"blocked_by_claim_gate"}
    assert all(row["cited_items"] == [] for row in called)
    assert report["checks"]["no_unsupported_claim_released"] is True


def test_model_abstention_releases_nothing(tmp_path):
    report, _tokens, _targets = experiment(
        tmp_path, groq({"answerable": False, "sentence_ids": []}, seen=[]))
    statuses = {row["query_status"] for row in report["rows"] if row["model_called"]}
    assert statuses == {"model_abstained"}
    assert not any(row.get("cited_items") for row in report["rows"])


@pytest.mark.parametrize("headers", [{"retry-after": "3600"}, {}])
def test_long_or_unknown_rate_limit_stops_without_retry(tmp_path, headers):
    seen = []
    report, _tokens, _targets = experiment(tmp_path, groq(seen=seen, status=429,
                                                           headers=headers))
    assert len(seen) == 1
    assert report["rows"][0]["error_category"] == "rate_limited"
    assert report["stopped"] == "provider_rate_limited"
    assert {row["query_status"] for row in report["rows"][1:]} == {"not_sent"}
    assert report["result"] == "inconclusive"


def test_short_rate_limit_paces_the_next_call(tmp_path, monkeypatch, no_waiting):
    # Sleeping is faked here, so the ledger's recorded cooldown would otherwise still be running.
    monkeypatch.setattr(SpendLedger, "cooldown_until", lambda self: None)
    seen, calls = [], [0]
    inner = groq(seen=seen)

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            seen.append(request)
            return httpx.Response(429, json={"error": {"type": "rate_limit_error"}},
                                  headers={"retry-after": "40"})
        return inner.handle_request(request)
    report, _tokens, _targets = experiment(tmp_path, httpx.MockTransport(handler), pace=30)
    assert len(seen) == 7 and report["stopped"] is None
    assert no_waiting == [42.0] + [30] * 5
    assert report["checks"]["completed_calls"] == "6/7"


def test_long_documents_are_cut_to_whole_sentences_within_the_input_bound():
    sentences = [f"Line {n} of the handover records a fictional settlement step." for n in
                 range(200)]
    access = _access(" ".join(sentences), "Restricted note.")
    prepared = run.prepare("A", run.QUESTIONS[0], access)
    assert prepared.truncated
    sent = run.number_sentences(prepared.provider_input)
    assert {item.text for item in sent} <= set(sentences)
    body = run.canonical_json(run.request_body(run.QUESTIONS[0].text, sent, run.EVAL_CONFIG))
    assert len(body.encode()) + ENVELOPE_BYTES <= run.EVAL_CONFIG.input_token_cap
    # Both readable items keep a share of the input.
    assert set(prepared.origins.values()) == {"confluence.general", "slack.general"}


def test_live_refuses_without_an_approval_before_reading_anything(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Read a token, key or targets file without an approval")
    monkeypatch.setattr(run.access_check, "load_tokens", forbidden)
    monkeypatch.setattr(run.access_check, "load_targets", forbidden)
    monkeypatch.setattr(run, "load_credential", forbidden)
    assert run.approval_problems() == ["APPROVAL_DATE is not set",
                                       "APPROVED_MAX_REQUESTS is not set",
                                       "APPROVED_MAX_USD is not set"]
    assert run.main(["--live", "--yes"]) == 2
    assert "No approval recorded" in capsys.readouterr().err
    assert not run.ledger_path().exists()


def test_filled_approval_uses_its_own_ledger(monkeypatch):
    monkeypatch.setattr(run, "APPROVAL_DATE", "2026-10-20")
    monkeypatch.setattr(run, "APPROVED_MAX_REQUESTS", 7)
    monkeypatch.setattr(run, "APPROVED_MAX_USD", Decimal("0.01"))
    assert run.approval_problems() == []
    assert run.ledger_path().name == "live-platform-ledger-2026-10-20.jsonl"
    assert run.ledger_path() not in run.FOREIGN_LEDGERS
    monkeypatch.setattr(run, "ledger_path",
                        lambda: ROOT / "var" / "provider" / "live-ledger.jsonl")
    assert "the ledger path belongs to another approval" in run.approval_problems()


@pytest.mark.parametrize("argv", [["--live"], ["--live", "--yes", "--pace", "5"],
                                  ["--dry-run", "--pace", "nan"]])
def test_unsafe_arguments_are_refused(argv):
    assert run.main(argv) == 2


def test_live_and_dry_run_are_exclusive():
    with pytest.raises(SystemExit):
        run.main(["--live", "--dry-run", "--yes"])
