"""G2 measured freshness: an actual simulated mutation -> sync -> query sequence.

Case 2 previously displayed a fixed-timestamp fixture. These tests require a real
simulated update/sync/query sequence with a declared budget, and require simulated
elapsed time to be labelled separately from wall-clock measurements.
"""

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.config import Settings
from aspire_brain.db import Database
from aspire_brain.main import create_app
from aspire_brain.platforms.simulated import SimulatedQueryService, SimulatedSource
from aspire_brain.platforms.sync import (
    SimulatedUpstream,
    Synchronizer,
    SyncIndex,
    measure_freshness,
)
from aspire_brain.web.cases import case_2_sequence

ROOT = Path(__file__).resolve().parents[2]
T_1230 = datetime(2026, 9, 27, 12, 30, tzinfo=UTC)
T_1235 = datetime(2026, 9, 27, 12, 35, tzinfo=UTC)
T_1300 = datetime(2026, 9, 27, 13, 0, tzinfo=UTC)
T_1305 = datetime(2026, 9, 27, 13, 5, tzinfo=UTC)
T_1310 = datetime(2026, 9, 27, 13, 10, tzinfo=UTC)
T_1405 = datetime(2026, 9, 27, 14, 5, tzinfo=UTC)
BUDGET = 3600
OLD_RUNBOOK = "Payment-service incident runbook: step 1 restart the service; step 2 notify the on-call lead."
NEW_RUNBOOK = ("Payment-service incident runbook: step 1 restart the service; "
               "step 2 notify the on-call lead; step 3 enable failover to the standby region.")


