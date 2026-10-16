"""Behaviour added to close the submission gaps, exercised through the running application.

* Typed questions use the configured provider, quote only what answers the question and abstain
  when the permitted evidence does not cover it (the full fixture oracle is checked).
* The four-platform index is shared and kept fresh by a sync loop; a platform administrator's
  change reaches answers at the next sync, and a removed grant closes new and saved answers.
* The audit trail covers both query routes and stopped queries, can be searched by user or by
  document, and detects removal of its newest events through a separate witness.
"""

import asyncio
import json
import secrets
import socket
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from aspire_brain.answers import QueryError, QueryService
from aspire_brain.audit import AuditError, AuditWriter, ProtectedAuditStore
from aspire_brain.audit.retention import RetentionPolicy
from aspire_brain.audit.witness import AuditWitness
from aspire_brain.auth import AuthService
from aspire_brain.config import Settings
from aspire_brain.db import Database
from aspire_brain.main import create_app
from aspire_brain.models import QueryRequest
from aspire_brain.platforms import runtime as runtime_module
from aspire_brain.platforms.runtime import FixtureClock, fixture_runtime
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)
from aspire_brain.providers import OfflineExtractiveProvider
from aspire_brain.providers.grounded import GroundedAnswerProvider
from aspire_brain.providers.live import LiveGroundedProvider, SpendLedger, approved_live_config
from aspire_brain.web.cases import FINTECH_FIXTURE_ROOT, FINTECH_NOW

ROOT = Path(__file__).resolve().parents[2]
ORACLE = {row["id"]: row for row in json.loads(
    (FINTECH_FIXTURE_ROOT / "expected-outcomes.json").read_text())["assertions"]}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Gap-closure test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


class Ticker:
    """A monotonic clock the test advances by hand."""

    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def settings_for(tmp_path, **extra):
    return Settings(db_path=tmp_path / "gap.db", session_secret=secrets.token_hex(32),
                    audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                    demo_mode=True, **extra)


@pytest.fixture
def ticker():
    return Ticker()


@pytest.fixture
def app_client(tmp_path, ticker):
    def make(provider=None):
        runtime = fixture_runtime(FINTECH_FIXTURE_ROOT, start=FINTECH_NOW,
                                  sync_interval_seconds=0, monotonic=ticker)
        client = TestClient(create_app(settings_for(tmp_path), provider=provider,
                                       platform_runtime=runtime),
                            base_url="http://localhost", client=("127.0.0.1", 50000))
        return client, runtime
    return make


def headers(client):
    token = client.get("/api/session").json()["csrf_token"]
    return {"X-CSRF-Token": token, "Origin": "http://localhost"}


def login(client, persona):
    assert client.post("/api/demo/session", json={"user_id": persona},
                       headers=headers(client)).status_code == 200


def ask(client, question, persona=None):
    if persona:
        login(client, persona)
    response = client.post("/api/four-platform/queries", json={"question": question},
                           headers=headers(client))
    assert response.status_code == 200, response.text
    return response.json()


def cited(result):
    return {citation["source_id"] for citation in result["packet"]["citations"]}


def seeded(client):
    client.app.state.db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    return client


# -- useful, grounded answers: the fixture oracle ---------------------------------------------

