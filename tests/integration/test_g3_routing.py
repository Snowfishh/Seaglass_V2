"""G3 question-driven platform routing.

Routing decides which of Confluence, Jira, Slack and Drive a question touches, instead of
requiring a caller-supplied platform tuple. It must stay conservative: an ambiguous or broad
question includes plausible sources, and a keyword miss is never treated as proof that a
platform is irrelevant.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.routing import (
    PLATFORMS,
    explicit_override_decision,
    route_question,
)
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)


def source(platform, source_id, kind, parent, text, thread=None, event=None):
    return SimulatedSource(
        platform=platform, tenant_id="demo-a", source_id=source_id, source_kind=kind,
        version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://{platform}/{source_id}", parent_id=parent, thread_id=thread,
        source_updated_at="2026-09-27T07:55:00Z", event_at=event,
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g3r.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g3-routing-audit-key-separate-123456")
    audit.initialize()
    auth = AuthService(db)
    records = [
        source("confluence", "RUNBOOK-1", "space_page", "OPS",
               "Payment incident runbook: enable failover step before restart."),
        source("jira", "OPS-17", "issue", "OPS",
               "Database migration project status: in progress. P17 incident response requires "
               "finance sign-off."),
        source("slack", "msg-17", "thread_message", "p17-ops",
               "Database migration blocker raised in Slack: connection pool limit. P17 incident "
               "response confirmed.", "thread-17"),
        source("drive", "postmortem-1", "folder_file", "ops-docs",
               "P17 incident response postmortem: root cause was configuration drift."),
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
        last_successful_sync={p: NOW for p in PLATFORMS},
        freshness_budget_seconds={p: 3600 for p in PLATFORMS},
    )
    return auth, audit, state


# --- Router decisions ---

def test_runbook_question_routes_to_confluence():
    decision = route_question("What is the latest runbook for the payment-service incident?")
    assert decision["selected_platforms"] == ["confluence"]
    assert decision["basis"] in {"keyword_signals", "explicit_platform_mention"}
    assert "confluence" in decision["signals"]
    assert "jira" in decision["omitted_platforms"]


def test_migration_question_routes_to_jira_and_slack():
    decision = route_question(
        "What is the status of the database migration project and were there any blockers "
        "raised in Slack last week?")
    assert set(decision["selected_platforms"]) == {"jira", "slack"}
    assert decision["basis"] == "keyword_signals"
    assert set(decision["omitted_platforms"]) == {"confluence", "drive"}


def test_explicit_platform_mention_is_routed():
    decision = route_question("Summarise the Slack thread about the rollout.")
    assert "slack" in decision["selected_platforms"]
    assert "slack" in decision["explicit_platforms"]


def test_ticket_identifier_routes_to_jira():
    decision = route_question("What is the status of MIGRATE-42?")
    assert "jira" in decision["selected_platforms"]


def test_broad_question_includes_all_platforms():
    decision = route_question("Summarize everything about the payment outage across platforms.")
    assert set(decision["selected_platforms"]) == set(PLATFORMS)
    assert decision["basis"] == "broad_default_all"
    assert decision["omitted_platforms"] == []


def test_question_without_signals_defaults_to_all_platforms():
    decision = route_question("Tell me about the thing that happened.")
    assert set(decision["selected_platforms"]) == set(PLATFORMS)
    assert decision["basis"] == "no_signal_default_all"


def test_keyword_routing_records_omitted_coverage_rather_than_completeness():
    decision = route_question("What is the latest runbook for the payment-service incident?")
    # A keyword miss must not be presented as evidence that a platform is irrelevant.
    assert decision["omitted_platforms"]
    assert "not" in decision["coverage_note"].lower()
    assert "absence" in decision["coverage_note"].lower() or \
        "evidence" in decision["coverage_note"].lower()


def test_explicit_override_decision_is_labelled():
    decision = explicit_override_decision(("confluence",))
    assert decision["mode"] == "explicit_override"
    assert decision["basis"] == "explicit_override"
    assert decision["selected_platforms"] == ["confluence"]
    assert set(decision["omitted_platforms"]) == {"jira", "slack", "drive"}


# --- Service integration ---

def test_service_routes_from_question_when_no_override(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query(
        "employee", "What is the latest runbook for the payment-service incident?", NOW))
    assert packet["routing"]["mode"] == "question_driven"
    assert packet["routing"]["selected_platforms"] == ["confluence"]
    assert packet["required_platforms"] == ["confluence"]
    assert packet["query_status"] == "answered"
    assert {c["platform"] for c in packet["citations"]} == {"confluence"}


def test_service_override_is_recorded_in_the_packet(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=("jira", "slack"),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query(
        "employee", "What does the P17 incident response require?", NOW))
    assert packet["routing"]["mode"] == "explicit_override"
    assert packet["routing"]["basis"] == "explicit_override"
    assert packet["required_platforms"] == ["jira", "slack"]


def test_routed_answer_never_cites_a_platform_outside_the_routing(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query(
        "employee", "What is the status of the database migration project and were there any "
                    "blockers raised in Slack last week?", NOW))
    cited = {c["platform"] for c in packet["citations"]}
    assert cited <= set(packet["routing"]["selected_platforms"])


def test_case_1_question_routes_to_jira_and_slack():
    from aspire_brain.web.cases import CASE_1_QUERY
    decision = route_question(CASE_1_QUERY)
    assert set(decision["selected_platforms"]) == {"jira", "slack"}


# --- Browser route ---

def test_case_1_browser_route_shows_routing_and_time_scope(tmp_path):
    import secrets

    from fastapi.testclient import TestClient

    from aspire_brain.config import Settings
    from aspire_brain.main import create_app

    settings = Settings(db_path=tmp_path / "g3r-cases.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)

    def headers(client):
        session = client.get("/api/session").json()
        return {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}

    with TestClient(create_app(settings), base_url="http://localhost",
                    client=("127.0.0.1", 50000)) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=headers(client)).status_code == 200
        response = client.post("/api/cases/case_1", headers=headers(client))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["packet"]["routing"]["mode"] == "question_driven"
        assert set(body["packet"]["routing"]["selected_platforms"]) == {"jira", "slack"}
        assert body["packet"]["routing"]["omitted_platforms"] == ["confluence", "drive"]
        assert body["time_scope"]["applied"] is True
        assert body["time_scope"]["platforms"]["slack"]["basis"] == "event_at"
        assert "not time-filtered" in body["time_scope_note"]
        assert {c["platform"] for c in body["packet"]["citations"]} == {"jira", "slack"}
