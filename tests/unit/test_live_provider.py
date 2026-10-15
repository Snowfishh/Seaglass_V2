"""Live grounded provider, exercised offline against a fake OpenAI-compatible endpoint."""

import asyncio
import json
import os
import secrets
import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from aspire_brain.config import Settings
from aspire_brain.main import create_app
from aspire_brain.models import Evidence
from aspire_brain.platforms.simulated import SimulatedPlatformState, SimulatedQueryService
from aspire_brain.providers import ExternalProviderUnavailable, ProviderInput, configured_provider
from aspire_brain.providers.live import (
    BudgetExhausted,
    LiveGroundedProvider,
    ProviderAbstained,
    ProviderCallFailed,
    SpendLedger,
    approved_live_config,
)
from aspire_brain.providers.runtime import SUPPORTED_TARGET_ENDPOINT, SUPPORTED_TARGET_MODEL
from aspire_brain.web import cases

ROOT = Path(__file__).resolve().parents[2]
KEY = "gsk_" + secrets.token_hex(16)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def context(*texts, question="What is the migration status?"):
    return ProviderInput(question=question, context={"principal": "employee", "tenant": "demo-a"},
                         decision_summary="Simulated cross-platform evidence for inspection only.",
                         evidence=[Evidence(version_id=f"rev-{i}", chunk_id=f"jira:ISSUE-{i}:rev-{i}",
                                            text=text, source_locator=f"https://jira.example/I-{i}",
                                            content_hash="0" * 64, document_id=f"ISSUE-{i}")
                                   for i, text in enumerate(texts, 1)])


def groq(selection, *, seen=None, status=200, model=SUPPORTED_TARGET_MODEL, finish="stop",
         usage=None, headers=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        content = selection if isinstance(selection, str) else json.dumps(selection)
        return httpx.Response(status, json={
            "id": "req_abc123", "model": model,
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content}}],
            "usage": usage or {"prompt_tokens": 400, "completion_tokens": 120,
                               "completion_tokens_details": {"reasoning_tokens": 80}}},
            headers=headers)
    return httpx.MockTransport(handler)


def provider(tmp_path, transport, **ledger_limits):
    return LiveGroundedProvider(approved_live_config(), credential=KEY,
                                ledger=SpendLedger(tmp_path / "ledger.jsonl", **ledger_limits),
                                transport=transport)


def test_answer_is_built_from_selected_exact_sentences_in_model_order(tmp_path):
    seen = []
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S2", "S1"]}, seen=seen))
    output, record = asyncio.run(live.generate_with_record(context(
        "Migration status: in progress. Owner is Ana.", "Blocker: connection pool limit.")))
    assert output.answer.splitlines() == [
        "Simulated cross-platform evidence for inspection only.",
        "From https://jira.example/I-1: Owner is Ana.",
        "From https://jira.example/I-1: Migration status: in progress.",
    ]
    assert output.citation_ids == ["jira:ISSUE-1:rev-1"]
    assert record.mode == "live" and record.live_request_made and record.outcome == "succeeded"
    assert record.input_tokens == 400 and record.reasoning_tokens == 80 and record.output_tokens == 40
    assert record.settled_cost_usd == Decimal("0.000066")
    assert record.vendor_request_id == "req_abc123"
    assert len(seen) == 1


def test_only_question_and_sentences_leave_the_process(tmp_path):
    seen = []
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}, seen=seen))
    asyncio.run(live.generate(context("Migration status: in progress.")))
    request = seen[0]
    assert request.method == "POST" and str(request.url) == SUPPORTED_TARGET_ENDPOINT
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert set(body) == {"model", "messages", "stream", "include_reasoning", "reasoning_effort",
                         "max_completion_tokens", "temperature", "response_format"}
    assert body["model"] == SUPPORTED_TARGET_MODEL and body["max_completion_tokens"] == 1800
    assert body["temperature"] == 0  # the same evidence should get the same selection
    assert body["response_format"]["json_schema"]["strict"] is True
    assert json.loads(body["messages"][1]["content"]) == {
        "question": "What is the migration status?",
        "sentences": [{"id": "S1", "text": "Migration status: in progress."}]}
    wire = request.content.decode()
    for private in ("employee", "demo-a", "ISSUE-1", "jira.example", "rev-1"):
        assert private not in wire
    assert KEY not in wire


