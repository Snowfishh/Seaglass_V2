"""5E traverses the real local query service with only synthetic fixtures and fake HTTP."""
import asyncio
import json
import secrets
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from aspire_brain.answers import QueryService
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.knowledge import Retriever
from aspire_brain.providers.preflight import load_candidate
from aspire_brain.providers.preflight_service import (
    READER,
    ServiceSmokeProvider,
    run_service_preflight,
)

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "docs/reviews/stage5e-preflight-2026-10-10/5e-corrected-candidate.json"
TEXT = "Fictional Singapore contractor travel cap: SGD 250 per claim."
CHUNK = "synthetic:5e-control:v1"


def response(answer=TEXT, code=200):
    return httpx.Response(code, json={
        "id": "offline-service-test", "object": "chat.completion", "created": 1,
        "model": "openai/gpt-oss-20b", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps({
                "answer": answer, "citation_ids": [CHUNK]})}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140,
                  "completion_tokens_details": {"reasoning_tokens": 0}},
    })


def run(tmp_path, handler):
    return run_service_preflight(load_candidate(CANDIDATE), api_key=secrets.token_urlsafe(24),
                                 state_dir=tmp_path, inner=httpx.MockTransport(handler))


def usage_response(prompt, completion, reasoning):
    body = json.loads(response().content)
    return httpx.Response(200, json=body | {"usage": {
        "prompt_tokens": prompt, "completion_tokens": completion,
        "completion_tokens_details": {"reasoning_tokens": reasoning},
    }})


@pytest.mark.parametrize("prompt,completion,reasoning", [
    pytest.param(3073, None, None, id="input-over"),
    pytest.param(None, 257, None, id="completion-over"),
    pytest.param(None, None, 129, id="reasoning-over"),
    pytest.param(None, 40, 41, id="negative-output"),
    pytest.param(None, 129, 0, id="output-over"),
    pytest.param(True, None, None, id="boolean-counter"),
    pytest.param(None, "40", None, id="string-counter"),
    pytest.param(None, None, -1, id="negative-counter"),
])
def test_invalid_usage_rejected_by_service_without_packet_or_retry(
        tmp_path, prompt, completion, reasoning):
    seen = []
    result = run(tmp_path, lambda request: seen.append(request) or
                 usage_response(prompt, completion, reasoning))
    assert len(seen) == 1
    assert result["service_status_code"] == 502
    assert result["postflight_validated"] is False
    assert result["packet"] is None and result["packet_count"] == 0
    assert result["packet_readable"] is False and result["output"] is None
    assert result["mode"] == "offline_mock" and result["live_request_made"] is False
    assert result["audit_chain_valid"] is True
    assert {"provider_error", "query_aborted"} <= set(result["audit_event_types"])
    attempt = next(event for event in result["audit_rows"]
                   if event["event_type"] == "provider_attempt_result")
    for details in (result["runtime"], attempt["metadata"]):
        assert details["settled_cost_usd"] is None
        assert Decimal(details["uncertain_cost_usd"]) == Decimal("0.0003072")
        assert details["attempt"] == 1 and details["network_attempted"] is True
    assert attempt["metadata"]["outcome"] == "rejected"
    assert all(result[field] == 0 for field in ("sdk_retries", "application_retries", "fallbacks"))
    ledger = (tmp_path / "attempt.json").read_bytes()
    assert Decimal(json.loads(ledger)["uncertain_cost_usd"]) == Decimal("0.0003072")
    db = Database(result["database_path"])
    auth = AuthService(db)
    service = QueryService(db, auth, AuditWriter(db.path, (tmp_path / "audit.key").read_bytes()))
    with pytest.raises(AccessDenied):
        service.packet(auth.principal(READER), result["request_id"])
    restarted = run(tmp_path, lambda request: seen.append(request) or response())
    assert len(seen) == 1 and (tmp_path / "attempt.json").read_bytes() == ledger
    assert restarted["service_status_code"] == 502 and restarted["packet_count"] == 0
    assert restarted["slot_consumed"] is True and restarted["network_attempted"] is False


