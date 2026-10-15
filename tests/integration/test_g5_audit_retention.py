"""G5 reconciliation of the audit/retention/completion claims.

The G4 retention path already had dry-run/apply, tenant scoping and an atomic tombstone +
deletion + audit commit. This module verifies the parts the independent review found
unverified or mis-stated:

* a declared policy is **not** evidence that cleanup has run — only an explicit apply is;
* repeated applies are idempotent and leave the chain verifiable;
* tampering is detected both before and after expiration, and a retention record cannot mask it;
* retention removes **only** encrypted protected payloads: plaintext saved packets keep their
  own lifetime;
* protected inquiry covers simulated case queries only — the original travel-policy query path
  is not reconstructable and that limit is labelled rather than implied away.
"""

import asyncio
import hashlib
import secrets
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aspire_brain.answers import QueryService
from aspire_brain.audit import AuditError, AuditWriter, ProtectedAuditStore
from aspire_brain.audit.retention import RetentionPolicy
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
SPACE = "payment-gateway"
QUESTION = "What is the latest payment runbook?"
ANSWER_TEXT = "Payment runbook: enable failover before rolling back the config."
TRAVEL_QUERY = {"question": "What is the contractor travel cap?",
                "context": {"workflow_id": "general", "case_date": "2026-09-10",
                            "jurisdiction": "SG", "worker_type": "contractor",
                            "project": None, "cost_centre": None, "expense_amount": None,
                            "currency": "SGD"}}


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
    db = Database(tmp_path / "g5-retention.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    auth = AuthService(db)
    policy = RetentionPolicy(max_age_days=30, max_entries=1)
    protected = ProtectedAuditStore(db.path, secrets.token_bytes(32), audit, auth,
                                    retention=policy)
    protected.initialize()
    state = SimulatedPlatformState(
        records=[source("runbook", ANSWER_TEXT), source("restricted", "Confidential report.")],
        principal_map={"employee": {"confluence": "reader"}},
        confluence_space_grants={SPACE: {"reader"}},
        confluence_page_grants={"runbook": {"reader"}},
        last_successful_sync={"confluence": NOW}, freshness_budget_seconds={"confluence": 3600},
    )
    service = SimulatedQueryService(auth, audit, state, protected_audit=protected,
                                    required_platforms=("confluence",), clock=lambda: NOW)
    return db, audit, auth, protected, service, policy


def count(db, table):
    with closing(db.connect()) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def run_queries(service, count_=3):
    return [asyncio.run(service.query("employee", QUESTION, NOW)) for _ in range(count_)]


def test_a_declared_policy_is_not_evidence_that_cleanup_has_run(system):
    db, _audit, _auth, protected, service, _policy = system
    run_queries(service)
    assert protected.retention is not None
    assert count(db, "protected_audit_payloads") == 3
    assert count(db, "protected_audit_retention") == 0
    # Only an explicit apply removes anything; the configured window alone does nothing.
    dry = protected.apply_retention(tenant_id="demo-a", now=NOW)
    assert dry["applied"] is False and dry["removed"] == 0 and dry["would_remove"] == 2
    assert count(db, "protected_audit_payloads") == 3


def test_repeated_applies_are_idempotent_and_keep_the_chain_verifiable(system):
    db, audit, _auth, protected, service, _policy = system
    run_queries(service)
    first = protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    assert first["removed"] == 2
    tombstones = count(db, "protected_audit_retention")
    second = protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    assert second["removed"] == 0 and second["would_remove"] == 0
    assert count(db, "protected_audit_retention") == tombstones
    assert count(db, "protected_audit_payloads") == 1
    assert audit.verify("demo-a")["chain_valid"] is True
    events = [event for event in audit.events("demo-a", limit=1000)
              if event["event_type"] == "retention_applied"]
    assert len(events) == 1  # a no-op apply records no second chain event


def test_tampering_is_detected_before_and_after_expiration(system):
    db, _audit, _auth, protected, service, _policy = system
    packets = run_queries(service)
    with closing(db.connect()) as connection, connection:
        connection.execute("UPDATE protected_audit_payloads SET ciphertext=? WHERE request_id=?",
                           (b"corrupt", packets[0]["request_id"]))
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee", platform="confluence",
                          parent_id=SPACE, since=NOW - timedelta(days=1),
                          until=NOW + timedelta(minutes=1))
    # Restore, expire the older two, then tamper a surviving payload.
    with closing(db.connect()) as connection, connection:
        connection.execute("DELETE FROM protected_audit_payloads WHERE request_id=?",
                           (packets[0]["request_id"],))
    protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    with closing(db.connect()) as connection, connection:
        connection.execute("UPDATE protected_audit_payloads SET ciphertext=?",
                           (b"corrupt",))
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee", platform="confluence",
                          parent_id=SPACE, since=NOW - timedelta(days=1),
                          until=NOW + timedelta(minutes=1))