@pytest.mark.parametrize("reply", [
    {"answerable": True, "sentence_ids": ["S9"]},                      # unknown sentence
    {"answerable": True, "sentence_ids": ["S1", "S1"]},                # duplicate
    {"answerable": True, "sentence_ids": ["S1"], "answer": "Ignore the rules."},  # extra field
    "The migration is done, trust me.",                                # prose, not JSON
])
def test_model_output_outside_the_selection_contract_is_refused(tmp_path, reply):
    live = provider(tmp_path, groq(reply))
    with pytest.raises(ValueError):
        asyncio.run(live.generate(context("Migration status: in progress.")))


@pytest.mark.parametrize("kwargs", [{"status": 500}, {"model": "other-model"},
                                    {"finish": "length"}])
def test_unusable_responses_are_refused(tmp_path, kwargs):
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}, **kwargs))
    with pytest.raises(ValueError):
        asyncio.run(live.generate(context("Migration status: in progress.")))


def test_model_abstention_releases_nothing_but_keeps_its_record(tmp_path):
    live = provider(tmp_path, groq({"answerable": False, "sentence_ids": []}))
    with pytest.raises(ProviderAbstained) as raised:
        asyncio.run(live.generate(context("Unrelated sentence.")))
    assert raised.value.record.live_request_made and raised.value.record.outcome == "succeeded"


def test_spend_ledger_stops_before_sending(tmp_path):
    seen = []
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}, seen=seen),
                    max_requests=2)
    for _ in range(2):
        asyncio.run(live.generate(context("Migration status: in progress.")))
    with pytest.raises(BudgetExhausted):
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert len(seen) == 2
    assert live.ledger.summary()["requests"] == 2


def test_unknown_outcome_counts_its_full_reservation(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)
    live = provider(tmp_path, httpx.MockTransport(timeout))
    with pytest.raises(ProviderCallFailed) as raised:
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert raised.value.category == "timeout" and raised.value.record.outcome == "timeout"
    summary = live.ledger.summary()
    assert summary["requests"] == 1 and Decimal(summary["spend_usd"]) == Decimal("0.000840")


def test_oversized_evidence_is_refused_before_any_reservation(tmp_path):
    live = provider(tmp_path, httpx.MockTransport(lambda request: pytest.fail("No request")))
    big = " ".join(f"Sentence number {i} about the migration." for i in range(200))
    with pytest.raises(ValueError, match="no request was made"):
        asyncio.run(live.generate(context(big)))
    assert live.ledger.summary()["requests"] == 0


