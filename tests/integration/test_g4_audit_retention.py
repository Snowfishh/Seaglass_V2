"""G4 audit payload retention, authorised search and visible anchoring limits.

Written before the implementation. Retention must remove only the encrypted payload, leave
the HMAC chain verifiable, and be *explained* so an officer can tell an expired record from
a tampered one. The chain's unanchored tail must stay visible as an unproven completeness
claim, and routine audit metadata must stay minimised.
"""

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
from aspire_brain.audit.engine import SAFE_METADATA
from aspire_brain.audit.retention import RetentionPolicy
from aspire_brain.auth import AuthService
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
QUESTIONS = ("What is the latest payment runbook?",
             "What does the payment runbook say about failover?",
             "What does the payment runbook say about rolling back?")
ANSWER_TEXT = "Payment runbook: enable failover before rolling back the config."


def source(source_id, text):
    return SimulatedSource(
        platform="confluence", tenant_id="demo-a", source_id=source_id,
        source_kind="space_page", version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://confluence/{source_id}", parent_id=SPACE,
        source_updated_at=NOW - timedelta(minutes=2),
    )


def build_store(tmp_path, policy):
    db = Database(tmp_path / "g4-retention.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    auth = AuthService(db)
    protected = ProtectedAuditStore(db.path, secrets.token_bytes(32), audit, auth,
                                    retention=policy)
    protected.initialize()
    state = SimulatedPlatformState(
        records=[source("runbook", ANSWER_TEXT), source("restricted", "Confidential report.")],
        principal_map={"employee": {"confluence": "reader"}},
        confluence_space_grants={SPACE: {"reader"}},
        confluence_page_grants={"runbook": {"reader"}},
        last_successful_sync={"confluence": NOW},
        freshness_budget_seconds={"confluence": 3600},
    )
    service = SimulatedQueryService(auth, audit, state, protected_audit=protected,
                                    required_platforms=("confluence",), clock=lambda: NOW)
    return db, audit, auth, protected, service


def record_queries(service):
    return [asyncio.run(service.query("employee", question, NOW)) for question in QUESTIONS]


def count_payloads(db, tenant_id=None):
    with closing(db.connect()) as connection:
        if tenant_id is None:
            return connection.execute("SELECT COUNT(*) FROM protected_audit_payloads").fetchone()[0]
        return connection.execute("SELECT COUNT(*) FROM protected_audit_payloads WHERE tenant_id=?",
                                  (tenant_id,)).fetchone()[0]


def test_retention_requires_a_declared_tenant(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=100)
    _db, _audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    with pytest.raises(TypeError):
        protected.apply_retention(now=NOW, apply=True)
    with pytest.raises(ValueError):
        protected.apply_retention(tenant_id="demo-a", now=NOW.replace(tzinfo=None), apply=True)


def test_retention_dry_run_is_the_default_and_removes_nothing(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=1)
    db, _audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    report = protected.apply_retention(tenant_id="demo-a", now=NOW)
    assert report["applied"] is False
    assert report["tenant_id"] == "demo-a"
    assert report["removed"] == 0
    assert report["would_remove"] == 2
    assert report["removed_request_ids"] == []
    assert report["evaluated"] == 3
    assert report["policy"] == {"max_age_days": 30, "max_entries": 1, "basis": policy.basis}
    assert count_payloads(db) == 3
    inquiry = protected.inquire("auditor", subject_id="employee", platform="confluence",
                               parent_id=SPACE, since=NOW - timedelta(days=1),
                               until=NOW + timedelta(minutes=1))
    assert len(inquiry["entries"]) == 3


def test_retention_removes_expired_payloads_and_keeps_the_chain_verifiable(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=2)
    db, audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    report = protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    assert report["applied"] is True
    assert report["removed"] == 1
    assert report["retained"] == 2
    assert report["chain_preserved"] is True
    assert set(report["removal_reasons"].values()) == {"max_entries"}
    assert count_payloads(db) == 2
    assert audit.verify("demo-a")["chain_valid"] is True
    with closing(db.connect()) as connection:
        tombstones = connection.execute(
            "SELECT COUNT(*) FROM protected_audit_retention").fetchone()[0]
    assert tombstones == 1


def test_retention_is_scoped_to_one_tenant(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=1)
    db, audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    # A second tenant stores one payload; its volume must not evict another tenant's records.
    other = ProtectedAuditStore(db.path, secrets.token_bytes(32), audit, AuthService(db),
                                retention=policy)
    other.initialize()
    with closing(db.connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        other.store_in_transaction(connection, "demo-b", "req-b", "event-b",
                                   {"subject_id": "other_tenant", "question": "Other question",
                                    "packet": {"answer": "Other answer"},
                                    "retrieved_ids": [], "decisions": []})
    report = protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    assert report["removed"] == 2
    assert count_payloads(db, "demo-a") == 1
    assert count_payloads(db, "demo-b") == 1
    with pytest.raises(ValueError):
        protected.apply_retention(tenant_id="bad tenant", now=NOW, apply=True)


def test_retention_by_age_removes_every_expired_payload(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=100)
    db, audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    report = protected.apply_retention(tenant_id="demo-a", now=NOW + timedelta(days=40),
                                       apply=True)
    assert report["removed"] == 3 and report["retained"] == 0
    assert set(report["removal_reasons"].values()) == {"max_age"}
    assert count_payloads(db) == 0
    assert audit.verify("demo-a")["chain_valid"] is True


def test_retention_removal_is_explained_not_treated_as_tampering(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=1)
    db, _audit, _auth, protected, service = build_store(tmp_path, policy)
    packets = record_queries(service)
    protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    inquiry = protected.inquire("auditor", subject_id="employee", platform="confluence",
                               parent_id=SPACE, since=NOW - timedelta(days=1),
                               until=NOW + timedelta(minutes=1))
    assert len(inquiry["entries"]) == 1
    assert inquiry["entries"][0]["request_id"] == packets[-1]["request_id"]
    assert inquiry["retention"]["removed_count"] == 2
    assert inquiry["retention"]["policy"] == {"max_age_days": 30, "max_entries": 1,
                                             "basis": policy.basis}
    assert inquiry["retention"]["note"]
    assert inquiry["integrity"]["chain_valid"] is True


def test_payload_deleted_without_a_retention_record_is_still_detected(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=100)
    _db, _audit, _auth, protected, service = build_store(tmp_path, policy)
    packet = asyncio.run(service.query("employee", QUESTIONS[0], NOW))
    with closing(protected._connect()) as connection, connection:
        connection.execute("DELETE FROM protected_audit_payloads WHERE request_id=?",
                           (packet["request_id"],))
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee", platform="confluence",
                          parent_id=SPACE, since=NOW - timedelta(days=1),
                          until=NOW + timedelta(minutes=1))


def test_retention_is_recorded_in_the_audit_chain_atomically(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=1)
    db, audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    events = [event for event in audit.events("demo-a", limit=1000)
              if event["event_type"] == "retention_applied"]
    assert len(events) == 1
    assert events[0]["metadata"]["operation"] == "protected_audit_retention"
    assert events[0]["metadata"]["source_count"] == 2
    assert set(events[0]["metadata"]) <= SAFE_METADATA
    assert audit.verify("demo-a")["chain_valid"] is True
    # A dry run must not add a chain record.
    assert protected.apply_retention(tenant_id="demo-a", now=NOW)["removed"] == 0
    assert len([event for event in audit.events("demo-a", limit=1000)
                if event["event_type"] == "retention_applied"]) == 1


def test_forged_retention_record_does_not_explain_a_removed_payload(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=1)
    db, _audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    # Delete the oldest payload and forge a tombstone for it, without a chain record.
    with closing(db.connect()) as connection, connection:
        request_id = connection.execute(
            "SELECT request_id FROM protected_audit_payloads ORDER BY rowid LIMIT 1").fetchone()[0]
        connection.execute("INSERT INTO protected_audit_retention VALUES (?,?,?,?,?)",
                           (request_id, "demo-a", "forged", NOW.isoformat(), "{}"))
        connection.execute("DELETE FROM protected_audit_payloads WHERE request_id=?",
                           (request_id,))
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee", platform="confluence",
                          parent_id=SPACE, since=NOW - timedelta(days=1),
                          until=NOW + timedelta(minutes=1))


