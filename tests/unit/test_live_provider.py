"""Live grounded provider, exercised offline against a fake OpenAI-compatible endpoint."""

import asyncio
import json
import secrets
import socket
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
         usage=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        content = selection if isinstance(selection, str) else json.dumps(selection)
        return httpx.Response(status, json={
            "id": "req_abc123", "model": model,
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content}}],
            "usage": usage or {"prompt_tokens": 400, "completion_tokens": 120,
                               "completion_tokens_details": {"reasoning_tokens": 80}}})
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
                         "max_completion_tokens", "response_format"}
    assert body["model"] == SUPPORTED_TARGET_MODEL and body["max_completion_tokens"] == 1800
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


def test_evaluation_script_counts_failed_calls(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("live_model_run_fail",
                                                  ROOT / "eval/live_model/run.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "fake_transport", lambda: httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": {"type": "rate_limit_error"}})))
    assert script.main(["--out", str(tmp_path)]) == 1
    report = json.loads(next(tmp_path.glob("dry-*.json")).read_text())
    called = [row for row in report["rows"] if row.get("model_called")]
    assert called and {row["error_category"] for row in called} == {"rate_limited"}
    assert report["checks"]["answered_share_of_model_calls"] == f"0/{len(called)}"
    assert report["result"] == "fail"