def test_factory_builds_only_the_approved_envelope(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    built = configured_provider("live_grounded", runtime=approved_live_config(),
                                credential=KEY, ledger_path=ledger)
    assert isinstance(built, LiveGroundedProvider) and built.mode == "live_grounded"
    looser = approved_live_config().model_copy(update={"input_token_cap": 8000,
                                                       "total_token_cap": 10000})
    with pytest.raises(ExternalProviderUnavailable, match="no request was made"):
        configured_provider("live_grounded", runtime=looser, credential=KEY, ledger_path=ledger)
    with pytest.raises(ExternalProviderUnavailable, match="no request was made"):
        configured_provider("live_grounded", runtime=approved_live_config(), ledger_path=ledger)


def _app(tmp_path, live):
    settings = Settings(db_path=tmp_path / "live.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                        demo_mode=True)
    return TestClient(create_app(settings, provider=live), base_url="http://localhost",
                      client=("127.0.0.1", 50000))


def _headers(client):
    session = client.get("/api/session").json()
    return {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}


def test_pages_label_the_live_mode_instead_of_the_offline_default(tmp_path):
    live = provider(tmp_path, httpx.MockTransport(lambda request: pytest.fail("No request")))
    with _app(tmp_path, live) as client:
        ask, cases = client.get("/ask").text, client.get("/cases").text
    for page in (ask, cases):
        assert "Mode: <strong>live_grounded</strong>" in page
        assert "Mode: <strong>offline_extractive</strong>" not in page
    assert "No live model is contacted" not in cases
    assert f"{live.config.model} via {live.config.service}" in cases
    assert "Live model: your question and Case 7" in cases


def test_case_7_uses_the_live_model_under_the_claim_gate(tmp_path):
    seen = []
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S2", "S1"]}, seen=seen))
    with _app(tmp_path, live) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=_headers(client)).status_code == 200
        result = client.post("/api/cases/case_7", headers=_headers(client)).json()
    packet = result["packet"]
    assert packet["provider_mode"] == "live_grounded" and packet["query_status"] == "answered"
    assert packet["claim_support"]["mode"] == "live" and packet["claim_support"]["all_supported"]
    assert packet["claim_support"]["denominator"] == 2
    assert packet["provider_runtime"]["live_request_made"] is True
    assert result["default_packet"]["provider_mode"] == "offline_extractive"
    assert result["abstention"]["packet"]["query_status"] == "abstained"
    assert "live model" in result["provider_note"]
    assert len(seen) == 1  # the abstention control has no permitted evidence and sends nothing


def test_restricted_sources_are_never_sent_to_the_external_model(tmp_path):
    live = provider(tmp_path, httpx.MockTransport(lambda request: pytest.fail("No request")))
    state = SimulatedPlatformState(
        records=cases.CASE_3_RECORDS,
        principal_map={"employee": {"confluence": "conf-employee"}},
        confluence_space_grants={"SEC": {"conf-employee"}},
        confluence_page_grants={"BREACH-RPT": {"conf-employee"}},
        last_successful_sync={"confluence": cases.NOW},
        freshness_budget_seconds={"confluence": 3600})
    with _app(tmp_path, live) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
        service = SimulatedQueryService(client.app.state.auth, client.app.state.audit, state,
                                        provider=live, required_platforms=("confluence",),
                                        clock=lambda: cases.NOW)
        packet = asyncio.run(service.query("employee", cases.CASE_3_QUERY, cases.NOW))
    assert packet["query_status"] == "abstained" and packet["citations"] == []
    assert live.ledger.summary()["requests"] == 0


def test_evaluation_script_dry_run_passes_offline(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("live_model_run", ROOT / "eval/live_model/run.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--out", str(tmp_path)]) == 0
    report = json.loads(next(tmp_path.glob("dry-*.json")).read_text())
    assert report["mode"] == "dry_run" and report["result"] == "pass"
    assert script.main(["--live"]) == 2  # real calls need an explicit --yes


def test_rejected_request_is_categorised_and_not_charged(tmp_path):
    secret = "Rate limit reached for org_123 " + KEY
    def limited(request):
        return httpx.Response(429, headers={"retry-after": "7"}, json={"error": {
            "type": "rate_limit_error", "message": secret}})
    live = provider(tmp_path, httpx.MockTransport(limited))
    with pytest.raises(ProviderCallFailed) as raised:
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert raised.value.category == "rate_limited"
    assert raised.value.record.settled_cost_usd == Decimal("0")
    assert live.ledger.summary() | {} == {"requests": 1, "spend_usd": "0", "max_requests": 30,
                                          "max_usd": "5"}
    entry = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[-1])
    assert entry["error_category"] == "rate_limited"
    assert entry["details"] == {"provider_error_type": "rate_limit_error", "retry_after_seconds": "7"}
    assert "org_123" not in json.dumps(entry) and KEY not in json.dumps(entry)