@pytest.mark.parametrize("prompt,completion,reasoning", [
    (None, None, None), (3072, None, None), (None, 256, 128),
    (None, None, 128), (100, 40, None), (100, None, 0),
])
def test_valid_partial_usage_retains_uncertain_cost(tmp_path, prompt, completion, reasoning):
    result = run(tmp_path, lambda request: usage_response(prompt, completion, reasoning))
    assert result["service_status_code"] == 200 and result["packet_count"] == 1
    assert result["postflight_validated"] is True and result["packet_readable"] is True
    assert result["settled_cost_usd"] is None
    assert Decimal(result["uncertain_cost_usd"]) == Decimal("0.0003072")
    assert result["cost_provenance"] == "reservation_not_vendor_bill"
    assert result["input_tokens"] == prompt
    assert result["completion_tokens"] == completion
    assert result["reasoning_tokens"] == reasoning


def test_service_success_persists_and_reads_packet_with_audit(tmp_path):
    requests = []
    result = run(tmp_path, lambda request: requests.append(request) or response())
    assert len(requests) == 1
    assert result["postflight_validated"] is True
    assert result["service_status_code"] == 200
    assert result["packet_count"] == 1 and result["packet_readable"] is True
    assert result["packet"]["answer"] == TEXT
    assert result["packet"]["citations"][0]["chunk_id"] == CHUNK
    assert result["packet"]["claim_support"]["all_supported"] is True
    assert result["mode"] == "offline_mock" and result["live_request_made"] is False
    assert {"query_attempt", "policy_decision", "provider_send_intent", "query_completed"} <= set(
        result["audit_event_types"])
    assert result["audit_chain_valid"] is True
    assert result["request_id"] == result["packet"]["request_id"]
    events = result["audit_rows"]
    intents = [event for event in events if event["event_type"] == "provider_send_intent"]
    assert [event["metadata"]["operation"] for event in intents] == ["pre_claim", "post_claim"]
    assert all("response_digest" not in event["metadata"] for event in intents)
    attempt = next(event for event in events if event["event_type"] == "provider_attempt_result")
    assert attempt["metadata"]["manifest_sha256"] == result["manifest_sha256"]
    assert attempt["metadata"]["raw_response_sha256"] == result["raw_response_sha256"]
    assert attempt["metadata"]["attempt"] == 1
    assert attempt["metadata"]["live_request_made"] is False
    assert attempt["metadata"]["settled_cost_usd"] == result["settled_cost_usd"]
    ledger = json.loads((tmp_path / "attempt.json").read_text())
    assert ledger["request_id"] == result["request_id"]


@pytest.mark.parametrize("answer,code", [(TEXT, 429), ("SGD 2500 per claim.", 200)])
def test_service_rejects_provider_failure_without_packet(tmp_path, answer, code):
    seen = []
    result = run(tmp_path, lambda request: seen.append(request) or response(answer, code))
    assert len(seen) == 1
    assert result["service_status_code"] == 502
    assert result["postflight_validated"] is False
    assert result["packet_count"] == 0 and result["packet_readable"] is False
    assert "provider_error" in result["audit_event_types"]
    assert "query_aborted" in result["audit_event_types"]
    assert result["runtime"]["attempt"] == 1
    attempt = next(event for event in result["audit_rows"]
                   if event["event_type"] == "provider_attempt_result")
    assert attempt["metadata"]["error_category"] == (
        "http_error" if code == 429 else "invalid_timeout_or_guard")


def test_http_400_records_only_allowlisted_error_details(tmp_path):
    secret = secrets.token_urlsafe(24)
    message = ("invalid JSON schema for response_format: /properties/citation_ids: "
               f"uniqueItems is not supported [unsupported_uniqueItems] {secret}")
    result = run(tmp_path, lambda request: httpx.Response(400, json={"error": {
        "message": message, "type": "invalid_request_error", "param": "response_format",
        "code": secret}}))
    attempt = next(event for event in result["audit_rows"]
                   if event["event_type"] == "provider_attempt_result")
    for details in (result["runtime"], attempt["metadata"]):
        assert details["provider_error_type"] == "invalid_request_error"
        assert details["provider_error_param"] == "response_format"
        assert details["provider_error_reason"] == "unsupported_uniqueItems"
        assert secret not in json.dumps(details)
    assert result["service_status_code"] == 502
    assert result["packet_count"] == 0