@pytest.mark.parametrize("case_id", [key for key, row in ORACLE.items() if "question" in row])
def test_every_oracle_question_meets_its_expectation(app_client, case_id):
    client, _ = app_client()
    case = ORACLE[case_id]
    with client:
        seeded(client)
        result = ask(client, case["question"], persona=case["principal"])
    packet, answer = result["packet"], result["packet"]["answer"]
    assert packet["claim_support"]["all_supported"] is True
    if case_id == "morning_queue":
        assert set(case["required_source_ids"]) <= cited(result)
        for phrase in ("126 supplier-payment instructions", "118 are completed",
                       "three require manual review"):
            assert phrase in answer
    elif case_id == "allowed_case":
        assert set(case["required_source_ids"]) <= cited(result)
        assert "beneficiary account details were changed after the invoice" in answer
    elif case_id == "denied_case":
        body = json.dumps(result)
        for text in (*case["denied_source_ids"], *case["forbidden_disclosures"]):
            assert text not in body
    elif case_id == "unsupported_budget":
        assert packet["query_status"] == "abstained"
        assert packet["citations"] == []
        assert answer == ("The evidence you are permitted to read does not answer this "
                          "question; human review required.")
        assert packet["answer_focus"]["coverage"] < packet["answer_focus"]["threshold"]
    elif case_id == "amount_not_loss":
        assert "USD 12,480.00 is the payment amount, not a confirmed financial loss" in answer
        assert "The payment has not been released" in answer
    elif case_id == "fraud_not_established":
        assert "does not establish fraud or account compromise" in answer
        assert "The reason for the change remains unverified" in answer
    elif case_id == "cross_platform_status":
        # Every oracle source, on all four platforms, and the facts each one carries.
        assert set(case["required_source_ids"]) <= cited(result)
        assert {c["platform"] for c in packet["citations"]} == {"confluence", "jira", "slack",
                                                                 "drive"}
        assert f"Status: {case['expected_facts']['jira_status']}" in answer
        assert "partner references for two processing records" in answer
        assert "Three other processing records still lack a final partner reference" in answer
        assert "root cause remains unconfirmed" in answer
        # Next actions: callback logs, the two-record status comparison, the three missing
        # references (stated as the gap the next action closes).
        assert "checking the callback logs" in answer
        assert "need the internal status comparison" in answer
        assert case["must_not_claim"] not in answer
        assert packet["query_status"] == "answered"
    assert packet["query_status"] in {"answered", "partial", "abstained"}


def test_answers_are_short_and_quote_only_relevant_passages(app_client):
    client, _ = app_client()
    with client:
        seeded(client)
        result = ask(client, ORACLE["morning_queue"]["question"], persona="user-b")
    # The old answer quoted every permitted document in full (over 8,000 characters).
    assert len(result["packet"]["answer"]) < 1500
    assert "Customer communication" not in result["packet"]["answer"]


def test_the_same_question_without_permitted_coverage_abstains_identically(app_client):
    client, _ = app_client()
    with client:
        seeded(client)
        login(client, "user-b")
        held = ask(client, "Why is Cedar Quay's payment held?")["packet"]
        invented = ask(client, "Why is Zebra Harbour's payment held?")["packet"]
    for packet in (held, invented):
        assert packet["query_status"] == "abstained" and packet["citations"] == []
    assert held["answer"] == invented["answer"]
    assert held["incomplete_platforms"] == invented["incomplete_platforms"]


# -- the configured provider answers typed questions -----------------------------------------

def test_typed_questions_use_the_configured_local_provider(app_client):
    client, _ = app_client(provider=GroundedAnswerProvider())
    with client:
        seeded(client)
        result = ask(client, ORACLE["morning_queue"]["question"], persona="user-b")
    assert result["packet"]["provider_mode"] == "fake_grounded"
    assert result["packet"]["claim_support"]["all_supported"] is True
    assert "three require manual review" in result["packet"]["answer"]


def test_typed_questions_use_the_configured_live_model_without_restricted_sources(app_client, tmp_path):
    seen = []

    def groq(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "req_1", "model": approved_live_config().model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"answerable": True,
                                                            "sentence_ids": ["S1"]})}}],
            "usage": {"prompt_tokens": 400, "completion_tokens": 50,
                      "completion_tokens_details": {"reasoning_tokens": 10}}})
    live = LiveGroundedProvider(approved_live_config(), credential="gsk_" + secrets.token_hex(16),
                                ledger=SpendLedger(tmp_path / "ledger.jsonl"),
                                transport=httpx.MockTransport(groq))
    client, _ = app_client(provider=live)
    with client:
        seeded(client)
        result = ask(client, "Why is Cedar Quay's payment held?", persona="user-a")
    assert result["packet"]["provider_mode"] == "live_grounded"
    assert result["packet"]["provider_runtime"]["live_request_made"] is True
    assert "live model" in result["provider_note"]
    sent = json.dumps(seen)
    for restricted in ("12,480", "DEMO-4408", "Harbourline", "EXC-DEMO-7429"):
        assert restricted not in sent
    assert not {"conf-restricted-case", "drive-restricted-invoice"} & cited(result)
    # Restricted records take no share of the live input bound, and the evidence is sized by
    # the request the provider actually sends, so it is never refused for being too large.
    assert all(len(json.dumps(body, ensure_ascii=False).encode()) < 4000 for body in seen)
    # Before, the restricted records used up the bound and this message was left out.
    assert "Morning handover is available for OPS-DEMO-01" in sent