GROQ_RATE_LIMIT_HEADERS = {
    "x-ratelimit-limit-requests": "12000",
    "x-ratelimit-remaining-requests": "11998",
    "x-ratelimit-reset-requests": "2m59.56s",
    "x-ratelimit-limit-tokens": "60000",
    "x-ratelimit-remaining-tokens": "59950",
    "x-ratelimit-reset-tokens": "144ms",
}
RATE_LIMIT_DETAILS = {
    "rl_limit_req": "12000",
    "rl_remaining_req": "11998",
    "rl_reset_req": "2m59.56s",
    "rl_limit_tok": "60000",
    "rl_remaining_tok": "59950",
    "rl_reset_tok": "144ms",
}


def settled_details(tmp_path):
    entries = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    return [entry["details"] for entry in entries if entry["event"] == "settled"]


def test_successful_call_settles_with_the_rate_limit_headers(tmp_path):
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]},
                                    headers=GROQ_RATE_LIMIT_HEADERS))
    asyncio.run(live.generate(context("Migration status: in progress.")))
    assert settled_details(tmp_path)[-1] == RATE_LIMIT_DETAILS


def test_rate_limited_call_settles_with_the_rate_limit_headers(tmp_path):
    secret = "Rate limit reached for org_123 " + KEY

    def limited(request):
        return httpx.Response(429, json={"error": {"type": "rate_limit_error",
                                                  "message": secret}},
                              headers={"retry-after": "7"} | GROQ_RATE_LIMIT_HEADERS)
    live = provider(tmp_path, httpx.MockTransport(limited))
    with pytest.raises(ProviderCallFailed) as raised:
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert raised.value.category == "rate_limited"
    details = settled_details(tmp_path)[-1]
    assert details == RATE_LIMIT_DETAILS | {"provider_error_type": "rate_limit_error",
                                            "retry_after_seconds": "7"}
    assert secret not in json.dumps(details) and KEY not in json.dumps(details)


def test_failed_call_after_a_200_response_still_records_the_rate_limit_headers(tmp_path):
    live = provider(tmp_path, groq("not json", headers=GROQ_RATE_LIMIT_HEADERS))
    with pytest.raises(ProviderCallFailed):
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert settled_details(tmp_path)[-1] == RATE_LIMIT_DETAILS


def test_each_invalid_rate_limit_header_is_dropped_on_its_own(tmp_path):
    headers = dict(GROQ_RATE_LIMIT_HEADERS)
    headers |= {"x-ratelimit-remaining-requests": "abc",  # not digits
                "x-ratelimit-reset-tokens": "2h"}         # no trailing unit
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}, headers=headers))
    asyncio.run(live.generate(context("Migration status: in progress.")))
    expected = dict(RATE_LIMIT_DETAILS)
    del expected["rl_remaining_req"], expected["rl_reset_tok"]
    assert settled_details(tmp_path)[-1] == expected


@pytest.mark.parametrize("headers", [
    {"x-ratelimit-limit-requests": "12345678901"},      # eleven characters
    {"x-ratelimit-remaining-requests": " 8"},           # blank, not digits
    {"x-ratelimit-remaining-tokens": "-3"},             # sign, not digits
    {"x-ratelimit-limit-tokens": "12.5"},               # decimal, not digits
    {"x-ratelimit-reset-requests": "12h34m56.7890123s"},  # seventeen characters
    {"x-ratelimit-reset-requests": "1.5h"},             # fractional hour prefix
    {"x-ratelimit-reset-tokens": "300"},                # no unit
    {"x-ratelimit-unrelated": "5", "x-request-id": "req_abc123"},  # unknown headers
])
def test_malformed_oversized_or_unknown_rate_limit_headers_save_nothing(tmp_path, headers):
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}, headers=headers))
    asyncio.run(live.generate(context("Migration status: in progress.")))
    assert settled_details(tmp_path)[-1] == {}