def rec(platform, source_id, kind, parent, text, updated, thread=None, version="v1"):
    return SimulatedSource(
        platform=platform, tenant_id="demo-a", source_id=source_id, source_kind=kind,
        version_id=f"{source_id}:{version}",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://{platform}/{source_id}", parent_id=parent, thread_id=thread,
        source_updated_at=updated,
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g2f.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g2-fresh-audit-key-is-separate-123456")
    audit.initialize()
    return AuthService(db), audit


# --- Measurement labelling ---

def test_measure_freshness_labels_simulated_elapsed_and_leaves_live_null():
    measurement = measure_freshness(platform="confluence", mutation_at=T_1300,
                                    ingested_at=T_1310, observed_answer_at=T_1405,
                                    budget_seconds=BUDGET)
    assert measurement["time_mode"] == "simulated_elapsed"
    assert measurement["simulation_mode"] == "simulated"
    assert measurement["wall_clock_seconds"] is None
    assert measurement["live_propagation_seconds"] is None
    assert measurement["propagation_seconds"] == 600
    assert measurement["answer_latency_seconds"] == 3900
    assert measurement["within_budget"] is True
    assert measurement["outcome"] == "within_budget"
    # The 14:05 field is the observed query, not the earliest possible answer.
    assert measurement["observed_answer_at"] == T_1405.isoformat()
    assert measurement["earliest_correct_answer_at"] is None
    assert measurement["earliest_visibility"] == "unknown"


def test_measure_freshness_flags_over_budget():
    measurement = measure_freshness(platform="drive", mutation_at=T_1300,
                                    ingested_at=T_1300 + timedelta(seconds=4200),
                                    observed_answer_at=T_1300 + timedelta(seconds=4300),
                                    budget_seconds=BUDGET)
    assert measurement["within_budget"] is False
    assert measurement["outcome"] == "over_budget"
    assert measurement["propagation_seconds"] == 4200


# --- Case 2 sequence ---

def test_case_2_sequence_measures_update_to_answer_within_budget(system):
    auth, audit = system
    result = asyncio.run(case_2_sequence(auth, audit, "employee"))
    measurement = result["measurement"]
    assert measurement["platform"] == "confluence"
    assert measurement["budget_seconds"] == BUDGET
    assert measurement["propagation_seconds"] == 600
    assert measurement["within_budget"] is True
    assert measurement["time_mode"] == "simulated_elapsed"
    assert measurement["wall_clock_seconds"] is None
    assert measurement["mutation_at"] == T_1300.isoformat()
    assert measurement["ingested_at"] == T_1310.isoformat()
    assert measurement["observed_answer_at"] == T_1405.isoformat()
    assert measurement["earliest_correct_answer_at"] is None
    assert measurement["earliest_visibility"] == "unknown"


def test_case_2_observes_the_first_post_sync_query_at_ingestion_time(system):
    auth, audit = system
    result = asyncio.run(case_2_sequence(auth, audit, "employee"))
    measurement = result["measurement"]
    # The fixture actually runs a query at ingestion time, so the first post-sync answer
    # is observed rather than inferred.
    assert measurement["first_post_sync_query_at"] == T_1310.isoformat()
    assert measurement["first_post_sync_answer_contains_update"] is True
    assert measurement["observed_answer_contains_update"] is True
    assert result["first_post_sync_packet"]["query_status"] == "answered"
    assert "failover" in result["first_post_sync_packet"]["answer"]


def test_case_2_updated_runbook_is_visible_only_after_sync(system):
    auth, audit = system
    result = asyncio.run(case_2_sequence(auth, audit, "employee"))
    assert "failover" in result["packet"]["answer"]
    assert result["packet"]["query_status"] == "answered"
    # Pre-update (12:35) and pre-sync (13:05) answers must not contain the new step.
    assert "failover" not in result["pre_update_packet"]["answer"]
    assert "failover" not in result["pre_sync_packet"]["answer"]
    assert result["pre_sync_packet"]["query_status"] != "answered"
    assert result["pre_sync_packet"]["source_status"]["confluence"]["freshness_state"] == "stale"


def test_case_2_sequence_is_not_a_fixed_timestamp_demonstration(system):
    auth, audit = system
    result = asyncio.run(case_2_sequence(auth, audit, "employee"))
    measurement = result["measurement"]
    times = [measurement["mutation_at"], measurement["ingested_at"],
             measurement["observed_answer_at"]]
    assert len(set(times)) == 3
    assert measurement["mutation_at"] < measurement["ingested_at"] < measurement["observed_answer_at"]


# --- Four-platform propagation ---

PLATFORM_CASES = {
    "confluence": ("space_page", "payment-gateway", "RUNBOOK-PAY", None,
                   {"confluence_space_grants": {"payment-gateway": {"conf-employee"}},
                    "confluence_page_grants": {"RUNBOOK-PAY": {"conf-employee"}}}),
    "jira": ("issue", "OPS", "OPS-17", None,
             {"jira_project_grants": {"OPS": {"jira-employee"}},
              "jira_issue_grants": {"OPS-17": {"jira-employee"}}}),
    "slack": ("thread_message", "p17-ops", "msg-17", "thread-17",
              {"slack_channel_grants": {"p17-ops": {"slack-employee"}},
               "slack_thread_grants": {"thread-17": {"slack-employee"}}}),
    "drive": ("folder_file", "ops-docs", "postmortem-1", None,
              {"drive_folder_grants": {"ops-docs": {"drive-employee"}},
               "drive_file_grants": {"postmortem-1": {"drive-employee"}}}),
}
ACCOUNT = {"confluence": "conf-employee", "jira": "jira-employee",
           "slack": "slack-employee", "drive": "drive-employee"}


@pytest.mark.parametrize("platform", sorted(PLATFORM_CASES))
def test_each_platform_propagates_an_update_within_budget(system, platform):
    auth, audit = system
    kind, parent, source_id, thread, grants = PLATFORM_CASES[platform]
    old_text = f"{platform} record original text about the incident runbook."
    new_text = f"{platform} record updated text with failover step for the incident runbook."
    upstream = SimulatedUpstream(
        platform=platform, tenant_id="demo-a", page_size=2,
        records=[rec(platform, source_id, kind, parent, old_text, T_1230, thread=thread)],
        grants=grants,
    )
    index = SyncIndex(principal_map={"employee": {platform: ACCOUNT[platform]}},
                      freshness_budget_seconds={platform: BUDGET},
                      upstream={platform: upstream})
    syncer = Synchronizer(index)
    syncer.sync(platform, T_1230)
    service = SimulatedQueryService(auth, audit, index, required_platforms=(platform,),
                                    clock=lambda: T_1235)
    before = asyncio.run(service.query("employee", f"What is the {platform} incident runbook?",
                                       T_1235))
    assert "failover" not in before["answer"]
    upstream.upsert(rec(platform, source_id, kind, parent, new_text, T_1300, thread=thread,
                        version="v2"), at=T_1300)
    pre = asyncio.run(service.query("employee", f"What is the {platform} incident runbook?",
                                    T_1305))
    assert pre["query_status"] != "answered"
    syncer.sync(platform, T_1310)
    after = asyncio.run(service.query("employee", f"What is the {platform} incident runbook?",
                                      T_1405))
    measurement = measure_freshness(platform=platform, mutation_at=T_1300, ingested_at=T_1310,
                                    observed_answer_at=T_1405, budget_seconds=BUDGET)
    assert "failover" in after["answer"]
    assert measurement["within_budget"] is True
    assert measurement["propagation_seconds"] == 600


# --- Over-budget failure ---

def test_over_budget_sync_is_recorded_as_a_failure(system):
    auth, audit = system
    upstream = SimulatedUpstream(
        platform="drive", tenant_id="demo-a", page_size=2,
        records=[rec("drive", "postmortem-1", "folder_file", "ops-docs",
                     "Drive postmortem original text about the incident.", T_1230)],
        grants={"drive_folder_grants": {"ops-docs": {"drive-employee"}},
                "drive_file_grants": {"postmortem-1": {"drive-employee"}}},
    )
    index = SyncIndex(principal_map={"employee": {"drive": "drive-employee"}},
                      freshness_budget_seconds={"drive": BUDGET},
                      upstream={"drive": upstream})
    syncer = Synchronizer(index)
    syncer.sync("drive", T_1230)
    upstream.upsert(rec("drive", "postmortem-1", "folder_file", "ops-docs",
                        "Drive postmortem updated with failover guidance.", T_1300, version="v2"),
                    at=T_1300)
    # The update is pending, so the source is stale until a sync actually ingests it.
    assert index.source_status("drive", T_1405)["freshness_state"] == "stale"
    late_ingest = T_1300 + timedelta(seconds=4200)
    run = syncer.sync("drive", late_ingest)
    service = SimulatedQueryService(auth, audit, index, required_platforms=("drive",),
                                    clock=lambda: late_ingest)
    packet = asyncio.run(service.query("employee", "What is the drive incident runbook?",
                                       late_ingest))
    # A real late run: the update is ingested and queried only after the budget elapsed.
    measurement = measure_freshness(
        platform="drive", mutation_at=T_1300, ingested_at=late_ingest,
        observed_answer_at=late_ingest, budget_seconds=BUDGET,
        first_post_sync_query_at=late_ingest,
        first_post_sync_answer_contains_update="failover" in packet["answer"],
        observed_answer_contains_update="failover" in packet["answer"],
        observation_mode="observed_late_sync")
    assert run["outcome"] == "completed"
    assert "failover" in packet["answer"]
    assert measurement["within_budget"] is False
    assert measurement["outcome"] == "over_budget"
    assert measurement["observation_mode"] == "observed_late_sync"
    assert measurement["first_post_sync_answer_contains_update"] is True


# --- Browser routes ---

def client_for(settings):
    return TestClient(create_app(settings), base_url="http://localhost",
                      client=("127.0.0.1", 50000))


def headers(client):
    session = client.get("/api/session").json()
    return {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}


@pytest.fixture
def browser_client(tmp_path):
    settings = Settings(db_path=tmp_path / "cases.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)
    with client_for(settings) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=headers(client)).status_code == 200
        yield client


def test_case_2_browser_route_exposes_a_measured_sequence(browser_client):
    response = browser_client.post("/api/cases/case_2", headers=headers(browser_client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert "failover" in body["packet"]["answer"]
    measurement = body["measurement"]
    assert measurement["time_mode"] == "simulated_elapsed"
    assert measurement["wall_clock_seconds"] is None
    assert measurement["within_budget"] is True
    assert measurement["propagation_seconds"] == 600


def test_drive_supplemental_case_route_shows_create_and_delete(browser_client):
    response = browser_client.post("/api/cases/case_6", headers=headers(browser_client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["platforms"] == ["drive"]
    assert "failover" in body["packet"]["answer"]
    assert body["after_delete_query"]["query_status"] == "abstained"
    assert body["after_delete_query"]["citations"] == []
    assert body["measurement"]["within_budget"] is True
    assert body["over_budget_measurement"]["within_budget"] is False
    # The over-budget row comes from a real late sync and query, not a calculation.
    assert body["over_budget_measurement"]["observation_mode"] == "observed_late_sync"
    assert body["over_budget_measurement"]["first_post_sync_answer_contains_update"] is True
    assert "failover" in body["late_packet"]["answer"]
    assert body["late_sync_run"]["outcome"] == "completed"