def test_inquiry_keeps_the_checkpoint_anchoring_limit_visible(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=100)
    _db, _audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    inquiry = protected.inquire("auditor", subject_id="employee", platform="confluence",
                               parent_id=SPACE, since=NOW - timedelta(days=1),
                               until=NOW + timedelta(minutes=1))
    anchoring = inquiry["checkpoint_anchoring"]
    assert anchoring["completeness_unproven"] is True
    assert anchoring["verified_through_checkpoint"] is False
    assert anchoring["unanchored_tail_events"] == inquiry["integrity"]["unanchored_tail_events"]
    assert "unanchored" in anchoring["note"].lower()


def test_officer_search_filters_by_user_space_and_time(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=100)
    _db, _audit, _auth, protected, service = build_store(tmp_path, policy)
    record_queries(service)
    by_user = protected.inquire("auditor", subject_id="employee", platform="confluence",
                               parent_id=SPACE, since=NOW - timedelta(days=1),
                               until=NOW + timedelta(minutes=1))
    assert len(by_user["entries"]) == 3
    by_document = protected.inquire("auditor", subject_id="employee", platform="confluence",
                                   source_id="runbook", since=NOW - timedelta(days=1),
                                   until=NOW + timedelta(minutes=1))
    assert len(by_document["entries"]) == 3
    by_denied = protected.inquire("auditor", subject_id="employee", platform="confluence",
                                 source_id="restricted", decision_mode="denied",
                                 since=NOW - timedelta(days=1), until=NOW + timedelta(minutes=1))
    assert len(by_denied["entries"]) == 3
    out_of_window = protected.inquire("auditor", subject_id="employee", platform="confluence",
                                     parent_id=SPACE, since=NOW - timedelta(days=10),
                                     until=NOW - timedelta(days=5))
    assert out_of_window["entries"] == []
    other_subject = protected.inquire("auditor", subject_id="auditor", platform="confluence",
                                      parent_id=SPACE, since=NOW - timedelta(days=1),
                                      until=NOW + timedelta(minutes=1))
    assert other_subject["entries"] == []