# -- freshness in the running application -----------------------------------------------------

def test_a_runbook_revision_reaches_answers_at_the_next_sync(app_client, ticker):
    client, runtime = app_client()
    question = "What is the escalation threshold for processing payments?"
    with client:
        seeded(client)
        before = ask(client, question, persona="user-b")
        assert "more than 30 minutes" in before["packet"]["answer"]
        login(client, "fintech_admin")
        change = client.post("/api/four-platform/upstream-changes",
                             json={"action": "apply_runbook_update"}, headers=headers(client))
        assert change.json()["changed"] == ["conf-payment-runbook"]
        assert change.json()["status"]["platforms"]["confluence"]["freshness_state"] == "stale"
        pending = ask(client, question, persona="user-b")
        # The change is known but not ingested: Confluence is stale and is not quoted as current.
        assert "more than 30 minutes" not in pending["packet"]["answer"]
        assert "confluence" in pending["packet"]["incomplete_platforms"]
        ticker.value += 125
        login(client, "fintech_admin")
        synced = client.post("/api/four-platform/sync", headers=headers(client)).json()
        assert {run["outcome"] for run in synced["runs"]} == {"completed"}
        after = ask(client, question, persona="user-b")
    assert "more than 15 minutes" in after["packet"]["answer"]
    assert "more than 30 minutes" not in after["packet"]["answer"]
    measurement = synced["status"]["measurements"][-1]
    assert measurement["propagation_seconds"] == 125.0
    assert measurement["within_budget"] is True and measurement["budget_seconds"] == 3600


def test_without_a_sync_the_index_goes_stale_after_its_budget(app_client, ticker):
    client, runtime = app_client()
    with client:
        seeded(client)
        ticker.value += 3601
        status = ask(client, ORACLE["morning_queue"]["question"], persona="user-b")
    packet = status["packet"]
    assert packet["query_status"] == "abstained" and packet["citations"] == []
    assert {entry["freshness_state"] for entry in packet["source_status"].values()} == {"stale"}


def test_the_sync_loop_runs_on_its_interval(ticker, monkeypatch):
    runtime = fixture_runtime(FINTECH_FIXTURE_ROOT, start=FINTECH_NOW, sync_interval_seconds=300,
                              monotonic=ticker)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        ticker.value += seconds
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(runtime_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever())
    scheduled = [run for run in runtime.runs if run["reason"] == "scheduled"]
    assert sleeps == [300, 300, 300]
    assert len(scheduled) == 8 and {run["outcome"] for run in scheduled} == {"completed"}
    assert runtime.status()["platforms"]["jira"]["freshness_state"] == "fresh"
    # Cancelled during the third wait, which had already run its full 300 seconds.
    assert runtime.next_sync_at == runtime.clock.now()


def test_fixture_clock_advances_in_real_time():
    ticker = Ticker()
    clock = FixtureClock(FINTECH_NOW, monotonic=ticker)
    ticker.value = 90
    assert clock.now() == FINTECH_NOW + timedelta(seconds=90)


# -- permission changes in the running application -----------------------------------------

def test_removed_access_closes_new_and_saved_answers(app_client):
    client, runtime = app_client()
    question = ORACLE["allowed_case"]["question"]
    with client:
        seeded(client)
        first = ask(client, question, persona="user-a")
        assert "conf-restricted-case" in cited(first)
        request_id = first["packet"]["request_id"]
        assert client.get(f"/api/four-platform/packets/{request_id}").status_code == 200
        login(client, "fintech_admin")
        revoke = client.post("/api/four-platform/upstream-changes",
                             json={"action": "revoke_restricted", "principal_id": "user-a"},
                             headers=headers(client))
        assert set(revoke.json()["changed"]) == {"conf-restricted-case", "drive-restricted-invoice"}
        login(client, "user-a")
        # Before the sync: the saved answer is closed and nothing restricted is quoted.
        closed = client.get(f"/api/four-platform/packets/{request_id}")
        assert closed.status_code == 404 and closed.json() == {"detail": "Evidence unavailable"}
        pending = ask(client, question)
        assert not {"conf-restricted-case", "drive-restricted-invoice"} & cited(pending)
        # Nor are its identifiers, locators or a count of withheld sources disclosed.
        suggestions = json.dumps(client.get("/api/lookup-suggestions").json())
        assert "restricted-case" not in suggestions and "restricted-invoice" not in suggestions
        verification = pending["packet"]["answer_focus"]["upstream_verification"]
        assert verification is None or "withheld" not in verification
        login(client, "fintech_admin")
        client.post("/api/four-platform/sync", headers=headers(client))
        after = ask(client, question, persona="user-a")
        assert not {"conf-restricted-case", "drive-restricted-invoice"} & cited(after)
        assert "Cedar Quay Analytics" not in after["packet"]["answer"]
        # Sources follow the same grants.
        assert client.get("/api/sources/conf-restricted-case@1/conf-restricted-case").status_code == 404
        login(client, "fintech_admin")
        client.post("/api/four-platform/upstream-changes",
                    json={"action": "restore_restricted", "principal_id": "user-a"},
                    headers=headers(client))
        client.post("/api/four-platform/sync", headers=headers(client))
        restored = ask(client, question, persona="user-a")
    assert "conf-restricted-case" in cited(restored)