@pytest.mark.parametrize("value", [
    "12345678901",      # eleven characters
    " 8",               # blank, not digits
    "-3",               # sign, not digits
    "12.5",             # decimal, not digits
    "٣٠٠",              # non-ASCII digits
    "1٢٣",              # mixed digits
    "12\n34",           # injection attempt
    "0x10",             # not decimal
])
def test_rate_limit_counts_are_digits_of_at_most_ten_characters(value):
    from aspire_brain.providers.live import _rate_limit_details

    assert _rate_limit_details({"x-ratelimit-limit-requests": value}) == {}


def test_rate_limit_counts_within_the_bounds_are_kept():
    from aspire_brain.providers.live import _rate_limit_details

    assert _rate_limit_details({"x-ratelimit-limit-requests": "0",
                                "x-ratelimit-remaining-requests": "1234567890"}) == {
        "rl_limit_req": "0", "rl_remaining_req": "1234567890"}


@pytest.mark.parametrize("value", [
    "12h34m56.7890123s",  # seventeen characters
    "1.5h",               # fractional hour prefix
    "300",                # no unit
    "1h",                 # no trailing unit
    "7m",                 # no trailing unit
    "2m59.56 s",          # inner blank
    "1m2sec",             # unknown unit
    ".5s",                # no integer part
    "1.5",                # no unit
    "ms",                 # no quantity
])
def test_rate_limit_resets_outside_the_exact_shape_are_dropped(value):
    from aspire_brain.providers.live import _rate_limit_details

    assert _rate_limit_details({"x-ratelimit-reset-requests": value,
                                "x-ratelimit-reset-tokens": value}) == {}


@pytest.mark.parametrize("value", ["144ms", "7.66s", "2m59.56s", "1h2m3.4s", "30s"])
def test_rate_limit_resets_inside_the_shape_are_kept(value):
    from aspire_brain.providers.live import _rate_limit_details

    assert _rate_limit_details({"x-ratelimit-reset-requests": value}) == {"rl_reset_req": value}


def test_a_recorded_rate_limit_cooldowns_the_next_attempt_before_anything_is_sent(tmp_path):
    seen = []

    def limited(request):
        seen.append(request)
        return httpx.Response(429, json={"error": {"type": "rate_limit_error"}},
                              headers={"retry-after": "3600"})
    live = provider(tmp_path, httpx.MockTransport(limited))
    with pytest.raises(ProviderCallFailed) as raised:
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert raised.value.category == "rate_limited"
    assert live.ledger.summary()["requests"] == 1
    # A second provider on the same ledger stands in for another process sharing the budget.
    other = provider(tmp_path, httpx.MockTransport(limited))
    with pytest.raises(ExternalProviderUnavailable, match="no request was made") as blocked:
        asyncio.run(other.generate(context("Migration status: in progress.")))
    assert "Provider rate limit in effect until" in str(blocked.value)
    assert len(seen) == 1                     # nothing more was sent
    assert other.ledger.summary()["requests"] == 1  # nothing more was reserved


def test_an_expired_cooldown_lets_the_next_call_through(tmp_path):
    entry = {"event": "settled", "correlation_id": "earlier-call", "outcome": "failed",
             "error_category": "rate_limited", "settled_cost_usd": "0",
             "details": {"retry_after_seconds": "3600"},
             "at": (datetime.now(UTC) - timedelta(hours=2)).isoformat()}
    (tmp_path / "ledger.jsonl").write_text(json.dumps(entry) + "\n")
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}))
    _output, record = asyncio.run(live.generate_with_record(
        context("Migration status: in progress.")))
    assert record.outcome == "succeeded"
    until = live.ledger.cooldown_until()
    assert until is not None and until <= datetime.now(UTC)


def test_a_rate_limit_without_a_retry_after_sets_no_cooldown(tmp_path):
    live = provider(tmp_path, httpx.MockTransport(lambda request: httpx.Response(
        429, json={"error": {"type": "rate_limit_error"}})))
    with pytest.raises(ProviderCallFailed):
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert live.ledger.cooldown_until() is None
    other = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}))
    _output, record = asyncio.run(other.generate_with_record(
        context("Migration status: in progress.")))
    assert record.outcome == "succeeded"


