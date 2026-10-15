"""Typed questions across the fictional fintech fixture, behind the signed local identity."""

import asyncio
import json
import secrets
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.config import Settings
from aspire_brain.db import Database
from aspire_brain.main import create_app
from aspire_brain.platforms.connectors.offline import load_fixture_index
from aspire_brain.platforms.routing import detect_time_window
from aspire_brain.platforms.simulated import ALL_PLATFORMS, SimulatedQueryService
from aspire_brain.web.cases import FINTECH_FIXTURE_ROOT, FINTECH_NOW

ROOT = Path(__file__).resolve().parents[2]
ORACLE = {r["id"]: r for r in json.loads(
    (FINTECH_FIXTURE_ROOT / "expected-outcomes.json").read_text())["assertions"]}
HANDOVER = "How many supplier payments need manual review in the 09:30 handover?"
RESTRICTED = ("conf-restricted-case", "drive-restricted-invoice")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Typed fixture query attempted network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=tmp_path / "typed.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)
    with TestClient(create_app(settings), base_url="http://localhost",
                    client=("127.0.0.1", 50000)) as test_client:
        test_client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                      ROOT / "data/demo/principals.json")
        yield test_client


def headers(client):
    session = client.get("/api/session").json()
    return {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}


def ask(client, question, persona=None):
    if persona:
        assert client.post("/api/demo/session", json={"user_id": persona},
                           headers=headers(client)).status_code == 200
    return client.post("/api/four-platform/queries", json={"question": question},
                       headers=headers(client))


def cited(result):
    return {citation["source_id"] for citation in result["packet"]["citations"]}


def test_fintech_personas_are_offered_in_demo_mode(client):
    personas = client.get("/api/session").json()["personas"]
    assert {"user-a", "user-b"} <= set(personas)


def test_typed_question_requires_persona_csrf_and_a_valid_body(client):
    assert client.post("/api/four-platform/queries",
                       json={"question": HANDOVER}).status_code == 403
    assert ask(client, HANDOVER).status_code == 401
    assert ask(client, "   ", persona="user-b").status_code == 422
    assert client.post("/api/four-platform/queries",
                       json={"question": HANDOVER, "principal": "user-a"},
                       headers=headers(client)).status_code == 422
    response = ask(client, "What changed in the last 900 days?")
    assert response.status_code == 422
    assert response.json()["detail"] == "Time window must be between 1 and 365 days"


