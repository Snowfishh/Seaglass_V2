"""Behavioural integrity tests using independently altered stored events."""

import hashlib
import hmac
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from aspire_brain.audit import AuditError, AuditWriter


@pytest.fixture
def writer(tmp_path):
    result = AuditWriter(tmp_path / "audit.db", b"a" * 32)
    result.initialize()
    return result


def append(writer, request="request-1", event="query_attempt", tenant="demo-a"):
    return writer.append(
        tenant, "employee", request, event, {"provider_mode": "offline_extractive"}
    )


def alter(writer, sql, values=()):
    with closing(sqlite3.connect(writer.db_path)) as db, db:
        db.execute(sql, values)


def test_empty_and_complete_chains_do_not_claim_completeness(writer):
    assert writer.verify("demo-a")["chain_valid"]
    append(writer)
    append(writer, event="query_completed")
    result = writer.verify("demo-a")
    assert result["chain_valid"]
    assert result["completeness_unproven"]
    assert not result["verified_through_checkpoint"]
    assert result["incomplete_requests"] == []


@pytest.mark.parametrize(
    "sql,values",
    [
        ("UPDATE audit_events SET principal_id = ? WHERE sequence = 1", ("finance_lead",)),
        ("UPDATE audit_events SET event_type = ? WHERE sequence = 1", ("query_completed",)),
        ("UPDATE audit_events SET metadata_json = ? WHERE sequence = 1", ('{"status":"altered"}',)),
        ("UPDATE audit_events SET timestamp = ? WHERE sequence = 1", ("2020-01-01T00:00:00Z",)),
        ("UPDATE audit_events SET previous_hmac = ? WHERE sequence = 2", ("f" * 64,)),
        ("UPDATE audit_events SET sequence = 8 WHERE sequence = 2", ()),
        ("DELETE FROM audit_events WHERE sequence = 2", ()),
    ],
)
def test_detects_content_link_sequence_and_middle_deletion(writer, sql, values):
    for number in range(3):
        append(writer, f"request-{number}")
    alter(writer, sql, values)
    assert not writer.verify("demo-a")["chain_valid"]


def test_sequence_order_is_verified_not_timestamp_order(writer):
    append(writer)
    append(writer, event="query_completed")
    alter(writer, "UPDATE audit_events SET sequence = 9 WHERE sequence = 1")
    alter(writer, "UPDATE audit_events SET sequence = 1 WHERE sequence = 2")
    alter(writer, "UPDATE audit_events SET sequence = 2 WHERE sequence = 9")
    assert not writer.verify("demo-a")["chain_valid"]


def test_retained_checkpoint_detects_truncation_but_unanchored_tail_is_unproven(writer):
    append(writer)
    append(writer, event="query_completed")
    anchor = writer.checkpoint("demo-a")
    result = writer.verify("demo-a", anchor)
    assert result["chain_valid"] and result["verified_through_checkpoint"]
    assert result["completeness_unproven"]
    alter(writer, "DELETE FROM audit_events WHERE sequence = 2")
    assert writer.verify("demo-a")["chain_valid"]
    anchored = writer.verify("demo-a", anchor)
    assert anchored["chain_valid"]
    assert not anchored["verified_through_checkpoint"]
    assert "checkpoint_missing" in anchored["errors"]


def test_checkpoint_does_not_claim_to_anchor_newer_tail(writer):
    append(writer)
    anchor = writer.checkpoint("demo-a")
    append(writer, event="query_completed")
    result = writer.verify("demo-a", anchor)
    assert result["verified_through_checkpoint"]
    assert result["unanchored_tail_events"] == 1
    assert result["completeness_unproven"]


def test_checkpoint_is_scoped_to_tenant_and_key(writer):
    append(writer)
    anchor = writer.checkpoint("demo-a")
    assert not writer.verify("demo-b", anchor)["verified_through_checkpoint"]
    other_key = AuditWriter(writer.db_path, b"b" * 32)
    result = other_key.verify("demo-a", anchor)
    assert not result["chain_valid"]
    assert not result["verified_through_checkpoint"]


def test_tenants_have_separate_chains_and_read_views(writer):
    append(writer, tenant="demo-a")
    append(writer, tenant="demo-b")
    assert [event["sequence"] for event in writer.events("demo-a")] == [1]
    assert {event["tenant_id"] for event in writer.events("demo-a")} == {"demo-a"}
    assert writer.verify("demo-b")["chain_valid"]


