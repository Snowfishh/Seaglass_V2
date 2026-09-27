"""Behavioral G1 tests against a labelled local Jira/Slack simulation."""

import asyncio
import hashlib
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aspire_brain.answers import QueryError
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
    SourceFailure,
)
from aspire_brain.providers import OfflineExtractiveProvider

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
SENTINEL = "FORBIDDEN_PLATFORM_SENTINEL"


def source(platform, source_id, kind, parent, text, thread=None):
    return SimulatedSource(
        platform=platform,
        tenant_id="demo-a",
        source_id=source_id,
        source_kind=kind,
        version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        locator=f"simulated://{platform}/{source_id}",
        parent_id=parent,
        thread_id=thread,
        source_updated_at="2026-09-25T07:55:00Z",
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g1.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g1-test-audit-key-is-separate-12345")
    audit.initialize()
    auth = AuthService(db)
    records = [
        source("jira", "OPS-17", "issue", "OPS", "P17 incident response requires finance sign-off."),
        source("slack", "msg-17", "thread_message", "p17-ops",
               "P17 incident response owner confirmed finance sign-off in the runbook.", "thread-17"),
        source("jira", "OPS-SECRET", "issue", "OPS", "P17 incident response " + SENTINEL),
        source("slack", "msg-secret", "dm", "dm-secret", "P17 incident response " + SENTINEL),
    ]
    state = SimulatedPlatformState(
        records=records,
        principal_map={"employee": {"jira": "jira-employee", "slack": "slack-employee"}},
        jira_project_grants={"OPS": {"jira-employee"}},
        jira_issue_grants={"OPS-17": {"jira-employee"}},
        slack_channel_grants={"p17-ops": {"slack-employee"}},
        slack_thread_grants={"thread-17": {"slack-employee"}},
        slack_dm_grants={},
        last_successful_sync={"jira": NOW, "slack": NOW},
        freshness_budget_seconds={"jira": 3600, "slack": 3600},
    )
    return auth, audit, state


def run(service, principal="employee"):
    return asyncio.run(service.query(principal, "What does the P17 incident response require?", NOW))


def test_five_independent_case_expectations_are_labelled():
    cases = json.loads((ROOT / "eval/g1-case-expectations.json").read_text())
    assert cases["mode"] == "simulated"
    assert cases["scenario_details_inferred_from_report"] is False
    assert [case["id"] for case in cases["scenarios"]] == [
        "case_1_cross_platform_answer", "case_2_bounded_freshness",
        "case_3_restricted_report", "case_4_upstream_revocation",
        "case_5_officer_inquiry",
    ]
    assert cases["scenarios"][0]["expected_citation_platforms"] == ["jira", "slack"]


def test_permitted_answer_cites_both_sources_and_omits_forbidden_text(system):
    auth, audit, state = system
    seen = []

    class Spy(OfflineExtractiveProvider):
        async def generate(self, context):
            seen.append(context.model_dump_json())
            return await super().generate(context)

    service = SimulatedQueryService(auth, audit, state, provider=Spy(), clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "answered"
    assert packet["simulation_mode"] == "simulated"
    assert packet["provider_mode"] == "offline_extractive"
    assert {citation["platform"] for citation in packet["citations"]} == {"jira", "slack"}
    assert {citation["source_id"] for citation in packet["citations"]} == {"OPS-17", "msg-17"}
    assert all(citation["content_sha256"] and citation["locator"]
               for citation in packet["citations"])
    assert SENTINEL not in "".join(seen) + json.dumps(packet)
    assert service.packet("employee", packet["request_id"]) == packet
    assert audit.verify(auth.principal("employee")["tenant_id"])["chain_valid"]


@pytest.mark.parametrize("missing", ["jira_project", "jira_issue", "slack_channel", "slack_thread"])
def test_each_parent_or_child_grant_is_required(system, missing):
    auth, audit, state = system
    if missing == "jira_project":
        state.set_jira_project_grant("OPS", "jira-employee", False)
    elif missing == "jira_issue":
        state.set_jira_issue_grant("OPS-17", "jira-employee", False)
    elif missing == "slack_channel":
        state.set_slack_channel_grant("p17-ops", "slack-employee", False)
    else:
        state.set_slack_thread_grant("thread-17", "slack-employee", False)
    packet = run(SimulatedQueryService(auth, audit, state))
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert SENTINEL not in json.dumps(packet)


def test_dm_access_is_separate_and_incomplete_identity_denies(system):
    auth, _, state = system
    principal = auth.principal("employee")
    assert not state.can_read(principal, "slack", "msg-secret")
    state.set_slack_dm_grant("dm-secret", "slack-employee", True)
    assert state.can_read(principal, "slack", "msg-secret")
    state.set_principal_identity("employee", "slack", None)
    assert not state.can_read(principal, "slack", "msg-secret")
    assert not state.can_read(auth.principal("other_tenant"), "slack", "msg-secret")


def test_revocation_after_ingestion_blocks_new_query_and_saved_packet(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, clock=lambda: NOW)
    packet = run(service)
    state.set_slack_thread_grant("thread-17", "slack-employee", False)
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])
    after = run(service)
    assert after["query_status"] == "abstained"
    assert after["citations"] == []
    assert "confirmed" not in after["answer"]