def test_empty_retrieval_never_calls_sdk(tmp_path, monkeypatch):
    monkeypatch.setattr(Retriever, "search", lambda *args, **kwargs: [])
    seen = []
    result = run(tmp_path, lambda request: seen.append(request) or response())
    assert seen == [] and not (tmp_path / "attempt.json").exists()
    assert result["postflight_validated"] is False
    assert result["runtime"]["attempt"] == 0
    assert result["packet"]["claim_support"]["abstained"] is True
    assert "provider_send_intent" not in result["audit_event_types"]


def test_revocation_during_presend_audit_prevents_transport(tmp_path, monkeypatch):
    original = AuditWriter.append

    def revoke_after_intent(self, tenant_id, principal_id, request_id, event_type, metadata):
        event = original(self, tenant_id, principal_id, request_id, event_type, metadata)
        if event_type == "provider_send_intent":
            db = Database(self.db_path)
            with closing(db.connect()) as connection, connection:
                connection.execute("UPDATE versions SET acl='[]'")
                connection.execute("UPDATE tenants SET acl_revision=acl_revision+1")
        return event

    monkeypatch.setattr(AuditWriter, "append", revoke_after_intent)
    seen = []
    result = run(tmp_path, lambda request: seen.append(request) or response())
    assert seen == [] and not (tmp_path / "attempt.json").exists()
    assert result["service_status_code"] == 502
    assert result["packet_count"] == 0
    assert result["runtime"]["attempt"] == 0


def test_restart_cannot_consume_second_attempt(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return response(code=429)

    first, second = run(tmp_path, handler), run(tmp_path, handler)
    assert len(seen) == 1
    assert first["service_status_code"] == second["service_status_code"] == 502
    assert second["packet_count"] == 0
    assert second["runtime"]["attempt"] == 0
    assert second["runtime"]["slot_consumed"] is True
    assert second["runtime"]["network_attempted"] is False


def test_provider_cannot_generate_outside_bound_service(tmp_path):
    provider = ServiceSmokeProvider(load_candidate(CANDIDATE), api_key=secrets.token_urlsafe(24),
                                    ledger_path=tmp_path / "attempt.json",
                                    inner=httpx.MockTransport(lambda request: response()))
    with pytest.raises(ValueError):
        asyncio.run(provider.generate(None))
    assert not (tmp_path / "attempt.json").exists()


def test_postresponse_revocation_blocks_release_and_reports_service_failure(tmp_path):
    def handler(request):
        db = Database(tmp_path / "synthetic.sqlite")
        with closing(db.connect()) as connection, connection:
            connection.execute("UPDATE versions SET acl='[]'")
            connection.execute("UPDATE tenants SET acl_revision=acl_revision+1")
        return response()

    result = run(tmp_path, handler)
    assert result["runtime"]["postflight_validated"] is True
    assert result["postflight_validated"] is False
    assert result["status"] == "service_rejected"
    assert result["service_status_code"] == 409
    assert result["packet_count"] == 0 and result["packet_readable"] is False


def test_revocation_after_claim_consumes_slot_without_network(tmp_path, monkeypatch):
    original = AuditWriter.append

    def revoke_after_claim(self, tenant_id, principal_id, request_id, event_type, metadata):
        event = original(self, tenant_id, principal_id, request_id, event_type, metadata)
        if event_type == "provider_send_intent" and metadata["operation"] == "post_claim":
            db = Database(self.db_path)
            with closing(db.connect()) as connection, connection:
                connection.execute("UPDATE versions SET acl='[]'")
                connection.execute("UPDATE tenants SET acl_revision=acl_revision+1")
        return event

    monkeypatch.setattr(AuditWriter, "append", revoke_after_claim)
    seen = []
    result = run(tmp_path, lambda request: seen.append(request) or response())
    assert seen == [] and (tmp_path / "attempt.json").exists()
    assert result["slot_consumed"] is True and result["network_attempted"] is False
    assert result["live_request_made"] is False and result["packet_count"] == 0
