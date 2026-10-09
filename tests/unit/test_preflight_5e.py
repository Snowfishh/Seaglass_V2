"""One-attempt 5E contract; every SDK request in this module uses a fake transport."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from aspire_brain.providers.preflight import (
    GuardedTransport,
    create_client,
    load_candidate,
    run_preflight,
)

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "docs/reviews/stage5e-preflight-2026-10-10/5e-corrected-candidate.json"
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
BODY_SHA = "cfacdf3f9bf655f4180b9625221a9d42bd12e609edc36fe2bfed4e3a71c15f49"
ANSWER = "Fictional Singapore contractor travel cap: SGD 250 per claim."
CITATION = "synthetic:5e-control:v1"
FAKE_KEY = "test-only-credential-must-never-appear-in-report"


@pytest.fixture
def candidate():
    return load_candidate(CANDIDATE)


def completion(*, answer=ANSWER, citations=None, finish="stop", model="openai/gpt-oss-20b"):
    return {
        "id": "offline-5e-test", "object": "chat.completion", "created": 1, "model": model,
        "choices": [{"index": 0, "finish_reason": finish, "message": {
            "role": "assistant", "content": json.dumps({
                "answer": answer, "citation_ids": [CITATION] if citations is None else citations,
            })}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140,
                  "completion_tokens_details": {"reasoning_tokens": 0}},
    }


def test_candidate_fixes_prices_budget_and_exact_body(candidate):
    assert candidate.config.max_cost_usd == Decimal("0.01")
    assert candidate.rates.input_usd_per_million == Decimal("0.075")
    assert candidate.rates.output_usd_per_million == Decimal("0.30")
    assert candidate.rates.reasoning_usd_per_million == Decimal("0.30")
    assert candidate.config.request_cap == 1
    assert candidate.config.timeout_seconds == 10
    assert len(candidate.body_json.encode()) == 1181
    assert hashlib.sha256(candidate.body_json.encode()).hexdigest() == BODY_SHA
    assert candidate.fingerprint_sha256 == BODY_SHA
    assert json.loads(candidate.body_json)["max_completion_tokens"] == 256


def test_original_candidate_cannot_be_redispatched_after_correction():
    original = CANDIDATE.with_name("5e-preflight-candidate.json")
    assert hashlib.sha256(original.read_bytes()).hexdigest() == (
        "d1879a8f22469d81dc1189f86230744dbe956d81183096d0bfc475858dc2cdd1")
    with pytest.raises(ValueError, match="Unreviewed request bytes"):
        load_candidate(original)


def test_prompt_requires_verbatim_quotes_and_bounded_abstention(candidate):
    system = json.loads(candidate.body_json)["messages"][0]["content"]
    assert "Quote the evidence verbatim, character for character" in system
    assert "without paraphrasing, summarising, reordering, correcting or translating" in system
    assert "Cite only the chunk ids that appear in the user message." in system
    assert "I cannot answer from the available evidence." in system


def test_sdk_is_pinned_and_disables_retries(candidate, tmp_path):
    import groq

    assert groq.__version__ == "1.7.0"
    with create_client(api_key=FAKE_KEY, transport=GuardedTransport(
            candidate, tmp_path / "attempt.json", httpx.MockTransport(
                lambda request: httpx.Response(200, json=completion())))) as client:
        assert client.max_retries == 0
        assert client.timeout.read == 10
        assert str(client.base_url) == "https://api.groq.com/openai/v1/"
        assert client._client.follow_redirects is False
        assert client._client._trust_env is False


@pytest.mark.parametrize("method,url,transform", [
    ("GET", ENDPOINT, lambda raw: raw),
    ("POST", ENDPOINT.replace("api.groq.com", "attacker.invalid"), lambda raw: raw),
    ("POST", ENDPOINT + "?unreviewed=true", lambda raw: raw),
    ("POST", ENDPOINT.replace("https:", "http:"), lambda raw: raw),
    ("POST", ENDPOINT + "/", lambda raw: raw),
    ("POST", ENDPOINT, lambda raw: raw + b" "),
    ("POST", ENDPOINT, lambda raw: raw.replace(b"gpt-oss-20b", b"gpt-oss-120b")),
    ("POST", ENDPOINT, lambda raw: json.dumps(json.loads(raw), indent=2).encode()),
])
def test_guard_rejects_unreviewed_wire_requests(candidate, tmp_path, method, url, transform):
    seen = []
    guard = GuardedTransport(candidate, tmp_path / "attempt.json", httpx.MockTransport(
        lambda request: seen.append(request) or httpx.Response(200, json={})))
    with pytest.raises(ValueError):
        guard.handle_request(httpx.Request(method, url, content=transform(candidate.body_json.encode())))
    assert seen == []


def test_guard_consumes_persistent_attempt_before_network(candidate, tmp_path):
    ledger = tmp_path / "attempt.json"
    seen = []

    def inner(request):
        assert ledger.exists()
        seen.append(request.content)
        return httpx.Response(200, json=completion())

    for attempt in range(2):
        guard = GuardedTransport(candidate, ledger, httpx.MockTransport(inner))
        request = httpx.Request("POST", ENDPOINT, content=candidate.body_json.encode())
        if attempt == 0:
            assert guard.handle_request(request).status_code == 200
        else:
            with pytest.raises(ValueError):
                guard.handle_request(request)
    assert seen == [candidate.body_json.encode()]


@pytest.mark.parametrize("failure", [429, 500, "timeout"])
def test_sdk_failure_is_terminal_sanitized_and_never_retried(candidate, tmp_path, failure):
    seen = []

    def inner(request):
        seen.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(FAKE_KEY, request=request)
        return httpx.Response(failure, json={"error": {"message": FAKE_KEY}})

    ledger = tmp_path / "attempt.json"
    result = run_preflight(candidate, api_key=FAKE_KEY, ledger_path=ledger,
                           inner=httpx.MockTransport(inner))
    assert len(seen) == 1
    assert result["attempt"] == 1
    assert result["postflight_validated"] is False
    assert result["settled_cost_usd"] is None
    assert Decimal(str(result["uncertain_cost_usd"])) > 0
    assert result["mode"] == "offline_mock"
    assert result["live_request_made"] is False
    assert FAKE_KEY not in json.dumps(result)
    restarted = run_preflight(candidate, api_key=FAKE_KEY, ledger_path=ledger,
                              inner=httpx.MockTransport(inner))
    assert len(seen) == 1
    assert restarted["postflight_validated"] is False


@pytest.mark.parametrize("body", [None, [], {"error": []},
                                  {"error": {"type": [], "param": {}, "message": []}}])
def test_malformed_http_errors_still_produce_minimized_terminal_reports(candidate, tmp_path, body):
    result = run_preflight(candidate, api_key=FAKE_KEY, ledger_path=tmp_path / "attempt.json",
                           inner=httpx.MockTransport(
                               lambda request: httpx.Response(400, content=json.dumps(body))))
    assert result["error_category"] == "http_error"
    assert result["http_status"] == 400
    assert result["attempt"] == 1 and result["slot_consumed"] is True
    assert result["postflight_validated"] is False
    assert FAKE_KEY not in json.dumps(result)


@pytest.mark.parametrize("changes", [
    {"answer": "The travel cap is SGD 250."},
    {"answer": ANSWER.replace("250", "2500")},
    {"answer": ANSWER.replace("SGD", "USD")},
    {"answer": ANSWER.replace("per claim", "per year")},
    {"answer": "I cannot answer from the available evidence."},
    {"citations": ["unauthorized:source"]},
    {"citations": []},
    {"finish": "length"},
    {"model": "openai/gpt-oss-120b"},
])
def test_http_200_does_not_imply_verified_content(candidate, tmp_path, changes):
    report = run_preflight(candidate, api_key=FAKE_KEY, ledger_path=tmp_path / "attempt.json",
                           inner=httpx.MockTransport(
                               lambda request: httpx.Response(200, json=completion(**changes))))
    assert report["postflight_validated"] is False
    assert report["mode"] == "offline_mock"
    assert report["live_request_made"] is False


def test_validated_mock_remains_mock_and_settles_from_usage(candidate, tmp_path):
    seen = []

    def inner(request):
        seen.append(request)
        return httpx.Response(200, json=completion())

    report = run_preflight(candidate, api_key=FAKE_KEY, ledger_path=tmp_path / "attempt.json",
                           inner=httpx.MockTransport(inner))
    assert report["postflight_validated"] is True
    assert report["mode"] == "offline_mock"
    assert report["live_request_made"] is False
    assert report["attempt"] == 1
    assert Decimal(str(report["settled_cost_usd"])) == Decimal("0.0000195")
    assert Decimal(str(report["uncertain_cost_usd"])) == 0
    assert len(seen) == 1
    assert seen[0].content == candidate.body_json.encode()
    assert FAKE_KEY not in json.dumps(report)