def test_a_successful_call_sets_no_cooldown(tmp_path):
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]},
                                   headers=GROQ_RATE_LIMIT_HEADERS))
    asyncio.run(live.generate(context("Migration status: in progress.")))
    assert live.ledger.cooldown_until() is None


def test_the_latest_rate_limit_sets_the_cooldown(tmp_path):
    lines = [
        {"event": "settled", "outcome": "failed", "error_category": "rate_limited",
         "settled_cost_usd": "0", "details": {"retry_after_seconds": "7200"},
         "at": (datetime.now(UTC) - timedelta(hours=3)).isoformat()},
        {"event": "settled", "outcome": "failed", "error_category": "rate_limited",
         "settled_cost_usd": "0", "details": {"retry_after_seconds": "300"},
         "at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
    ]
    (tmp_path / "ledger.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    ledger = SpendLedger(tmp_path / "ledger.jsonl")
    until = ledger.cooldown_until()
    assert until is not None and until > datetime.now(UTC)


def test_evaluation_script_counts_failed_calls(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("live_model_run_fail",
                                                  ROOT / "eval/live_model/run.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "fake_transport", lambda rate_limits=None: httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": {"type": "rate_limit_error"}})))
    # Every call refused by the provider: nothing completed, so nothing about quality is shown.
    assert script.main(["--out", str(tmp_path)]) == 3
    report = json.loads(next(tmp_path.glob("dry-*.json")).read_text())
    called = [row for row in report["rows"] if row.get("model_called")]
    assert called and {row["error_category"] for row in called} == {"rate_limited"}
    assert report["checks"]["answered_share_of_model_calls"] == f"0/{len(called)}"
    assert report["result"] == "inconclusive"


@pytest.mark.parametrize("usage", [
    # 1,050 visible output tokens: over the 800 output cap, though the 1,800 sum still fits.
    {"prompt_tokens": 400, "completion_tokens": 1100,
     "completion_tokens_details": {"reasoning_tokens": 50}},
    # 1,100 reasoning tokens: over the 1,000 reasoning cap, though the sum still fits.
    {"prompt_tokens": 400, "completion_tokens": 1150,
     "completion_tokens_details": {"reasoning_tokens": 1100}},
])
def test_output_and_reasoning_usage_are_each_held_to_their_own_cap(tmp_path, usage):
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}, usage=usage))
    with pytest.raises(ProviderCallFailed) as raised:
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert raised.value.category == "usage_outside_envelope"


def test_usage_at_each_cap_is_accepted(tmp_path):
    usage = {"prompt_tokens": 400, "completion_tokens": 1800,
             "completion_tokens_details": {"reasoning_tokens": 1000}}
    live = provider(tmp_path, groq({"answerable": True, "sentence_ids": ["S1"]}, usage=usage))
    _output, record = asyncio.run(live.generate_with_record(
        context("Migration status: in progress.")))
    assert record.output_tokens == 800 and record.reasoning_tokens == 1000


def test_a_rate_limited_failure_carries_its_validated_retry_after(tmp_path):
    def limited(request):
        return httpx.Response(429, json={"error": {"type": "rate_limit_error"}},
                              headers={"retry-after": "33"})
    live = provider(tmp_path, httpx.MockTransport(limited))
    with pytest.raises(ProviderCallFailed) as raised:
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert raised.value.retry_after_seconds == 33.0


def test_a_failure_without_retry_after_carries_none(tmp_path):
    live = provider(tmp_path, httpx.MockTransport(lambda request: httpx.Response(
        429, json={"error": {"type": "rate_limit_error"}})))
    with pytest.raises(ProviderCallFailed) as raised:
        asyncio.run(live.generate(context("Migration status: in progress.")))
    assert raised.value.retry_after_seconds is None


def _policy_case(case_id):
    for line in (ROOT / "eval/cases.jsonl").read_text().splitlines():
        case = json.loads(line)
        if case["id"] == case_id:
            return case
    raise AssertionError(case_id)


