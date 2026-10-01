"""D-DEF end-to-end: the ``/api/queries`` release path must refuse a sign / non-ASCII false accept.

The unit gate is one half of the contract. This module exercises the whole ``QueryService.query``
path with a local fake provider that mutates only the *quoted evidence blocks* of an otherwise
exact extractive answer. Before the repair both reproduced vectors were released with
``all_supported: true``, persisted, and readable; after the repair each must:

* raise a controlled ``QueryError`` with status ``502``,
* record an ``unsupported_claim`` audit event,
* persist **no** packet, and leave **no** readable packet behind.

The unchanged control answer must still be released, and the three rejection controls must stay
rejected. No network request, credential or dependency is used; the provider is in-process.
"""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from aspire_brain.answers import QueryError, QueryService
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.providers import OfflineExtractiveProvider, ProviderOutput

ROOT = Path(__file__).resolve().parents[2]

#: Mutations applied to the quoted evidence blocks only (never the service notice), each one a
#: claim the cited source does not contain. ``None`` is the unchanged control.
VECTORS = {
    "v1_sign_loss": lambda body: body.replace("SGD 250", "SGD -250"),
    "v2_zero_token_addition": lambda body: body.replace("2026.", "2026 \u65e0\u9700\u5ba1\u6279."),
    "v3_currency_symbol": lambda body: body.replace("SGD 250", "SGD $250"),
    "numeric_suffix": lambda body: "50" + body.split("SGD 250", 1)[1],
    "v4_unicode_sign": lambda body: body.replace("SGD 250", "SGD \u2212250"),
}


class MutatingProvider(OfflineExtractiveProvider):
    """Emit the ordinary extractive answer, then mutate the quoted evidence blocks."""

    def __init__(self, mutate):
        self._mutate = mutate

    async def generate(self, context):
        base = await super().generate(context)
        head, separator, body = base.answer.partition("\n\n")
        answer = head + separator + self._mutate(body) if separator else self._mutate(base.answer)
        return ProviderOutput(answer=answer, citation_ids=base.citation_ids)


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "ddef.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"ddef-claim-support-key-separate-secret-1234")
    audit.initialize()
    return db, AuthService(db), audit


def request():
    return QueryRequest.model_validate({
        "question": "What is the general travel cap?",
        "context": {"workflow_id": "general", "case_date": "2026-09-10",
                    "jurisdiction": "SG", "worker_type": "contractor", "currency": "SGD"},
    })


def packet_rows(db):
    with closing(db.connect()) as connection:
        return connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0]


def unsupported_claim_events(audit, tenant="demo-a"):
    return [event for event in audit.events(tenant, limit=200, offset=0)
            if event["event_type"] == "provider_error"
            and (event.get("metadata") or {}).get("error_code") == "unsupported_claim"]


@pytest.mark.parametrize("vector", sorted(VECTORS))
def test_vector_is_refused_with_unsupported_claim_evidence(system, vector):
    db, auth, audit = system
    service = QueryService(db, auth, audit, MutatingProvider(VECTORS[vector]))
    principal = auth.principal("employee")
    with pytest.raises(QueryError) as excinfo:
        asyncio.run(service.query(principal, request()))
    assert excinfo.value.status_code == 502
    assert "unsupported claim" in str(excinfo.value).lower()
    # No packet persisted, so none is readable.
    assert packet_rows(db) == 0
    with pytest.raises(AccessDenied):
        service.packet(principal, str(uuid4()))
    # The refusal is visible in the audit chain as an unsupported-claim event.
    assert unsupported_claim_events(audit), "the unsupported claim must be audited"
    assert audit.verify("demo-a")["chain_valid"] is True


def test_unchanged_control_is_still_released(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit, MutatingProvider(lambda body: body))
    packet = asyncio.run(service.query(auth.principal("employee"), request()))
    assert packet["claim_support"]["all_supported"] is True
    assert packet["claim_support"]["unsupported_claims"] == 0
    assert packet_rows(db) == 1