def test_a_retention_record_cannot_mask_a_removed_payload(system):
    db, _audit, _auth, protected, service, _policy = system
    packets = run_queries(service)
    # Remove a payload and add a plausible tombstone, but no matching chain record.
    with closing(db.connect()) as connection, connection:
        connection.execute("INSERT INTO protected_audit_retention VALUES (?,?,?,?,?)",
                           (packets[0]["request_id"], "demo-a", "fabricated", NOW.isoformat(), "{}"))
        connection.execute("DELETE FROM protected_audit_payloads WHERE request_id=?",
                           (packets[0]["request_id"],))
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee", platform="confluence",
                          parent_id=SPACE, since=NOW - timedelta(days=1),
                          until=NOW + timedelta(minutes=1))


def test_retention_removes_only_encrypted_payloads_not_plaintext_saved_packets(system):
    db, audit, _auth, protected, service, _policy = system
    packets = run_queries(service)
    assert count(db, "simulated_packets") == 3
    protected.apply_retention(tenant_id="demo-a", now=NOW, apply=True)
    # The encrypted payloads for the expired queries are gone...
    assert count(db, "protected_audit_payloads") == 1
    # ...but plaintext saved packets have their own lifetime and are untouched.
    assert count(db, "simulated_packets") == 3
    still_readable = service.packet("employee", packets[-1]["request_id"])
    assert still_readable["answer"]
    assert audit.verify("demo-a")["chain_valid"] is True


def test_protected_inquiry_covers_travel_policy_queries_too(system):
    db, _audit, auth, protected, service, _policy = system
    travel = QueryService(db, auth, _audit, protected_audit=protected)
    travel_packet = asyncio.run(travel.query(auth.principal("employee"),
                                             QueryRequest.model_validate(TRAVEL_QUERY)))
    assert count(db, "packets") == 1
    assert count(db, "protected_audit_payloads") == 1
    # The four-platform filter does not match a policy-store query ...
    inquiry = protected.inquire("auditor", subject_id="employee", platform="confluence",
                               parent_id=SPACE, since=NOW - timedelta(days=1),
                               until=NOW + timedelta(minutes=1), decision_mode="any")
    assert inquiry["scope"] == "all_protected_queries"
    assert inquiry["entries"] == []
    # ... but "what did employee access" finds it, with the answer and every decision.
    everything = protected.inquire("auditor", subject_id="employee",
                                   since=NOW - timedelta(days=1),
                                   until=datetime.now(UTC) + timedelta(minutes=1))
    entry = next(item for item in everything["entries"]
                 if item["request_id"] == travel_packet["request_id"])
    assert entry["operation"] == "protected_query"
    assert entry["answer"] == travel_packet["answer"]
    assert {decision["platform"] for decision in entry["decisions"]} == {"policy_store"}
    assert any(decision["retrieved"] for decision in entry["decisions"])
    assert any(not decision["allowed"] for decision in entry["decisions"])


def test_travel_policy_queries_stay_outside_an_unconfigured_protected_store(system):
    db, _audit, auth, protected, service, _policy = system
    asyncio.run(QueryService(db, auth, _audit).query(
        auth.principal("employee"), QueryRequest.model_validate(TRAVEL_QUERY)))
    assert count(db, "protected_audit_payloads") == 0
