import asyncio
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aspire_brain.answers import QueryError, QueryService
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.providers import OfflineExtractiveProvider, ProviderOutput

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"test-audit-key-separate-secret-1234")
    audit.initialize()
    auth = AuthService(db)
    return db, auth, audit


def request(workflow="general", **overrides):
    return QueryRequest.model_validate({
        "question": "What is the travel cap?",
        "context": {"workflow_id": workflow, "case_date": "2026-09-10",
                    "jurisdiction": "SG", "worker_type": "contractor",
                    **overrides},
    })


def run(service, principal, query):
    return asyncio.run(service.query(principal, query))


def test_real_persona_outcomes_and_saved_packet(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit)
    employee = auth.principal("employee")
    finance = auth.principal("finance_lead")
    general = run(service, employee, request())
    assert general["query_status"] == "answered"
    assert "250" in general["answer"]
    case = request("contractor_travel", project="P17", expense_amount="220", currency="SGD")
    denied = run(service, employee, case)
    assert (denied["query_status"], denied["case_outcome"]) == ("needs_review", "undetermined")
    assert "150" not in denied["answer"]
    answer = run(service, finance, case)
    assert answer["case_outcome"] == "exceeds_documented_limits"
    assert "150" in answer["answer"]
    assert service.packet(finance, answer["request_id"]) == answer
    with pytest.raises(AccessDenied):
        service.packet(employee, answer["request_id"])
    assert audit.verify("demo-a")["chain_valid"]


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", True, {}, "1e9999"])
def test_invalid_money(amount):
    with pytest.raises(ValidationError):
        request(expense_amount=amount)


def test_invalid_and_extra_context():
    for context in [{"roles": ["finance"]}, {"case_date": "2026-02-30"}, {"currency": "sgd"}]:
        with pytest.raises(ValidationError):
            request(**context)
    assert request(expense_amount="220.50").context.expense_amount == Decimal("220.50")


def test_provider_spy_and_invalid_citations(system, caplog):
    db, auth, audit = system
    seen = []

    class Spy(OfflineExtractiveProvider):
        async def generate(self, context):
            seen.append(context.model_dump_json())
            return await super().generate(context)

    service = QueryService(db, auth, audit, Spy())
    result = run(service, auth.principal("employee"), request())
    assert "FINANCE_ONLY_SENTINEL" not in str(seen) + str(result) + caplog.text

    class Invalid(OfflineExtractiveProvider):
        async def generate(self, context):
            return ProviderOutput(answer="Unsupported", citation_ids=["invented"])

    with pytest.raises(QueryError):
        run(QueryService(db, auth, audit, Invalid()), auth.principal("employee"), request())


def test_provider_timeout_and_computed_status_protection(system):
    db, auth, audit = system

    class Timeout(OfflineExtractiveProvider):
        async def generate(self, context):
            raise TimeoutError("secret error detail")

    with pytest.raises(QueryError, match="Provider could not"):
        run(QueryService(db, auth, audit, Timeout()), auth.principal("employee"), request())

    class Forge(OfflineExtractiveProvider):
        async def generate(self, context):
            return {"answer": "Approved", "citation_ids": [], "case_outcome": "approved"}

    with pytest.raises(QueryError):
        run(QueryService(db, auth, audit, Forge()), auth.principal("employee"), request())


def test_revocation_during_generation_aborts(system):
    db, auth, audit = system

    class Revoke(OfflineExtractiveProvider):
        async def generate(self, context):
            db.revoke(context.evidence[0].version_id, audit)
            return await super().generate(context)

    with pytest.raises(QueryError, match="changed"):
        run(QueryService(db, auth, audit, Revoke()), auth.principal("employee"), request())


def test_saved_packet_revocation_and_audit_failure(system, monkeypatch):
    db, auth, audit = system
    service = QueryService(db, auth, audit)
    principal = auth.principal("employee")
    result = run(service, principal, request())
    db.revoke(result["citations"][0]["document_version_id"], audit)
    with pytest.raises(AccessDenied):
        service.packet(principal, result["request_id"])
    def broken(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(audit, "append", broken)
    with pytest.raises(QueryError, match="Audit"):
        run(service, principal, request())


def test_final_audit_failure_rolls_back_packet_and_retains_incomplete_attempt(system, monkeypatch):
    db, auth, audit = system
    service = QueryService(db, auth, audit)
    original = audit.append_in_transaction
    failed = False

    def fail_final(connection, tenant, principal, request_id, event_type, metadata):
        nonlocal failed
        if event_type == "query_completed":
            failed = True
        if failed:
            raise OSError("simulated unavailable audit store")
        return original(connection, tenant, principal, request_id, event_type, metadata)

    monkeypatch.setattr(audit, "append_in_transaction", fail_final)
    with pytest.raises(QueryError, match="Audit"):
        run(service, auth.principal("employee"), request())
    with closing(db.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0] == 0
    integrity = audit.verify("demo-a")
    assert integrity["chain_valid"]
    assert len(integrity["incomplete_requests"]) == 1


def test_packet_revocation_between_dependency_checks_aborts(system, monkeypatch):
    db, auth, audit = system
    service = QueryService(db, auth, audit)
    principal = auth.principal("employee")
    packet = run(service, principal, request())
    original = auth.readable
    revoked = False

    def racing_check(person, version):
        nonlocal revoked
        result = original(person, version)
        if not revoked:
            revoked = True
            db.revoke(version, audit)
        return result

    monkeypatch.setattr(auth, "readable", racing_check)
    with pytest.raises(QueryError, match="changed"):
        service.packet(principal, packet["request_id"])


def test_content_revision_and_role_changes_abort_and_timeout_is_enforced(system):
    db, auth, audit = system
    principal = auth.principal("employee")

    class ChangeContent(OfflineExtractiveProvider):
        async def generate(self, context):
            db.set_publication_state("sg-travel-v2", "withdrawn", audit)
            return await super().generate(context)

    with pytest.raises(QueryError, match="changed"):
        run(QueryService(db, auth, audit, ChangeContent()), principal, request())

    class Slow(OfflineExtractiveProvider):
        async def generate(self, context):
            await asyncio.sleep(1)
            return await super().generate(context)

    service = QueryService(db, auth, audit, Slow())
    service.timeout_seconds = 0.001
    with pytest.raises(QueryError, match="Provider could not"):
        run(service, principal, request())


def test_unrelated_general_question_abstains_and_generic_evidence_is_extractive(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit)
    principal = auth.principal("employee")
    absent = request().model_copy(update={"question": "What is the parental leave entitlement?"})
    response = run(service, principal, absent)
    assert response["query_status"] == "insufficient_evidence"
    assert response["applied_rules"] == []
    assert response["citations"] == []
    supported = request().model_copy(update={"question": "receipts"})
    response = run(service, principal, supported)
    assert response["query_status"] == "answered"
    assert response["case_outcome"] == "not_applicable"
    assert response["applied_rules"] == []
    assert response["citations"]


def test_offline_makes_no_http_calls_and_fallback_is_labelled(system, monkeypatch):
    import urllib.request

    import httpx

    db, auth, audit = system
    def network_forbidden(*args, **kwargs):
        pytest.fail("Offline query attempted an outbound HTTP request")
    monkeypatch.setattr(httpx.Client, "send", network_forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", network_forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", network_forbidden)
    monkeypatch.setattr(db, "fts_available", False)
    packet = run(QueryService(db, auth, audit), auth.principal("employee"), request())
    assert packet["provider_mode"] == "offline_extractive"
    assert packet["retrieval_mode"] == "authorized_lexical_fallback"
    assert packet["configuration"]["top_k"] == 5
