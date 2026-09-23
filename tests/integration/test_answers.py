import asyncio
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