def test_concurrent_appends_cannot_fork_tenant_chain(writer):
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda number: append(writer, f"request-{number}"), range(40)))
    assert len(set(ids)) == 40
    assert [event["sequence"] for event in writer.events("demo-a")] == list(range(1, 41))
    assert writer.verify("demo-a")["chain_valid"]


def test_attempt_remains_incomplete_until_durable_terminal_outcome(writer):
    append(writer, "unfinished")
    append(writer, "finished")
    append(writer, "finished", "query_failed")
    assert writer.verify("demo-a")["incomplete_requests"] == ["unfinished"]


def test_audit_store_failure_raises_controlled_error(writer):
    alter(writer, "DROP TABLE audit_events")
    with pytest.raises(AuditError, match="Audit persistence unavailable"):
        append(writer)


@pytest.mark.parametrize(
    "metadata", [{"answer": "private body"}, {"prompt": "secret"}, {"status": float("nan")}]
)
def test_body_fields_and_nonfinite_values_are_rejected(writer, metadata):
    with pytest.raises(AuditError):
        writer.append("demo-a", "employee", "req", "query_attempt", metadata)


def test_invalid_limits_and_short_keys_fail_closed(writer):
    with pytest.raises(AuditError):
        writer.events("demo-a", limit=100000)
    with pytest.raises(AuditError):
        AuditWriter(writer.db_path, b"short")


def test_initialization_is_idempotent(writer):
    event_id = append(writer)
    writer.initialize()
    assert writer.events("demo-a")[0]["event_id"] == event_id


def test_external_transaction_rolls_back_audit_and_controlled_change_together(writer):
    with closing(sqlite3.connect(writer.db_path)) as db, db:
        db.execute("CREATE TABLE controlled_state (value TEXT)")
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO controlled_state VALUES ('changed')")
        writer.append_in_transaction(
            db, "demo-a", "admin", "request-1", "metadata_change", {"operation": "revoke"}
        )
        db.rollback()
        assert db.execute("SELECT COUNT(*) FROM controlled_state").fetchone()[0] == 0
    assert writer.events("demo-a") == []


def test_external_transaction_requires_explicit_transaction(writer):
    with closing(sqlite3.connect(writer.db_path)) as db, db:
        with pytest.raises(AuditError, match="active write transaction"):
            writer.append_in_transaction(db, "demo-a", "admin", "request-1", "metadata_change", {})


def test_changed_key_cannot_extend_existing_chain(writer):
    append(writer)
    other = AuditWriter(writer.db_path, b"b" * 32)
    with pytest.raises(AuditError, match="key does not match"):
        append(other)
    assert len(writer.events("demo-a")) == 1


def test_incompatible_schema_is_not_overwritten(writer):
    alter(writer, "UPDATE audit_meta SET value='99' WHERE name='schema_version'")
    with pytest.raises(AuditError, match="Incompatible audit schema"):
        writer.initialize()


@pytest.mark.parametrize("head", ["é" * 64, 123, "short"])
def test_malformed_checkpoint_is_controlled_integrity_failure(writer, head):
    append(writer)
    anchor = writer.checkpoint("demo-a") | {"head_hmac": head}
    assert not writer.verify("demo-a", anchor)["verified_through_checkpoint"]


def test_response_digest_is_keyed_and_domain_separated(writer):
    payload = b'{"answer":"protected response"}'
    expected = hmac.new(
        b"a" * 32, b"aspire-brain:response-digest:v1\x00" + payload, hashlib.sha256
    ).hexdigest()
    assert writer.response_digest(payload) == expected
    assert writer.response_digest(payload) != hashlib.sha256(payload).hexdigest()
    assert writer.response_digest(payload) != writer.response_digest(payload + b" ")
    assert not hasattr(writer, "key")


def test_response_digest_requires_bounded_bytes(writer):
    with pytest.raises(AuditError):
        writer.response_digest("not bytes")
    with pytest.raises(AuditError):
        writer.response_digest(b"x" * 1_048_577)


def test_request_trace_filter_is_tenant_scoped_and_precedes_pagination(writer):
    append(writer, "other-request")
    append(writer, "selected")
    append(writer, "selected", "query_completed")
    append(writer, "selected", tenant="demo-b")
    selected = writer.events("demo-a", limit=1, offset=1, request_id="selected")
    assert len(selected) == 1
    assert selected[0]["event_type"] == "query_completed"
    assert selected[0]["tenant_id"] == "demo-a"
    assert writer.events("demo-a", request_id="missing") == []
    with pytest.raises(AuditError):
        writer.events("demo-a", request_id="' OR 1=1 --")