def test_a_rejected_time_window_is_audited(client):
    assert ask(client, "What changed in the last 900 days?", persona="user-b").status_code == 422
    events = client.app.state.audit.events("fintech-demo", limit=1000)
    rejected = [event for event in events if event["event_type"] == "query_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["principal_id"] == "user-b"
    assert rejected[0]["metadata"] == {"error_code": "invalid_time_window"}
    attempts = [event for event in events if event["event_type"] == "query_attempt"
                and event["request_id"] == rejected[0]["request_id"]]
    assert len(attempts) == 1


def test_typed_question_uses_routing_fixture_clock_and_offline_provider(client):
    response = ask(client, HANDOVER, persona="user-b")
    assert response.status_code == 200, response.text
    result = response.json()
    packet = result["packet"]
    assert result["query"] == HANDOVER
    assert result["principal"] == "user-b"
    assert packet["routing"]["mode"] == "question_driven"
    assert result["platforms"] == packet["searched_platforms"] == list(ALL_PLATFORMS)
    assert packet["provider_mode"] == "offline_extractive"
    assert "offline_extractive" in result["provider_note"]
    assert {status["last_successful_sync"] for status in packet["source_status"].values()} == {
        FINTECH_NOW.isoformat()}
    assert {status["freshness_state"] for status in packet["source_status"].values()} == {"fresh"}
    assert "three require manual review" in packet["answer"]
    assert "conf-morning-handover" in cited(result)


def test_same_question_differs_only_by_permitted_sources(client):
    question = ORACLE["allowed_case"]["question"]
    allowed = ask(client, question, persona="user-a").json()
    assert set(ORACLE["allowed_case"]["required_source_ids"]) <= cited(allowed)
    assert "beneficiary account details were changed" in allowed["packet"]["answer"]

    denied = ask(client, question, persona="user-b")
    assert denied.status_code == 200
    body = denied.text
    for source_id in RESTRICTED:
        assert source_id not in body
    for text in ORACLE["denied_case"]["forbidden_disclosures"]:
        if text != "Cedar Quay":  # the question itself names the supplier
            assert text not in body


def test_denied_case_question_discloses_nothing_restricted(client):
    case = ORACLE["denied_case"]
    response = ask(client, case["question"], persona=case["principal"])
    assert response.status_code == 200
    for text in (*case["denied_source_ids"], *case["forbidden_disclosures"]):
        assert text not in response.text


def test_personas_outside_the_fixture_tenant_abstain(client):
    result = ask(client, HANDOVER, persona="employee").json()
    assert result["packet"]["query_status"] == "abstained"
    assert result["packet"]["citations"] == []


def test_relative_dates_scope_slack_by_event_time_on_the_fixture_clock(client):
    today = ask(client, "What progress was posted in Slack today?", persona="user-b").json()
    assert today["packet"]["routing"]["selected_platforms"] == ["slack"]
    assert today["time_scope"]["applied"] is True
    end = datetime.fromisoformat(today["time_scope"]["platforms"]["slack"]["end"])
    # The fixture clock starts at FINTECH_NOW and then runs in real time.
    assert timedelta(0) <= end - FINTECH_NOW < timedelta(minutes=5)
    assert "fixture clock" in today["time_scope_note"]
    assert today["packet"]["query_status"] == "answered"
    assert "slack-shift-root" in cited(today)

    yesterday = ask(client, "What progress was posted in Slack yesterday?").json()
    assert yesterday["packet"]["query_status"] == "abstained"
    assert yesterday["packet"]["citations"] == []

    undated = ask(client, HANDOVER).json()
    assert undated["time_scope"]["applied"] is False
    assert undated["time_scope_note"] is None


# --- Default-all routing: an empty platform marks the answer partial ---

@pytest.fixture
def service_parts(tmp_path):
    db = Database(tmp_path / "engine.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    return AuthService(db), audit


def run(service, principal, question):
    return asyncio.run(service.query(principal, question, FINTECH_NOW))


def test_no_signal_routing_answers_and_lists_platforms_without_relevant_evidence(service_parts):
    auth, audit = service_parts
    index = load_fixture_index(FINTECH_FIXTURE_ROOT, now=FINTECH_NOW)
    service = SimulatedQueryService(auth, audit, index, required_platforms=None,
                                    clock=lambda: FINTECH_NOW)
    packet = run(service, "user-b", HANDOVER)
    assert packet["routing"]["basis"] == "no_signal_default_all"
    # Every platform was searched as a precaution; one with nothing relevant is reported, but
    # it does not make an answered question incomplete.
    assert packet["query_status"] == "answered"
    assert packet["incomplete_platforms"] == []
    assert "drive" in packet["answer_focus"]["platforms_without_relevant_evidence"]
    assert packet["retrieval"]["platforms"]["drive"]["candidates_after_scope"] == 0
    assert all(citation["platform"] != "drive" for citation in packet["citations"])
    assert "three require manual review" in packet["answer"]


def test_explicit_four_platform_requirement_still_abstains_on_a_missing_platform(service_parts):
    auth, audit = service_parts
    index = load_fixture_index(FINTECH_FIXTURE_ROOT, now=FINTECH_NOW)
    service = SimulatedQueryService(auth, audit, index, required_platforms=ALL_PLATFORMS,
                                    clock=lambda: FINTECH_NOW)
    packet = run(service, "user-b", HANDOVER)
    assert packet["routing"]["basis"] == "explicit_override"
    assert packet["query_status"] == "abstained"
    assert packet["incomplete_platforms"] == ["drive"]
    assert packet["citations"] == []


def test_signal_routed_platform_without_a_match_makes_the_answer_partial(service_parts):
    auth, audit = service_parts
    index = load_fixture_index(FINTECH_FIXTURE_ROOT, now=FINTECH_NOW)
    service = SimulatedQueryService(auth, audit, index, required_platforms=None,
                                    clock=lambda: FINTECH_NOW)
    question = "What is the status of the processing payments ticket and the Slack blockers?"
    yesterday = detect_time_window("yesterday", FINTECH_NOW)
    packet = asyncio.run(service.query("user-b", question, FINTECH_NOW,
                                       time_windows={"slack": yesterday}))
    assert packet["routing"]["basis"] in {"keyword_signals", "explicit_platform_mention"}
    assert packet["routing"]["selected_platforms"] == ["jira", "slack"]
    assert packet["retrieval"]["platforms"]["jira"]["candidates_after_scope"] > 0
    assert packet["retrieval"]["platforms"]["slack"]["candidates_after_scope"] == 0
    # Slack was asked about and has nothing permitted in the window: the answer says so.
    assert packet["query_status"] == "partial"
    assert "slack" in packet["incomplete_platforms"]
    assert all(citation["platform"] != "slack" for citation in packet["citations"])


# --- Sources, Policy history and Audit trail for the fintech tenant ---

def test_fintech_lookups_offer_only_records_the_persona_can_read(client):
    suggestions = {}
    for persona in ("user-a", "user-b"):
        assert client.post("/api/demo/session", json={"user_id": persona},
                           headers=headers(client)).status_code == 200
        response = client.get("/api/lookup-suggestions")
        assert response.status_code == 200, response.text
        suggestions[persona] = response.json()
    a_docs, b_docs = set(suggestions["user-a"]["documents"]), set(suggestions["user-b"]["documents"])
    assert set(RESTRICTED) <= a_docs
    assert not set(RESTRICTED) & b_docs
    assert b_docs < a_docs
    assert {"conf-payment-runbook@1.0", "jira-status-delay@1"} <= {
        source["version_id"] for source in suggestions["user-b"]["sources"]}
    assert not any(text in json.dumps(suggestions["user-b"])
                   for text in ORACLE["denied_case"]["forbidden_disclosures"])


def test_fintech_source_and_history_follow_platform_permissions(client):
    client.post("/api/demo/session", json={"user_id": "user-b"}, headers=headers(client))
    source = client.get("/api/sources/conf-morning-handover@1/conf-morning-handover")
    assert source.status_code == 200, source.text
    assert "three require manual review" in source.json()["text"]
    assert source.json()["document_id"] == "conf-morning-handover"
    for denied in ("/api/sources/conf-restricted-case@1/conf-restricted-case",
                   "/api/sources/conf-morning-handover@1/conf-payment-runbook",
                   "/api/policies/conf-restricted-case/versions"):
        response = client.get(denied)
        assert response.status_code == 404
        assert response.json() == {"detail": "Evidence unavailable"}
    history = client.get("/api/policies/conf-payment-runbook/versions").json()
    assert [version["id"] for version in history] == ["conf-payment-runbook@1.0"]
    assert history[0]["state"] == "synced" and history[0]["platform"] == "confluence"

    client.post("/api/demo/session", json={"user_id": "user-a"}, headers=headers(client))
    restricted = client.get("/api/sources/conf-restricted-case@1/conf-restricted-case")
    assert restricted.status_code == 200
    assert "Cedar Quay" in restricted.json()["text"]


def test_a_grant_removed_upstream_closes_sources_and_history_before_the_next_sync(client):
    source = "/api/sources/conf-restricted-case@1/conf-restricted-case"
    history = "/api/policies/conf-restricted-case/versions"
    client.post("/api/demo/session", json={"user_id": "user-a"}, headers=headers(client))
    assert client.get(source).status_code == 200
    assert client.get(history).status_code == 200

    client.post("/api/demo/session", json={"user_id": "fintech_admin"}, headers=headers(client))
    change = client.post("/api/four-platform/upstream-changes",
                         json={"action": "revoke_restricted", "principal_id": "user-a"},
                         headers=headers(client))
    assert change.status_code == 200 and "conf-restricted-case" in change.json()["changed"]

    # No sync has run, so the index still grants user-a; the source platform no longer does.
    client.post("/api/demo/session", json={"user_id": "user-a"}, headers=headers(client))
    for path in (source, history):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Evidence unavailable"}
        assert "Cedar Quay" not in response.text
    assert client.get("/api/sources/conf-morning-handover@1/conf-morning-handover").status_code == 200


def test_fintech_auditor_traces_fintech_requests_but_reads_no_content(client):
    request_id = ask(client, HANDOVER, persona="user-a").json()["packet"]["request_id"]
    client.post("/api/demo/session", json={"user_id": "fintech_auditor"}, headers=headers(client))
    events = client.get("/api/audit/events?limit=100&newest_first=true").json()["events"]
    assert request_id in {event["request_id"] for event in events}
    assert {event["principal_id"] for event in events} >= {"user-a"}
    traced = client.get(f"/api/audit/events?request_id={request_id}").json()["events"]
    assert {event["event_type"] for event in traced} >= {"query_attempt", "query_completed"}
    assert client.get("/api/lookup-suggestions").json() == {"documents": [], "sources": []}
    assert client.get("/api/sources/conf-morning-handover@1/conf-morning-handover").status_code == 404
