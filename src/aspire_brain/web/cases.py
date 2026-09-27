"""Simulated case fixtures for the five PDF examples plus a G2 Drive supplement."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal

from aspire_brain.auth import AccessDenied
from aspire_brain.platforms.routing import detect_time_window
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)
from aspire_brain.platforms.sync import (
    SimulatedUpstream,
    Synchronizer,
    SyncIndex,
    measure_freshness,
)
from aspire_brain.providers.grounded import GroundedAnswerProvider

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)

# Declared G2 freshness budget: within the PDF's "minutes to ~1 hour" window.
FRESHNESS_BUDGET_SECONDS = 3600

# Case 2 simulated timeline (all times are deterministic simulated elapsed time).
CASE_2_INITIAL_SYNC = datetime(2026, 9, 27, 12, 30, tzinfo=UTC)
CASE_2_PRE_UPDATE_QUERY = datetime(2026, 9, 27, 12, 35, tzinfo=UTC)
CASE_2_MUTATION = datetime(2026, 9, 27, 13, 0, tzinfo=UTC)
CASE_2_PRE_SYNC_QUERY = datetime(2026, 9, 27, 13, 5, tzinfo=UTC)
CASE_2_SYNC = datetime(2026, 9, 27, 13, 10, tzinfo=UTC)
CASE_2_FINAL_QUERY = datetime(2026, 9, 27, 14, 5, tzinfo=UTC)

CASE_2_QUERY = "What is the latest runbook for the payment-service incident?"
CASE_2_OLD_RUNBOOK = ("Payment-service incident runbook: step 1 restart the service; "
                      "step 2 notify the on-call lead.")
CASE_2_NEW_RUNBOOK = (CASE_2_OLD_RUNBOOK +
                      " step 3 enable failover to the standby region.")


def _source(
    platform: Literal["confluence", "jira", "slack", "drive"],
    source_id: str,
    kind: str,
    parent: str,
    text: str,
    thread: str | None = None,
    updated: datetime | None = None,
    version: str = "v1",
    event: datetime | None = None,
):
    return SimulatedSource(
        platform=platform,
        tenant_id="demo-a",
        source_id=source_id,
        source_kind=kind,  # type: ignore[arg-type]
        version_id=f"{source_id}:{version}",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        locator=f"simulated://{platform}/{source_id}",
        parent_id=parent,
        thread_id=thread,
        source_updated_at=updated or datetime(2026, 9, 27, 9, 30, tzinfo=UTC),
        event_at=event,
    )


# Case 1: Jira + Slack cross-platform query, routed from the question and time-scoped.
CASE_1_QUERY = ("What is the status of the database migration project and were there any "
                "blockers raised in Slack last week?")
# The Slack messages carry a message event time, distinct from their last update time.
CASE_1_SLACK_EVENT = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)

CASE_1_RECORDS = [
    _source("jira", "MIGRATE-42", "issue", "DB",
            "Database migration project status: in progress. Blocker: connection pool limit."),
    _source("slack", "msg-db-1", "thread_message", "db-migration",
            "Database migration blocker confirmed in Slack: connection pool limit exceeded.",
            "thread-db-1", event=CASE_1_SLACK_EVENT),
]

CASE_1_STATE = SimulatedPlatformState(
    records=CASE_1_RECORDS,
    principal_map={"employee": {"jira": "jira-employee", "slack": "slack-employee"}},
    jira_project_grants={"DB": {"jira-employee"}},
    jira_issue_grants={"MIGRATE-42": {"jira-employee"}},
    slack_channel_grants={"db-migration": {"slack-employee"}},
    slack_thread_grants={"thread-db-1": {"slack-employee"}},
    slack_dm_grants={},
    last_successful_sync={"jira": NOW, "slack": NOW},
    freshness_budget_seconds={"jira": 3600, "slack": 3600},
)

# Case 2: Confluence runbook freshness — built per run by case_2_sequence().
# The previous fixed-timestamp fixture is replaced by an actual simulated
# mutation -> sync -> query sequence with a declared budget.

# Case 3: Restricted Confluence report (existence not disclosed)
CASE_3_QUERY = "Show me the security incident report from the Q3 breach."

CASE_3_RECORDS = [
    _source("confluence", "BREACH-RPT", "space_page_restricted", "SEC",
            "Q3 breach incident report: classified."),
]

CASE_3_STATE = SimulatedPlatformState(
    records=CASE_3_RECORDS,
    principal_map={"employee": {"confluence": "conf-employee"}},
    confluence_space_grants={"SEC": set()},  # no one granted
    confluence_page_grants={"BREACH-RPT": set()},
    last_successful_sync={"confluence": NOW},
    freshness_budget_seconds={"confluence": 3600},
)

# Case 4: Revocation (Slack channel access removed)
CASE_4_RECORDS = [
    _source("slack", "msg-rev-1", "channel_message", "incident",
            "Incident update: service restored."),
]

def case_4_state():
    """Each run owns its permission state, including when a query fails."""
    return SimulatedPlatformState(
        records=CASE_4_RECORDS,
        principal_map={"employee": {"slack": "slack-employee"}},
        slack_channel_grants={"incident": {"slack-employee"}},
        slack_thread_grants={},
        slack_dm_grants={},
        last_successful_sync={"slack": NOW},
        freshness_budget_seconds={"slack": 3600},
    )


async def case_2_sequence(auth, audit, principal_id: str, protected_audit=None):
    """Run the actual simulated update -> sync -> query freshness sequence.

    The older runbook is ingested at 12:30. The owner pushes the failover update at
    13:00. A query at 13:05 must not present the stale runbook as current. A sync at
    13:10 ingests the update (10 simulated minutes, inside the 3600 s budget). A query
    is run immediately at the ingestion time so the fixture observes the first post-sync
    correct answer, and the demo query at 14:05 is recorded as the observed answer. The
    earliest possible answer moment is not polled, so it stays unknown.
    """
    upstream = SimulatedUpstream(
        platform="confluence", tenant_id="demo-a", page_size=2,
        records=[_source("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway",
                         CASE_2_OLD_RUNBOOK, updated=datetime(2026, 9, 27, 12, 0, tzinfo=UTC))],
        grants={"confluence_space_grants": {"payment-gateway": {"conf-employee"}},
                "confluence_page_grants": {"RUNBOOK-PAY": {"conf-employee"}}},
    )
    index = SyncIndex(
        principal_map={"employee": {"confluence": "conf-employee"}},
        freshness_budget_seconds={"confluence": FRESHNESS_BUDGET_SECONDS},
        upstream={"confluence": upstream},
    )
    syncer = Synchronizer(index)
    syncer.sync("confluence", CASE_2_INITIAL_SYNC)
    clock = [CASE_2_PRE_UPDATE_QUERY]
    service = SimulatedQueryService(auth, audit, index, required_platforms=("confluence",),
                                    protected_audit=protected_audit, clock=lambda: clock[0])
    pre_update = await service.query(principal_id, CASE_2_QUERY, CASE_2_PRE_UPDATE_QUERY)

    upstream.upsert(_source("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway",
                            CASE_2_NEW_RUNBOOK, updated=CASE_2_MUTATION, version="v2"),
                    at=CASE_2_MUTATION)
    clock[0] = CASE_2_PRE_SYNC_QUERY
    pre_sync = await service.query(principal_id, CASE_2_QUERY, CASE_2_PRE_SYNC_QUERY)

    sync_run = syncer.sync("confluence", CASE_2_SYNC)
    # Observe the first correct answer the fixture actually runs after ingestion.
    clock[0] = CASE_2_SYNC
    first_post_sync = await service.query(principal_id, CASE_2_QUERY, CASE_2_SYNC)
    clock[0] = CASE_2_FINAL_QUERY
    packet = await service.query(principal_id, CASE_2_QUERY, CASE_2_FINAL_QUERY)
    measurement = measure_freshness(
        platform="confluence", mutation_at=CASE_2_MUTATION, ingested_at=CASE_2_SYNC,
        observed_answer_at=CASE_2_FINAL_QUERY, budget_seconds=FRESHNESS_BUDGET_SECONDS,
        first_post_sync_query_at=CASE_2_SYNC,
        first_post_sync_answer_contains_update="failover" in first_post_sync["answer"],
        observed_answer_contains_update="failover" in packet["answer"],
        observation_mode="observed_query")
    return {
        "query": CASE_2_QUERY,
        "principal": principal_id,
        "platforms": ["confluence"],
        "packet": packet,
        "pre_update_packet": pre_update,
        "pre_sync_packet": pre_sync,
        "first_post_sync_packet": first_post_sync,
        "sync_run": sync_run,
        "measurement": measurement,
        "state": index,
        "upstream": upstream,
    }


CASE_6_QUERY = "What does the incident postmortem say about the root cause and recovery steps?"
CASE_6_OLD_POSTMORTEM = "Incident postmortem: root cause was configuration drift in the service config."
CASE_6_NEW_POSTMORTEM = (CASE_6_OLD_POSTMORTEM +
                         " Recovery step: enable failover before rolling back the config.")


def _drive_fixture():
    """A fresh Drive upstream and index, so each observation starts from a clean state."""
    upstream = SimulatedUpstream(
        platform="drive", tenant_id="demo-a", page_size=2,
        records=[_source("drive", "postmortem-1", "folder_file", "ops-docs",
                         CASE_6_OLD_POSTMORTEM, updated=datetime(2026, 9, 27, 12, 0, tzinfo=UTC))],
        grants={"drive_folder_grants": {"ops-docs": {"drive-employee"}},
                "drive_file_grants": {"postmortem-1": {"drive-employee"}}},
    )
    index = SyncIndex(
        principal_map={"employee": {"drive": "drive-employee"}},
        freshness_budget_seconds={"drive": FRESHNESS_BUDGET_SECONDS},
        upstream={"drive": upstream},
    )
    return upstream, index


async def case_6_drive_sequence(auth, audit, principal_id: str, protected_audit=None):
    """Supplemental Drive G2 path: create -> sync -> query, then delete -> tombstone.

    A second, independent fixture performs a **real** late synchronization: the update is
    pushed at 13:00 and only ingested at 14:10 (4200 s, outside the 3600 s budget), then a
    query is actually run. That run is the observed over-budget row; the propagation is
    simulated elapsed time and no live latency is measured.
    """
    upstream, index = _drive_fixture()
    syncer = Synchronizer(index)
    syncer.sync("drive", CASE_2_INITIAL_SYNC)
    clock = [CASE_2_PRE_UPDATE_QUERY]
    service = SimulatedQueryService(auth, audit, index, required_platforms=("drive",),
                                    protected_audit=protected_audit, clock=lambda: clock[0])
    pre_update = await service.query(principal_id, CASE_6_QUERY, CASE_2_PRE_UPDATE_QUERY)

    upstream.upsert(_source("drive", "postmortem-1", "folder_file", "ops-docs",
                            CASE_6_NEW_POSTMORTEM, updated=CASE_2_MUTATION, version="v2"),
                    at=CASE_2_MUTATION)
    clock[0] = CASE_2_PRE_SYNC_QUERY
    pre_sync = await service.query(principal_id, CASE_6_QUERY, CASE_2_PRE_SYNC_QUERY)
    sync_run = syncer.sync("drive", CASE_2_SYNC)
    clock[0] = CASE_2_FINAL_QUERY
    packet = await service.query(principal_id, CASE_6_QUERY, CASE_2_FINAL_QUERY)
    measurement = measure_freshness(
        platform="drive", mutation_at=CASE_2_MUTATION, ingested_at=CASE_2_SYNC,
        observed_answer_at=CASE_2_FINAL_QUERY, budget_seconds=FRESHNESS_BUDGET_SECONDS,
        observed_answer_contains_update="failover" in packet["answer"],
        observation_mode="observed_query")

    upstream.delete("postmortem-1", at=datetime(2026, 9, 27, 14, 6, tzinfo=UTC))
    delete_run = syncer.sync("drive", datetime(2026, 9, 27, 14, 10, tzinfo=UTC))
    clock[0] = datetime(2026, 9, 27, 14, 15, tzinfo=UTC)
    after_delete_query = await service.query(principal_id, CASE_6_QUERY, clock[0])

    # A real late sync: same mutation, ingested only after the declared budget elapsed.
    late_upstream, late_index = _drive_fixture()
    late_syncer = Synchronizer(late_index)
    late_syncer.sync("drive", CASE_2_INITIAL_SYNC)
    late_upstream.upsert(_source("drive", "postmortem-1", "folder_file", "ops-docs",
                                 CASE_6_NEW_POSTMORTEM, updated=CASE_2_MUTATION, version="v2"),
                         at=CASE_2_MUTATION)
    late_sync_at = CASE_2_MUTATION + timedelta(seconds=FRESHNESS_BUDGET_SECONDS + 600)
    late_sync_run = late_syncer.sync("drive", late_sync_at)
    late_service = SimulatedQueryService(auth, audit, late_index, required_platforms=("drive",),
                                         protected_audit=protected_audit,
                                         clock=lambda: late_sync_at)
    late_packet = await late_service.query(principal_id, CASE_6_QUERY, late_sync_at)
    over_budget = measure_freshness(
        platform="drive", mutation_at=CASE_2_MUTATION, ingested_at=late_sync_at,
        observed_answer_at=late_sync_at, budget_seconds=FRESHNESS_BUDGET_SECONDS,
        first_post_sync_query_at=late_sync_at,
        first_post_sync_answer_contains_update="failover" in late_packet["answer"],
        observed_answer_contains_update="failover" in late_packet["answer"],
        observation_mode="observed_late_sync")
    return {
        "query": CASE_6_QUERY,
        "principal": principal_id,
        "platforms": ["drive"],
        "packet": packet,
        "pre_update_packet": pre_update,
        "pre_sync_packet": pre_sync,
        "after_delete_query": after_delete_query,
        "sync_run": sync_run,
        "delete_run": delete_run,
        "measurement": measurement,
        "over_budget_measurement": over_budget,
        "late_sync_run": late_sync_run,
        "late_packet": late_packet,
        "state": index,
        "upstream": upstream,
    }


# Case 7 (G4): the same permitted evidence answered by the explicitly selected grounded
# provider, with a claim-level support report and an abstention control. The default
# offline_extractive answer is shown beside it so the default is visible.
async def case_7_grounding_sequence(auth, audit, principal_id: str, protected_audit=None):
    window = detect_time_window(CASE_1_QUERY, NOW)
    default_service = SimulatedQueryService(auth, audit, CASE_1_STATE, required_platforms=None,
                                            protected_audit=protected_audit, clock=lambda: NOW)
    default_packet = await default_service.query(principal_id, CASE_1_QUERY, NOW,
                                                 time_windows={"slack": window})
    grounded_service = SimulatedQueryService(auth, audit, CASE_1_STATE,
                                             provider=GroundedAnswerProvider(),
                                             required_platforms=None,
                                             protected_audit=protected_audit, clock=lambda: NOW)
    grounded_packet = await grounded_service.query(principal_id, CASE_1_QUERY, NOW,
                                                   time_windows={"slack": window})
    abstention_service = SimulatedQueryService(auth, audit, CASE_3_STATE,
                                               provider=GroundedAnswerProvider(),
                                               required_platforms=("confluence",),
                                               protected_audit=protected_audit,
                                               clock=lambda: NOW)
    abstention_packet = await abstention_service.query(principal_id, CASE_3_QUERY, NOW)
    return {
        "query": CASE_1_QUERY,
        "principal": principal_id,
        "platforms": grounded_packet["routing"]["selected_platforms"],
        "packet": grounded_packet,
        "default_packet": default_packet,
        "abstention": {"query": CASE_3_QUERY, "packet": abstention_packet},
        "claim_support": grounded_packet["claim_support"],
        "provider_runtime": grounded_packet["provider_runtime"],
        "provider_note": ("offline_extractive remains the default. This card explicitly selects "
                          "the deterministic local grounded provider; no live model is "
                          "contacted and no live claim-support result exists."),
        "state": CASE_1_STATE,
    }


async def run_case(auth, audit, case_id: str, principal_id: str, protected_audit=None):
    if case_id == "case_1":
        # Question-driven routing decides the platforms, and the Slack window scopes messages
        # by their event time. Jira issues are not time-filtered.
        service = SimulatedQueryService(auth, audit, CASE_1_STATE,
                                        required_platforms=None,
                                        protected_audit=protected_audit,
                                        clock=lambda: NOW)
        window = detect_time_window(CASE_1_QUERY, NOW)
        packet = await service.query(principal_id, CASE_1_QUERY, NOW,
                                     time_windows={"slack": window})
        return {
            "query": CASE_1_QUERY,
            "principal": principal_id,
            "platforms": packet["routing"]["selected_platforms"],
            "packet": packet,
            "time_scope": packet["time_scope"],
            "time_scope_note": ("Slack messages are filtered to the last 7 days by message event "
                                "time; Jira issues are not time-filtered."),
            "state": CASE_1_STATE,
        }

    if case_id == "case_2":
        return await case_2_sequence(auth, audit, principal_id, protected_audit)

    if case_id == "case_3":
        service = SimulatedQueryService(auth, audit, CASE_3_STATE,
                                        required_platforms=("confluence",),
                                        protected_audit=protected_audit,
                                        clock=lambda: NOW)
        result = {
            "query": CASE_3_QUERY,
            "principal": principal_id,
            "platforms": ["confluence"],
        }
        packet = await service.query(principal_id, result["query"], NOW)
        return {**result, "packet": packet, "state": CASE_3_STATE}

    if case_id == "case_4":
        # First query succeeds, then revoke, then second query fails
        state = case_4_state()
        service = SimulatedQueryService(auth, audit, state,
                                        required_platforms=("slack",),
                                        protected_audit=protected_audit,
                                        clock=lambda: NOW)
        result = {
            "query": "What is the latest incident update?",
            "principal": principal_id,
            "platforms": ["slack"],
        }
        packet = await service.query(principal_id, result["query"], NOW)
        # Revoke channel access
        state.set_slack_channel_grant("incident", "slack-employee", False)
        try:
            service.packet(principal_id, packet["request_id"])
            after_packet = "unexpectedly_allowed"
        except AccessDenied:
            after_packet = "denied"
        after_query = await service.query(principal_id, result["query"], NOW)
        return {
            **result,
            "packet": packet,
            "after_packet": after_packet,
            "after_query": after_query,
            "state": state,
        }

    if case_id == "case_6":
        return await case_6_drive_sequence(auth, audit, principal_id, protected_audit)

    if case_id == "case_7":
        return await case_7_grounding_sequence(auth, audit, principal_id, protected_audit)

    raise ValueError(f"Unknown case: {case_id}")