def test_routine_audit_metadata_stays_minimised(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=100)
    _db, audit, _auth, _protected, service = build_store(tmp_path, policy)
    record_queries(service)
    events = audit.events("demo-a", limit=1000)
    completed = [event for event in events if event["event_type"] == "query_completed"]
    assert completed
    for event in completed:
        assert set(event["metadata"]) <= SAFE_METADATA
    serialized = json.dumps([event["metadata"] for event in events])
    assert ANSWER_TEXT not in serialized
    assert QUESTIONS[0] not in serialized
    with pytest.raises(AuditError):
        audit.append("demo-a", "employee", "req-retention-1", "query_completed",
                     {"question": QUESTIONS[0]})


def test_officer_http_inquiry_reports_retention_and_anchoring(tmp_path):
    policy = RetentionPolicy(max_age_days=30, max_entries=2)
    settings = Settings(db_path=tmp_path / "g4-web.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                        demo_mode=True, audit_retention_days=policy.max_age_days,
                        audit_retention_max_entries=policy.max_entries)
    with TestClient(create_app(settings), base_url="http://localhost",
                    client=("127.0.0.1", 50000)) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        session = client.get("/api/session").json()
        headers = {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=headers).status_code == 200
        headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
        assert client.post("/api/cases/case_2", headers=headers).status_code == 200
        assert client.app.state.protected_audit.retention is not None
        assert client.app.state.protected_audit.retention.max_entries == 2
        assert client.post("/api/demo/session", json={"user_id": "auditor"},
                           headers=headers).status_code == 200
        headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/cases/case_5", headers=headers)
        assert response.status_code == 200, response.text
        inquiry = response.json()["inquiry"]
        assert inquiry["retention"]["policy"]["max_entries"] == 2
        assert inquiry["checkpoint_anchoring"]["completeness_unproven"] is True
        assert client.app.state.audit.verify("demo-a")["incomplete_requests"] == []
