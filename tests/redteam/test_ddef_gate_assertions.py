"""D-DEF gate discrimination: unrelated errors and missing side effects must fail."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.redteam
ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval/redteam" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refused_outcome():
    return {
        "status_code": 502, "released": False, "support_denominator": 0,
        "all_supported": None, "unsupported_claims": None,
        "query_attempt_count": 1, "provider_error_count": 1,
        "unsupported_claim_error_count": 1, "query_aborted_count": 1,
        "query_completed_count": 0, "query_failed_count": 0,
        "request_id_from_audit": "failed-request", "packet_count": 0,
        "packet_read_status": 404, "read_request_id": "failed-request",
        "outward_fields": ["detail"], "read_outward_fields": ["detail"],
        "chain_valid": True, "exact_answer_equal": False, "provider_called": True,
    }


def test_an_unrelated_502_cannot_satisfy_the_service_gate(monkeypatch):
    from aspire_brain.answers import QueryError, QueryService

    gate = load("ddef_gate")

    async def unrelated_error(self, principal, request):
        raise QueryError("Unrelated provider timeout", 502)

    monkeypatch.setattr(QueryService, "query", unrelated_error)
    monkeypatch.setattr(gate, "SERVICE_VECTORS", {"v1_sign_loss": lambda body: body})
    rows = gate._service_report()
    assert rows and all(row["ok"] is False for row in rows)


def test_a_real_refusal_without_its_audit_error_fails(monkeypatch):
    from aspire_brain.audit import AuditWriter

    gate = load("ddef_gate")
    original = AuditWriter.events

    def omit_error(self, *args, **kwargs):
        return [event for event in original(self, *args, **kwargs)
                if event["event_type"] != "provider_error"]

    monkeypatch.setattr(AuditWriter, "events", omit_error)
    monkeypatch.setattr(gate, "SERVICE_VECTORS", {"v1_sign_loss": gate.SERVICE_VECTORS[
        "v1_sign_loss"]})
    row = gate._service_report()[0]
    assert row["status_code"] == 502
    assert row["checks"]["one_provider_error"] is False
    assert row["ok"] is False


def test_a_real_refusal_that_leaves_a_packet_fails(monkeypatch):
    from contextlib import closing

    from aspire_brain.answers import QueryError, QueryService

    gate = load("ddef_gate")
    original = QueryService.query

    async def persist_after_refusal(self, principal, request):
        try:
            return await original(self, principal, request)
        except QueryError:
            with closing(self.db.connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("unexpected-persisted-packet", principal["tenant_id"], principal["id"],
                     "[]", "{}", "{}", 0, 0))
            raise

    monkeypatch.setattr(QueryService, "query", persist_after_refusal)
    monkeypatch.setattr(gate, "SERVICE_VECTORS", {"v1_sign_loss": gate.SERVICE_VECTORS[
        "v1_sign_loss"]})
    row = gate._service_report()[0]
    assert row["status_code"] == 502
    assert row["checks"]["zero_persisted_packets"] is False
    assert row["ok"] is False


@pytest.mark.parametrize("field,value", [
    ("status_code", 503), ("provider_error_count", 2),
    ("unsupported_claim_error_count", 0), ("query_aborted_count", 0),
    ("query_attempt_count", 0), ("request_id_from_audit", None),
    ("packet_count", 1), ("packet_read_status", 200),
    ("read_request_id", "unrelated-random-id"), ("chain_valid", False),
    ("outward_fields", ["detail", "answer"]),
    ("read_outward_fields", ["detail", "claim_support"]),
    ("provider_called", False),
])
def test_missing_refusal_evidence_or_persistence_fails_the_gate(field, value):
    gate = load("ddef_gate")
    outcome = refused_outcome()
    assert all(gate._case_checks(False, outcome).values())
    corrupted = {**outcome, field: value}
    assert not all(gate._case_checks(False, corrupted).values())


def test_control_requires_actual_supported_and_readable_exact_answer():
    gate = load("ddef_gate")
    outcome = {**refused_outcome(), "status_code": 200, "released": True,
               "support_denominator": 1, "all_supported": True, "unsupported_claims": 0,
               "provider_error_count": 0, "unsupported_claim_error_count": 0,
               "query_aborted_count": 0, "query_completed_count": 1,
               "packet_count": 1, "packet_read_status": 200, "exact_answer_equal": True}
    assert all(gate._case_checks(True, outcome).values())
    for field, value in (("support_denominator", 0), ("packet_count", 0),
                         ("exact_answer_equal", False), ("unsupported_claims", 1),
                         ("provider_error_count", 1), ("query_aborted_count", 1)):
        assert not all(gate._case_checks(True, {**outcome, field: value}).values())


def test_release_gate_hashes_its_ddef_gate_bytes():
    gate = load("release_gate")
    assert "eval/redteam/ddef_gate.py" in gate.record_source_hashes()


def test_release_gate_preserves_full_ddef_observations(monkeypatch):
    gate = load("release_gate")
    detailed = {"unit_ok": True, "service_ok": True, "passed": True,
                "unit_vectors": [{"case_id": "unit-sentinel", "observed": {"x": 1}}],
                "service_vectors": [{"case_id": "http-sentinel", "checks": {"x": True}}],
                "source_hashes": {"eval/redteam/ddef_gate.py": "sentinel"}}
    monkeypatch.setattr(gate, "load_ddef_gate", lambda: SimpleNamespace(
        run_ddef_gate=lambda: deepcopy(detailed)))
    result = gate.evaluate()
    assert result["_per_case_report"].get("ddef_gate") == detailed


def test_gate_declares_numeric_suffix_and_boundary_discrimination_vectors():
    gate = load("ddef_gate")
    unit_ids = {row[0] for row in gate.UNIT_VECTORS}
    assert {"numeric_prefix", "numeric_suffix", "sign_boundary", "currency_boundary",
            "percent_boundary", "unit_boundary", "unicode_boundary",
            "control_exact_numeric", "control_exact_signed", "control_exact_currency",
            "control_exact_percent", "control_exact_unit", "control_exact_unicode"} <= unit_ids
    assert {"numeric_suffix", "notice_only"} <= set(gate.SERVICE_VECTORS)