def test_recheck_before_provider_input_aborts_racing_revocation(system, monkeypatch):
    auth, audit, state = system
    original = state.candidates

    def revoke_after_search(*args, **kwargs):
        found = original(*args, **kwargs)
        state.set_jira_issue_grant("OPS-17", "jira-employee", False)
        return found

    monkeypatch.setattr(state, "candidates", revoke_after_search)
    seen = []

    class Spy(OfflineExtractiveProvider):
        async def generate(self, context):
            seen.append(context)
            return await super().generate(context)

    with pytest.raises(AccessDenied):
        run(SimulatedQueryService(auth, audit, state, provider=Spy()))
    assert seen == []


def test_recheck_before_response_aborts_provider_time_revocation(system):
    auth, audit, state = system

    class Revoke(OfflineExtractiveProvider):
        async def generate(self, context):
            state.set_slack_thread_grant("thread-17", "slack-employee", False)
            return await super().generate(context)

    service = SimulatedQueryService(auth, audit, state, provider=Revoke())
    with pytest.raises(AccessDenied):
        run(service)
    assert audit.verify("demo-a")["chain_valid"]


def test_required_platform_failure_is_explicit_partial_or_abstaining(system):
    auth, audit, state = system
    state.set_failure("slack", SourceFailure(category="timeout"))
    packet = run(SimulatedQueryService(auth, audit, state))
    assert packet["query_status"] in {"partial", "abstained"}
    assert packet["query_status"] != "answered"
    assert packet["source_status"]["slack"]["freshness_state"] == "failed"
    assert packet["source_status"]["slack"]["source_failure"] == "timeout"
    assert "slack" in packet["incomplete_platforms"]
    assert {citation["platform"] for citation in packet["citations"]} <= {"jira"}
    assert "incomplete" in packet["answer"].lower()


def test_stale_required_platform_cannot_produce_complete_answer(system):
    auth, audit, state = system
    state.set_last_successful_sync("slack", datetime(2026, 9, 25, 5, 0, tzinfo=UTC))
    packet = run(SimulatedQueryService(auth, audit, state))
    assert packet["query_status"] != "answered"
    assert packet["source_status"]["slack"]["freshness_state"] == "stale"


def test_saved_packet_denied_when_platform_access_cannot_be_rechecked(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, clock=lambda: NOW)
    packet = run(service)
    state.set_failure("slack", SourceFailure(category="expired_access"))
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])


def test_source_update_after_last_sync_is_explicitly_incomplete(system):
    auth, audit, state = system
    original = state.records[("jira", "OPS-17")]
    state.records = {**state.records, ("jira", "OPS-17"):
                     original.model_copy(update={"source_updated_at":
                                                 datetime(2026, 9, 25, 8, 1, tzinfo=UTC)})}
    packet = run(SimulatedQueryService(auth, audit, state))
    assert packet["query_status"] != "answered"
    assert packet["source_status"]["jira"]["freshness_state"] == "stale"
    assert all(item["platform"] != "jira" for item in packet["citations"])


def test_source_hash_mismatch_rejected():
    with pytest.raises(ValueError):
        SimulatedSource(
            platform="jira", tenant_id="demo-a", source_id="OPS-1", source_kind="issue",
            version_id="OPS-1:v1", content_sha256="0" * 64, text="different",
            locator="simulated://jira/OPS-1", parent_id="OPS", thread_id=None,
            source_updated_at="2026-09-25T07:55:00Z",
        )


def test_same_version_id_on_two_platforms_keeps_distinct_citations(system):
    auth, audit, state = system
    state.records = {
        key: record.model_copy(update={"version_id": "v1"})
        for key, record in state.records.items()
    }
    packet = run(SimulatedQueryService(auth, audit, state))
    assert packet["query_status"] == "answered"
    assert {item["platform"] for item in packet["citations"]} == {"jira", "slack"}
    assert len(packet["citations"]) == 2


def test_changed_source_version_blocks_saved_packet(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, clock=lambda: NOW)
    packet = run(service)
    original = state.records[("jira", "OPS-17")]
    state.records = {**state.records, ("jira", "OPS-17"):
                     original.model_copy(update={"version_id": "OPS-17:v2"})}
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])


def test_saved_packet_denied_after_local_principal_is_disabled(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, clock=lambda: NOW)
    packet = run(service)
    auth.db.set_active("employee", False, audit)
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])


def test_saved_packet_denied_if_source_bytes_no_longer_match_hash(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, clock=lambda: NOW)
    packet = run(service)
    original = state.records[("jira", "OPS-17")]
    state.records = {**state.records, ("jira", "OPS-17"):
                     original.model_copy(update={"text": "tampered P17 content"})}
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])


def test_final_audit_failure_does_not_release_or_store_packet(system, monkeypatch):
    auth, audit, state = system
    original = audit.append_in_transaction

    def fail_completed(connection, tenant, principal, request_id, event_type, metadata):
        if event_type == "query_completed":
            raise OSError("test audit write failure")
        return original(connection, tenant, principal, request_id, event_type, metadata)

    monkeypatch.setattr(audit, "append_in_transaction", fail_completed)
    service = SimulatedQueryService(auth, audit, state)
    with pytest.raises(QueryError, match="Audit/packet persistence unavailable"):
        run(service)
    with closing(auth.db.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM simulated_packets").fetchone()[0] == 0
    assert audit.verify("demo-a")["chain_valid"]