def test_changed_number_control_stays_rejected(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit,
                           MutatingProvider(lambda body: body.replace("SGD 250", "SGD 900")))
    with pytest.raises(QueryError) as excinfo:
        asyncio.run(service.query(auth.principal("employee"), request()))
    assert excinfo.value.status_code == 502
    assert packet_rows(db) == 0



def test_numeric_suffix_is_refused_through_real_http_route(tmp_path):
    from fastapi.testclient import TestClient

    from aspire_brain.config import Settings
    from aspire_brain.main import create_app

    class NumericSuffix(OfflineExtractiveProvider):
        async def generate(self, context):
            item = next(item for item in context.evidence if item.chunk_id == "sg-travel-v2:p2")
            return ProviderOutput(answer="50" + item.text.split("SGD 250", 1)[1],
                                  citation_ids=[item.chunk_id])

    settings = Settings(db_path=tmp_path / "http.db", session_secret="ddef-http-test-session",
                        audit_key=b"ddef-http-test-audit-key-12345678", demo_mode=True)
    with TestClient(create_app(settings, provider=NumericSuffix()),
                    base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
        def headers():
            return {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"],
                    "Origin": "http://localhost"}
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=headers()).status_code == 200
        response = client.post("/api/queries", json=request().model_dump(mode="json"),
                               headers=headers())
        assert response.status_code == 502
        assert "answer" not in response.json()
        assert packet_rows(client.app.state.db) == 0
        errors = unsupported_claim_events(client.app.state.audit)
        assert len(errors) == 1
        denied = client.get("/api/packets/" + errors[0]["request_id"])
        assert denied.status_code == 404
        assert "answer" not in denied.json()
        assert client.app.state.audit.verify("demo-a")["chain_valid"] is True


def test_notice_only_answer_with_valid_citation_is_refused(system):
    class NoticeOnly(OfflineExtractiveProvider):
        async def generate(self, context):
            return ProviderOutput(answer=context.decision_summary,
                                  citation_ids=[context.evidence[0].chunk_id])
    db, auth, audit = system
    service = QueryService(db, auth, audit, NoticeOnly())
    with pytest.raises(QueryError) as excinfo:
        asyncio.run(service.query(auth.principal("employee"), request()))
    assert excinfo.value.status_code == 502
    assert packet_rows(db) == 0
    assert len(unsupported_claim_events(audit)) == 1
    assert audit.verify("demo-a")["chain_valid"] is True


def test_notice_only_answer_is_refused_through_simulated_path(tmp_path):
    import hashlib
    from datetime import UTC, datetime

    from aspire_brain.platforms.simulated import (
        SimulatedPlatformState,
        SimulatedQueryService,
        SimulatedSource,
    )

    class NoticeOnly(OfflineExtractiveProvider):
        async def generate(self, context):
            return ProviderOutput(answer=context.decision_summary,
                                  citation_ids=[context.evidence[0].chunk_id])

    now = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
    text = "Database migration project status: in progress."
    record = SimulatedSource(platform="jira", tenant_id="demo-a", source_id="MIGRATE-42",
        source_kind="issue", version_id="MIGRATE-42:v1", text=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        locator="simulated://jira/MIGRATE-42", parent_id="DB", source_updated_at=now)
    state = SimulatedPlatformState(records=[record],
        principal_map={"employee": {"jira": "jira-employee"}},
        jira_project_grants={"DB": {"jira-employee"}},
        jira_issue_grants={"MIGRATE-42": {"jira-employee"}},
        last_successful_sync={"jira": now}, freshness_budget_seconds={"jira": 3600})
    db = Database(tmp_path / "notice-only-simulated.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"ddef-notice-only-simulated-key-12345")
    audit.initialize()
    service = SimulatedQueryService(AuthService(db), audit, state, provider=NoticeOnly(),
                                    required_platforms=("jira",), clock=lambda: now)
    with pytest.raises(QueryError) as excinfo:
        asyncio.run(service.query("employee", "What is the status of database migration?", now))
    assert excinfo.value.status_code == 502
