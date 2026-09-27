"""Officer reconstruction for the labelled local simulation."""

import asyncio
import hashlib
import json
import secrets
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aspire_brain.audit import AuditError, AuditWriter, ProtectedAuditStore
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.config import Settings
from aspire_brain.db import Database
from aspire_brain.main import create_app
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(UTC)
SPACE = "payment-gateway"
QUESTION = "What is the latest payment runbook?"


def source(source_id, text):
    return SimulatedSource(
        platform="confluence", tenant_id="demo-a", source_id=source_id,
        source_kind="space_page", version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://confluence/{source_id}", parent_id=SPACE,
        source_updated_at=NOW - timedelta(minutes=2),
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "officer.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    auth = AuthService(db)
    protected = ProtectedAuditStore(db.path, secrets.token_bytes(32), audit, auth)
    protected.initialize()
    state = SimulatedPlatformState(
        records=[source("runbook", "Payment runbook: enable failover."),
                 source("restricted", "Confidential payment report.")],
        principal_map={"employee": {"confluence": "reader"}},
        confluence_space_grants={SPACE: {"reader"}},
        confluence_page_grants={"runbook": {"reader"}},
        last_successful_sync={"confluence": NOW},
        freshness_budget_seconds={"confluence": 3600},
    )
    service = SimulatedQueryService(auth, audit, state, protected_audit=protected,
                                    required_platforms=("confluence",), clock=lambda: NOW)
    return auth, audit, protected, service, db


def test_officer_reconstructs_protected_query_and_decisions(system):
    auth, audit, protected, service, db = system
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    result = protected.inquire(
        "auditor", subject_id="employee", platform="confluence",
        parent_id=SPACE, since=NOW - timedelta(days=30), until=NOW + timedelta(minutes=1),
    )
    assert result["simulation_mode"] == "simulated"
    assert result["integrity"]["chain_valid"] is True
    assert result["integrity"]["completeness_unproven"] is True
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["question"] == QUESTION
    assert entry["answer"] == packet["answer"]
    assert entry["audit_event_id"] == packet["audit_event_id"]
    assert entry["retrieved_ids"] == ["confluence:runbook:runbook:v1"]
    assert {(d["source_id"], d["allowed"]) for d in entry["decisions"]} == {
        ("runbook", True), ("restricted", False)}
    assert entry["timestamp"]
    with closing(db.connect()) as connection:
        raw = connection.execute("SELECT ciphertext FROM protected_audit_payloads").fetchone()[0]
    assert QUESTION.encode() not in raw
    assert packet["answer"].encode() not in raw
    assert audit.verify("demo-a")["chain_valid"]
    by_document = protected.inquire(
        "auditor", subject_id="employee", platform="confluence",
        source_id="restricted", since=NOW - timedelta(days=30),
        until=NOW + timedelta(minutes=1),
    )
    assert by_document["entries"] == []
    denied = protected.inquire(
        "auditor", subject_id="employee", platform="confluence",
        source_id="restricted", decision_mode="denied",
        since=NOW - timedelta(days=30), until=NOW + timedelta(minutes=1),
    )
    assert len(denied["entries"]) == 1


def test_inquiry_denies_non_officer_and_cross_tenant(system):
    auth, _, protected, service, _ = system
    asyncio.run(service.query("employee", QUESTION, NOW))
    for principal in ("employee", "other_tenant"):
        with pytest.raises(AccessDenied):
            protected.inquire(principal, subject_id="employee", platform="confluence",
                              parent_id=SPACE, since=NOW - timedelta(days=1), until=NOW)


def test_inquiry_detects_missing_payload_and_tampering(system):
    auth, audit, protected, service, db = system
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    with closing(db.connect()) as connection, connection:
        connection.execute("UPDATE protected_audit_payloads SET ciphertext=? WHERE request_id=?",
                           (b"corrupt", packet["request_id"]))
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee",
                          platform="confluence", parent_id=SPACE,
                          since=NOW - timedelta(days=1), until=NOW)
    assert audit.verify("demo-a")["chain_valid"]