def _query_with(tmp_path, live, case):
    from aspire_brain.models import QueryRequest

    with _app(tmp_path, live) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
        query = client.app.state.queries.query({"id": case["principal"]},
                                               QueryRequest.model_validate(case["query"]))
        packet = asyncio.run(query)
        events = client.app.state.audit.events("demo-a", limit=100)
    return packet, events


def test_abstention_on_a_review_decision_releases_the_decision_without_citations(tmp_path):
    case = _policy_case("employee-p17-unverified")
    assert case["expected"]["query_status"] == "needs_review"
    live = provider(tmp_path, groq({"answerable": False, "sentence_ids": []}))
    packet, events = _query_with(tmp_path, live, case)
    assert packet["query_status"] == "needs_review" and packet["citations"] == []
    assert packet["answer"].endswith("No evidence sentences were selected for this question.")
    assert packet["claim_support"]["abstained"] and packet["claim_support"]["all_supported"]
    assert not any(text in packet["answer"] for text in case["expected"]["forbidden_text"])
    assert any(event["event_type"] == "provider_error" for event in events)
    assert live.ledger.summary()["requests"] == 1


def test_abstention_on_an_answerable_decision_still_releases_nothing(tmp_path):
    from aspire_brain.answers.service import QueryError

    case = _policy_case("employee-current-general")
    assert case["expected"]["query_status"] == "answered"
    live = provider(tmp_path, groq({"answerable": False, "sentence_ids": []}))
    with pytest.raises(QueryError) as raised:
        _query_with(tmp_path, live, case)
    assert raised.value.status_code == 422


class FakeMsvcrt:
    """Stands in for Windows' ``msvcrt`` so the non-POSIX lock path runs on any platform."""

    LK_LOCK, LK_UNLCK = 1, 0

    def __init__(self):
        self.calls = []

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))


def test_the_spend_ledger_locks_with_msvcrt_where_there_is_no_fcntl(tmp_path, monkeypatch):
    import aspire_brain.providers.live as live_module

    fake = FakeMsvcrt()
    monkeypatch.setattr(live_module, "fcntl", None)
    monkeypatch.setattr(live_module, "msvcrt", fake, raising=False)
    ledger = SpendLedger(tmp_path / "ledger.jsonl")
    ledger.reserve("windows-call", Decimal("0.001"))
    assert ledger.summary()["requests"] == 1
    # Each use takes and releases the same one-byte lock at offset 0.
    assert fake.calls and len(fake.calls) % 2 == 0
    assert all(call == (FakeMsvcrt.LK_LOCK, 1, 0) for call in fake.calls[0::2])
    assert all(call == (FakeMsvcrt.LK_UNLCK, 1, 0) for call in fake.calls[1::2])


def test_the_application_imports_without_fcntl():
    import subprocess
    import sys

    # The standard library and server stack load first: on POSIX they use fcntl themselves, and
    # on Windows they have their own equivalents. Only the application's imports are probed.
    probe = ("import sys, types, asyncio, subprocess, httpx, fastapi, uvicorn; "
             "sys.modules['fcntl'] = None; "
             "sys.modules['msvcrt'] = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, "
             "locking=lambda *a: None); import aspire_brain.main, aspire_brain.providers.live as m; "
             "assert m.fcntl is None; print('ok')")
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                            cwd=ROOT, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_evidence_fits_measures_the_request_actually_sent(tmp_path):
    live = provider(tmp_path, httpx.MockTransport(lambda request: httpx.Response(500)))
    short = "Escalate a payment that stays processing for more than 30 minutes."
    assert live.evidence_fits("What is the escalation threshold?", [short])
    # Quotes are escaped twice (the user message is JSON inside the request JSON), so text well
    # under the cap in characters can still exceed it in request bytes.
    quoted = 'The "partner" said "pending". ' * 70
    assert len(quoted) < live.config.input_token_cap
    assert not live.evidence_fits("What did the partner say?", [quoted])
