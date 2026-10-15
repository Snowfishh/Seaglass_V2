"""Behavioral four-platform tests: Confluence, Jira, Slack, Drive."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
    SourceFailure,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
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
        source_updated_at="2026-09-27T07:55:00Z",
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
        source("confluence", "RUNBOOK-1", "space_page", "OPS",
               "P17 incident response runbook: enable failover step before restart."),
        source("confluence", "SECRET-1", "space_page_restricted", "SEC",
               "Q3 breach incident report " + SENTINEL),
        source("jira", "OPS-17", "issue", "OPS", "P17 incident response requires finance sign-off."),
        source("slack", "msg-17", "thread_message", "p17-ops",
               "P17 incident response owner confirmed finance sign-off in the runbook.", "thread-17"),
        source("drive", "postmortem-1", "folder_file", "ops-docs",
               "P17 incident response postmortem: root cause was configuration drift."),
        source("drive", "secret-doc", "folder_file_restricted", "sec-docs",
               "Restricted security document " + SENTINEL),
    ]
    state = SimulatedPlatformState(
        records=records,
        principal_map={"employee": {"confluence": "conf-employee", "jira": "jira-employee",
                                     "slack": "slack-employee", "drive": "drive-employee"}},
        confluence_space_grants={"OPS": {"conf-employee"}},
        confluence_page_grants={"RUNBOOK-1": {"conf-employee"}},
        jira_project_grants={"OPS": {"jira-employee"}},
        jira_issue_grants={"OPS-17": {"jira-employee"}},
        slack_channel_grants={"p17-ops": {"slack-employee"}},
        slack_thread_grants={"thread-17": {"slack-employee"}},
        slack_dm_grants={},
        drive_folder_grants={"ops-docs": {"drive-employee"}},
        drive_file_grants={"postmortem-1": {"drive-employee"}},
        last_successful_sync={"confluence": NOW, "jira": NOW, "slack": NOW, "drive": NOW},
        freshness_budget_seconds={"confluence": 3600, "jira": 3600, "slack": 3600, "drive": 3600},
    )
    return auth, audit, state


def run(service, principal="employee"):
    return asyncio.run(service.query(principal, "What does the P17 incident response require?", NOW))


# --- Confluence behavioral tests ---

def test_confluence_permitted_answer_cites_source(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "answered"
    assert {citation["platform"] for citation in packet["citations"]} == {"confluence"}
    assert all(citation["content_sha256"] and citation["locator"]
               for citation in packet["citations"])
    assert SENTINEL not in json.dumps(packet)


def test_confluence_space_grant_required(system):
    auth, audit, state = system
    state.set_confluence_space_grant("OPS", "conf-employee", False)
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert SENTINEL not in json.dumps(packet)


def test_confluence_page_grant_required(system):
    auth, audit, state = system
    state.set_confluence_page_grant("RUNBOOK-1", "conf-employee", False)
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert SENTINEL not in json.dumps(packet)


def test_confluence_restricted_report_denied_without_existence_disclosure(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence",),
                                    clock=lambda: NOW)
    # Employee has no access to SEC space or SECRET-1 page
    packet = run(service)
    assert SENTINEL not in json.dumps(packet)
    # The restricted page should not be cited or mentioned
    assert all(citation["source_id"] != "SECRET-1" for citation in packet["citations"])


# --- Drive behavioral tests ---

def test_drive_permitted_answer_cites_source(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("drive",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "answered"
    assert {citation["platform"] for citation in packet["citations"]} == {"drive"}
    assert all(citation["content_sha256"] and citation["locator"]
               for citation in packet["citations"])
    assert SENTINEL not in json.dumps(packet)


def test_drive_folder_grant_required(system):
    auth, audit, state = system
    state.set_drive_folder_grant("ops-docs", "drive-employee", False)
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("drive",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert SENTINEL not in json.dumps(packet)


def test_drive_file_grant_required(system):
    auth, audit, state = system
    state.set_drive_file_grant("postmortem-1", "drive-employee", False)
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("drive",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert SENTINEL not in json.dumps(packet)


def test_drive_restricted_file_denied_without_existence_disclosure(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("drive",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert SENTINEL not in json.dumps(packet)
    assert all(citation["source_id"] != "secret-doc" for citation in packet["citations"])


# --- Cross-platform four-platform tests ---

def test_four_platform_query_cites_all_permitted_sources(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence", "jira", "slack", "drive"),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "answered"
    platforms = {citation["platform"] for citation in packet["citations"]}
    assert platforms == {"confluence", "jira", "slack", "drive"}
    assert SENTINEL not in json.dumps(packet)


def test_four_platform_partial_when_one_fails(system):
    auth, audit, state = system
    state.set_failure("confluence", SourceFailure(category="unavailable"))
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence", "jira", "slack", "drive"),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "partial"
    assert "confluence" in packet["incomplete_platforms"]
    assert {citation["platform"] for citation in packet["citations"]} <= {"jira", "slack", "drive"}
    assert "incomplete" in packet["answer"].lower()


def test_four_platform_abstained_when_all_fail(system):
    auth, audit, state = system
    for platform in ("confluence", "jira", "slack", "drive"):
        state.set_failure(platform, SourceFailure(category="timeout"))
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence", "jira", "slack", "drive"),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []


# --- Revocation tests for new platforms ---

def test_confluence_revocation_blocks_new_query_and_saved_packet(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence",),
                                    clock=lambda: NOW)
    packet = run(service)
    state.set_confluence_page_grant("RUNBOOK-1", "conf-employee", False)
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])
    after = run(service)
    assert after["query_status"] == "abstained"
    assert after["citations"] == []


def test_drive_revocation_blocks_new_query_and_saved_packet(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("drive",),
                                    clock=lambda: NOW)
    packet = run(service)
    state.set_drive_file_grant("postmortem-1", "drive-employee", False)
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])
    after = run(service)
    assert after["query_status"] == "abstained"
    assert after["citations"] == []


# --- Stale source tests for new platforms ---

def test_confluence_stale_required_platform_is_explicit(system):
    auth, audit, state = system
    state.set_last_successful_sync("confluence", datetime(2026, 9, 27, 5, 0, tzinfo=UTC))
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] != "answered"
    assert packet["source_status"]["confluence"]["freshness_state"] == "stale"


def test_drive_stale_required_platform_is_explicit(system):
    auth, audit, state = system
    state.set_last_successful_sync("drive", datetime(2026, 9, 27, 5, 0, tzinfo=UTC))
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("drive",),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] != "answered"
    assert packet["source_status"]["drive"]["freshness_state"] == "stale"


# --- Integrity and collision tests ---

def test_same_version_id_across_four_platforms_keeps_distinct_citations(system):
    auth, audit, state = system
    state.records = {
        key: record.model_copy(update={"version_id": "v1"})
        for key, record in state.records.items()
    }
    service = SimulatedQueryService(auth, audit, state,
                                    required_platforms=("confluence", "jira", "slack", "drive"),
                                    clock=lambda: NOW)
    packet = run(service)
    assert packet["query_status"] == "answered"
    assert {item["platform"] for item in packet["citations"]} == {"confluence", "jira", "slack", "drive"}
    assert len(packet["citations"]) == 4


def test_confluence_hash_mismatch_rejected():
    with pytest.raises(ValueError):
        SimulatedSource(
            platform="confluence", tenant_id="demo-a", source_id="PAGE-1",
            source_kind="space_page", version_id="PAGE-1:v1",
            content_sha256="0" * 64, text="different",
            locator="simulated://confluence/PAGE-1", parent_id="SPACE",
            thread_id=None, source_updated_at="2026-09-27T07:55:00Z",
        )


def test_drive_hash_mismatch_rejected():
    with pytest.raises(ValueError):
        SimulatedSource(
            platform="drive", tenant_id="demo-a", source_id="FILE-1",
            source_kind="folder_file", version_id="FILE-1:v1",
            content_sha256="0" * 64, text="different",
            locator="simulated://drive/FILE-1", parent_id="FOLDER",
            thread_id=None, source_updated_at="2026-09-27T07:55:00Z",
        )


def test_cross_tenant_principal_denied_for_all_four_platforms(system):
    auth, _, state = system
    principal = auth.principal("other_tenant")
    for platform in ("confluence", "jira", "slack", "drive"):
        assert not state.can_read(principal, platform, "RUNBOOK-1")
        assert not state.can_read(principal, platform, "OPS-17")
        assert not state.can_read(principal, platform, "msg-17")
        assert not state.can_read(principal, platform, "postmortem-1")