def test_inquiry_detects_deleted_protected_payload(system):
    _, _, protected, service, db = system
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    with closing(db.connect()) as connection, connection:
        connection.execute("DELETE FROM protected_audit_payloads WHERE request_id=?",
                           (packet["request_id"],))
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee", platform="confluence",
                          parent_id=SPACE, since=NOW - timedelta(days=1),
                          until=NOW + timedelta(minutes=1))


def test_case_five_requires_auditor_and_uses_real_prior_fixture_query(tmp_path):
    settings = Settings(db_path=tmp_path / "web.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                        demo_mode=True)
    with TestClient(create_app(settings), base_url="http://localhost",
                    client=("127.0.0.1", 50000)) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.get("/api/cases/case_5").status_code == 405
        session = client.get("/api/session").json()
        headers = {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}
        assert client.post("/api/cases/case_2", headers=headers).status_code == 401
        assert client.post("/api/demo/session", json={"user_id": "employee"}, headers=headers).status_code == 200
        session = client.get("/api/session").json()
        headers["X-CSRF-Token"] = session["csrf_token"]
        assert client.post("/api/cases/case_2", headers=headers).status_code == 200
        assert client.post("/api/cases/case_5", headers=headers).status_code == 403
        assert client.post("/api/demo/session", json={"user_id": "auditor"}, headers=headers).status_code == 200
        headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/cases/case_5", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "answered"
        assert body["inquiry"]["entries"]
        assert body["inquiry"]["entries"][0]["question"]
        assert body["inquiry"]["entries"][0]["answer"]
        params = {"subject_id": "employee", "platform": "confluence",
                  "source_id": "RUNBOOK-PAY",
                  "since": (NOW - timedelta(days=30)).isoformat(),
                  "until": (NOW + timedelta(minutes=1)).isoformat()}
        searched = client.get("/api/audit/inquiry", params=params)
        assert searched.status_code == 200, searched.text
        assert searched.json()["entries"]
        invalid = client.get("/api/audit/inquiry", params={**params, "parent_id": "bad space"})
        assert invalid.status_code == 422
        assert client.app.state.audit.verify("demo-a")["incomplete_requests"] == []
        request_id = searched.json()["entries"][0]["request_id"]
        with closing(client.app.state.db.connect()) as connection, connection:
            connection.execute("UPDATE protected_audit_payloads SET ciphertext=? WHERE request_id=?",
                               (b"corrupt", request_id))
        assert client.get("/api/audit/inquiry", params=params).status_code == 503
        assert client.app.state.audit.verify("demo-a")["incomplete_requests"] == []
        events = client.app.state.audit.events("demo-a", limit=1000)
        assert any(event["event_type"] == "officer_inquiry_failed" for event in events)


def test_case_routes_use_caller_and_do_not_run_in_disabled_demo(tmp_path):
    settings = Settings(db_path=tmp_path / "web.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                        demo_mode=True)
    with TestClient(create_app(settings), base_url="http://localhost",
                    client=("127.0.0.1", 50000)) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        with closing(client.app.state.db.connect()) as connection:
            before = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        assert client.get("/api/cases/case_1").status_code == 405
        with closing(client.app.state.db.connect()) as connection:
            assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before
        session = client.get("/api/session").json()
        headers = {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}
        assert client.post("/api/demo/session", json={"user_id": "auditor"}, headers=headers).status_code == 200
        headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
        result = client.post("/api/cases/case_1", headers=headers).json()
        assert result["principal"] == "auditor"
        assert result["packet"]["citations"] == []
    from dataclasses import replace
    with TestClient(create_app(replace(settings, demo_mode=False)), base_url="http://localhost",
                    client=("127.0.0.1", 50000)) as client:
        session = client.get("/api/session").json()
        headers = {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}
        assert client.post("/api/cases/case_1", headers=headers).status_code == 401


def test_case_expectations_are_sourced_to_pdf():
    cases = json.loads((ROOT / "eval/g1-case-expectations.json").read_text())
    assert cases["detailed_case_brief_available"] is True
    assert cases["scenario_details_inferred_from_report"] is False
    assert cases["scenarios"][1]["required_platforms"] == ["confluence"]
    assert cases["scenarios"][4]["required_platforms"] == ["confluence"]