def test_only_a_platform_admin_can_change_or_sync_the_platforms(app_client):
    client, _ = app_client()
    with client:
        seeded(client)
        for persona in ("user-a", "fintech_auditor", "employee"):
            login(client, persona)
            for path, body in (("/api/four-platform/sync", None),
                               ("/api/four-platform/upstream-changes",
                                {"action": "revoke_restricted"})):
                response = client.post(path, json=body, headers=headers(client))
                assert response.status_code == 403, (persona, path)
        login(client, "user-b")
        assert client.get("/api/four-platform/status").status_code == 200
        login(client, "employee")
        assert client.get("/api/four-platform/status").status_code == 403
        assert client.get("/api/four-platform/packets/unknown").status_code == 404


# -- audit: both routes, stopped queries, any filter, and the witness -------------------------

@pytest.fixture
def audit_system(tmp_path):
    db = Database(tmp_path / "audit.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    witness = AuditWitness(tmp_path / "witness" / "witness.jsonl", secrets.token_bytes(32))
    audit = AuditWriter(db.path, secrets.token_bytes(32), witness=witness)
    audit.initialize()
    audit.anchor_all()
    auth = AuthService(db)
    protected = ProtectedAuditStore(db.path, secrets.token_bytes(32), audit, auth)
    protected.initialize()
    return db, audit, auth, protected, witness


def runbook_state(now):
    text = "Payment runbook: enable failover before rolling back the config."
    import hashlib
    record = SimulatedSource(
        platform="confluence", tenant_id="demo-a", source_id="runbook", source_kind="space_page",
        version_id="runbook:v1", content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text, locator="simulated://confluence/runbook", parent_id="payment-gateway",
        source_updated_at=now - timedelta(minutes=5))
    return SimulatedPlatformState(
        records=[record], principal_map={"employee": {"confluence": "reader"}},
        confluence_space_grants={"payment-gateway": {"reader"}},
        confluence_page_grants={"runbook": {"reader"}},
        last_successful_sync={"confluence": now}, freshness_budget_seconds={"confluence": 3600})


class FailingProvider(OfflineExtractiveProvider):
    async def generate(self, context):
        raise RuntimeError("provider down")


def window():
    now = datetime.now(UTC)
    return {"since": now - timedelta(days=1), "until": now + timedelta(minutes=1)}


def test_a_stopped_query_keeps_what_was_retrieved_on_record(audit_system):
    db, audit, auth, protected, _ = audit_system
    now = datetime.now(UTC)
    service = SimulatedQueryService(auth, audit, runbook_state(now), provider=FailingProvider(),
                                    required_platforms=("confluence",), protected_audit=protected,
                                    clock=lambda: now)
    with pytest.raises(QueryError):
        asyncio.run(service.query("employee", "What does the payment runbook say about failover?", now))
    found = protected.inquire("auditor", subject_id="employee", **window())
    entry = found["entries"][0]
    assert entry["outcome"] == "query_aborted" and entry["query_status"] == "aborted"
    assert entry["answer"] is None
    assert entry["retrieved_ids"] == ["confluence:runbook:runbook:v1"]
    assert entry["decisions"][0]["retrieved"] is True
    assert entry["question"] == "What does the payment runbook say about failover?"


def test_a_query_stopped_before_any_document_decision_is_found_by_user(audit_system):
    db, audit, auth, protected, _ = audit_system
    now = datetime.now(UTC)
    state = runbook_state(now)

    def broken(*args, **kwargs):
        raise RuntimeError("index unavailable")
    state.candidates = broken
    service = SimulatedQueryService(auth, audit, state, required_platforms=("confluence",),
                                    protected_audit=protected, clock=lambda: now)
    with pytest.raises(QueryError):
        asyncio.run(service.query("employee", "What does the payment runbook say?", now))
    # Every decision mode: with no item filter the mode has nothing to apply to.
    for mode in ("retrieved", "denied", "any"):
        found = protected.inquire("auditor", subject_id="employee", decision_mode=mode,
                                  **window())
        assert found["total_matches"] == 1
        entry = found["entries"][0]
        assert entry["outcome"] == "query_failed" and entry["decisions"] == []
        assert entry["retrieved_ids"] == []
    # An item filter still needs a matching decision.
    assert protected.inquire("auditor", subject_id="employee", source_id="runbook",
                             decision_mode="any", **window())["total_matches"] == 0


def test_a_stopped_travel_policy_query_is_on_record_too(audit_system):
    db, audit, auth, protected, _ = audit_system
    service = QueryService(db, auth, audit, provider=FailingProvider(), protected_audit=protected)
    request = QueryRequest.model_validate({"question": "What is the contractor travel cap?",
                                           "context": {"workflow_id": "general",
                                                       "case_date": "2026-09-10"}})
    with pytest.raises(QueryError):
        asyncio.run(service.query(auth.principal("employee"), request))
    entry = protected.inquire("auditor", subject_id="employee", platform="policy_store",
                              decision_mode="any", **window())["entries"][0]
    assert entry["operation"] == "protected_query" and entry["answer"] is None
    assert entry["outcome"] == "query_aborted"


def test_inquiry_by_document_answers_who_retrieved_it(audit_system):
    db, audit, auth, protected, _ = audit_system
    with closing(db.connect()) as connection, connection:
        connection.execute("INSERT INTO principals VALUES ('second','demo-a',1,'[\"staff\"]')")
    now = datetime.now(UTC)
    state = runbook_state(now)
    state.set_principal_identity("second", "confluence", "reader")
    service = SimulatedQueryService(auth, audit, state, required_platforms=("confluence",),
                                    protected_audit=protected, clock=lambda: now)
    for person in ("employee", "second"):
        asyncio.run(service.query(person, "What does the payment runbook say about failover?", now))
    who = protected.inquire("auditor", source_id="runbook", **window())
    assert {entry["subject_id"] for entry in who["entries"]} == {"employee", "second"}
    with pytest.raises(ValueError):
        protected.inquire("auditor", **window())


def test_the_witness_proves_completeness_and_detects_a_removed_tail(audit_system):
    db, audit, auth, protected, witness = audit_system
    now = datetime.now(UTC)
    service = SimulatedQueryService(auth, audit, runbook_state(now), required_platforms=("confluence",),
                                    protected_audit=protected, clock=lambda: now)
    asyncio.run(service.query("employee", "What does the payment runbook say about failover?", now))
    report = audit.verify("demo-a")
    assert report["chain_valid"] is True
    assert report["completeness_unproven"] is False
    assert report["completeness_basis"] == "audit_witness"
    assert report["witness"]["unwitnessed_tail_events"] == 0
    # Remove the newest event: the remaining chain is still internally valid ...
    with closing(db.connect()) as connection, connection:
        connection.execute("DELETE FROM audit_events WHERE tenant_id='demo-a' AND sequence="
                           "(SELECT MAX(sequence) FROM audit_events WHERE tenant_id='demo-a')")
    after = audit.verify("demo-a")
    # ... but the witness knows a later head existed.
    assert after["chain_valid"] is False
    assert after["witness"]["truncation_detected"] is True
    assert after["completeness_unproven"] is True
    with pytest.raises(AuditError):
        protected.inquire("auditor", subject_id="employee", **window())


def test_applied_retention_is_witnessed(audit_system):
    db, audit, auth, _, _ = audit_system
    now = datetime.now(UTC)
    protected = ProtectedAuditStore(db.path, secrets.token_bytes(32), audit, auth,
                                    retention=RetentionPolicy(max_age_days=30, max_entries=1))
    protected.initialize()
    service = SimulatedQueryService(auth, audit, runbook_state(now), required_platforms=("confluence",),
                                    protected_audit=protected, clock=lambda: now)
    for _ in range(2):
        asyncio.run(service.query("employee", "What does the payment runbook say about failover?", now))
    assert protected.apply_retention(tenant_id="demo-a", now=now, apply=True)["removed"] == 1
    # The retention event commits outside a query, so it must be witnessed on its own.
    report = audit.verify("demo-a")
    assert report["chain_valid"] is True
    assert report["witness"]["unwitnessed_tail_events"] == 0
    assert report["completeness_unproven"] is False


def test_an_edited_witness_line_is_detected(audit_system):
    _, audit, _, _, witness = audit_system
    audit.append("demo-a", "employee", "r1", "query_attempt", {})
    audit.append("demo-a", "employee", "r2", "query_attempt", {})
    lines = witness.path.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["sequence"] += 1
    witness.path.write_text("\n".join([json.dumps(entry)] + lines[1:]) + "\n")
    report = audit.verify("demo-a")
    assert report["chain_valid"] is False
    assert "witness_integrity_failure" in report["errors"]


def test_deleting_both_tails_needs_an_external_checkpoint_to_detect(audit_system):
    db, audit, _, _, witness = audit_system
    for number in range(4):
        audit.append("demo-a", "employee", f"r{number}", "query_attempt", {})
    checkpoint = audit.checkpoint("demo-a")  # exported and kept elsewhere
    # Delete the newest event from the database and its line from the witness. No key is used.
    with closing(db.connect()) as connection, connection:
        connection.execute("DELETE FROM audit_events WHERE tenant_id='demo-a' AND sequence="
                           "(SELECT MAX(sequence) FROM audit_events WHERE tenant_id='demo-a')")
    lines = witness.path.read_text().splitlines()
    witness.path.write_text("\n".join(lines[:-1]) + "\n")
    # The witness alone cannot see it: both remaining chains are valid prefixes.
    assert audit.verify("demo-a")["completeness_unproven"] is False
    # The external checkpoint can, and completeness is then no longer claimed.
    report = audit.verify("demo-a", checkpoint)
    assert "checkpoint_missing" in report["errors"]
    assert report["witness"]["checkpoint_rollback_detected"] is True
    assert report["completeness_unproven"] is True
    assert report["completeness_basis"] is None


def test_without_a_witness_completeness_stays_unproven(tmp_path):
    db = Database(tmp_path / "plain.db")
    db.initialize()
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    audit.append("demo-a", "employee", "r1", "query_attempt", {})
    report = audit.verify("demo-a")
    assert report["completeness_unproven"] is True and report["witness"] == {"configured": False}


def test_the_officer_page_offers_the_inquiry_search(app_client):
    client, _ = app_client()
    with client:
        page = client.get("/audit").text
        seeded(client)
        login(client, "auditor")
        response = client.get("/api/audit/inquiry", params={
            "subject_id": "employee", "since": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "until": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()})
    assert 'id="inquiry-form"' in page and "Reconstruct activity" in page
    assert response.status_code == 200 and response.json()["scope"] == "all_protected_queries"


# The example searches offered on the Reconstruct activity card, as (officer, fields) pairs.
INQUIRY_EXAMPLES = [
    ("auditor", {"subject_id": "employee"}),
    ("auditor", {"subject_id": "employee", "platform": "confluence", "parent_id": "payment-gateway"}),
    ("auditor", {"subject_id": "finance_lead"}),
    ("auditor", {"subject_id": "policy_admin"}),
    ("auditor", {"platform": "policy_store", "parent_id": "finance-guide", "decision_mode": "denied"}),
    ("fintech_auditor", {"subject_id": "user-a"}),
    ("fintech_auditor", {"subject_id": "user-b"}),
    ("fintech_auditor", {"platform": "confluence", "source_id": "conf-restricted-case",
                         "decision_mode": "retrieved"}),
    ("fintech_auditor", {"platform": "confluence", "source_id": "conf-restricted-case",
                         "decision_mode": "denied"}),
]


def test_every_inquiry_example_finds_records_once_its_question_is_asked(app_client):
    client, _ = app_client()
    window = {"since": (datetime.now(UTC) - timedelta(days=30)).isoformat(),
              "until": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()}
    with client:
        script = client.get("/static/app.js").text
        seeded(client)
        for persona in ("employee", "finance_lead", "policy_admin"):
            login(client, persona)
            assert client.post("/api/queries", headers=headers(client), json={
                "question": "What is the Singapore contractor travel cap?",
                "context": {"workflow_id": "general"}}).status_code == 200
        login(client, "employee")
        assert client.post("/api/cases/case_2", headers=headers(client)).status_code == 200
        for persona in ("user-a", "user-b"):
            ask(client, "Why is Cedar Quay's payment held?", persona=persona)
        totals = []
        for officer, fields in INQUIRY_EXAMPLES:
            login(client, officer)
            response = client.get("/api/audit/inquiry", params={**window, **fields})
            assert response.status_code == 200, (fields, response.text)
            totals.append(response.json()["total_matches"])
    assert all(totals), list(zip(INQUIRY_EXAMPLES, totals, strict=True))
    for officer, fields in INQUIRY_EXAMPLES:
        for value in fields.values():
            assert f"'{value}'" in script, value


def test_invalid_inquiry_fields_are_reported_under_the_search_button(app_client):
    client, _ = app_client()
    window = {"since": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
              "until": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()}
    with client:
        page = client.get("/audit").text
        seeded(client)
        login(client, "auditor")
        bad_subject = client.get("/api/audit/inquiry", params={**window, "subject_id": "!!bad"})
        bad_parent = client.get("/api/audit/inquiry", params={**window, "parent_id": "../$$"})
    assert page.index("Search records</button>") < page.index('id="inquiry-notice"') < page.index("</form>", page.index('id="inquiry-form"'))
    for response in (bad_subject, bad_parent):
        assert response.status_code == 422 and response.json() == {"detail": "Invalid inquiry fields"}


# -- operations: readiness and diagnosable failures --------------------------------------------

def test_readiness_reports_each_dependency_and_waits_for_the_first_sync(app_client):
    client, runtime = app_client()
    with client:
        assert client.get("/health").json() == {"status": "ok"}
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready", "checks": {
            "database": True, "database_writable": True, "audit": True,
            "platforms_synced": True}}
        runtime.index.last_successful_sync = {}
        waiting = client.get("/ready")
    assert waiting.status_code == 503
    assert waiting.json()["checks"]["platforms_synced"] is False


def test_an_unexpected_failure_is_logged_by_class_and_incident_without_its_text(
        app_client, monkeypatch, caplog):
    client, runtime = app_client()

    def broken():
        raise RuntimeError("secret upstream detail")
    with client:
        seeded(client)
        login(client, "user-a")
        monkeypatch.setattr(runtime, "status", broken)
        with caplog.at_level("ERROR", logger="aspire_brain.main"):
            response = client.post("/api/four-platform/queries",
                                   json={"question": "Why is the Cedar Quay payment held?"},
                                   headers=headers(client))
    assert response.status_code == 503
    assert response.json() == {"detail": "Case simulation unavailable"}
    incident = response.headers["X-Incident-ID"]
    logged = [record.getMessage() for record in caplog.records if record.name == "aspire_brain.main"]
    assert len(logged) == 1
    assert "RuntimeError" in logged[0] and f"incident={incident}" in logged[0]
    assert "/api/four-platform/queries" in logged[0]
    assert "secret upstream detail" not in caplog.text


def test_a_wrapped_internal_query_failure_is_logged_with_its_cause(app_client, monkeypatch, caplog):
    client, runtime = app_client()

    def broken(principal, records):
        raise RuntimeError("secret upstream detail")
    with client:
        seeded(client)
        login(client, "user-a")
        monkeypatch.setattr(runtime, "verifier", broken)
        with caplog.at_level("ERROR", logger="aspire_brain.main"):
            response = client.post("/api/four-platform/queries",
                                   json={"question": "Why is the Cedar Quay payment held?"},
                                   headers=headers(client))
            refused = client.post("/api/four-platform/queries", json={"question": "x" * 2001},
                                  headers=headers(client))
    assert response.status_code == 503
    assert response.json() == {"detail": "Simulated query failed; no evidence released"}
    assert refused.status_code == 422  # an expected refusal is not logged as a failure
    logged = [record.getMessage() for record in caplog.records if record.name == "aspire_brain.main"]
    assert len(logged) == 1
    assert "QueryError from RuntimeError" in logged[0]
    assert f"incident={response.headers['X-Incident-ID']}" in logged[0]
    assert "secret upstream detail" not in caplog.text
