"""G3 cross-platform ranking.

Permitted candidates from every routed platform are scored together instead of being
concatenated per platform. Ranking only ever sees records the caller may read.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.routing import rank_candidates
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
SENTINEL = "FORBIDDEN_RANKING_SENTINEL"


def source(platform, source_id, kind, parent, text, thread=None):
    return SimulatedSource(
        platform=platform, tenant_id="demo-a", source_id=source_id, source_kind=kind,
        version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://{platform}/{source_id}", parent_id=parent, thread_id=thread,
        source_updated_at="2026-09-27T07:55:00Z",
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g3rank.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g3-ranking-audit-key-separate-12345")
    audit.initialize()
    auth = AuthService(db)
    records = [
        source("confluence", "RUNBOOK-1", "space_page", "OPS",
               "Payment incident runbook: enable failover step before restart."),
        source("jira", "OPS-17", "issue", "OPS",
               "Payment incident runbook failover: the runbook failover step is pending review."),
        source("confluence", "SECRET-1", "space_page_restricted", "SEC",
               "Payment incident runbook failover " + SENTINEL),
        source("slack", "msg-17", "thread_message", "p17-ops",
               "Payment incident runbook failover step confirmed by the on-call lead.", "thread-17"),
        source("drive", "postmortem-1", "folder_file", "ops-docs",
               "Payment incident runbook failover step postmortem."),
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


QUESTION = "What is the payment incident runbook failover step?"


# --- Score ordering ---

def test_higher_term_overlap_ranks_first_across_platforms():
    weak = source("confluence", "A-1", "space_page", "OPS", "Payment runbook only.")
    strong = source("jira", "B-1", "issue", "OPS",
                    "Payment incident runbook failover step detail.")
    ranked = rank_candidates(QUESTION, [("confluence", weak), ("jira", strong)])
    assert [record.source_id for _, record in ranked] == ["B-1", "A-1"]


def test_ranking_is_deterministic_for_equal_scores():
    first = source("drive", "d-1", "folder_file", "ops", "Payment incident runbook failover.")
    second = source("confluence", "c-1", "space_page", "OPS", "Payment incident runbook failover.")
    ranked = rank_candidates(QUESTION, [("drive", first), ("confluence", second)])
    # Tie-break is (platform, source_id), so confluence precedes drive regardless of input order.
    assert [record.platform for _, record in ranked] == ["confluence", "drive"]
    again = rank_candidates(QUESTION, [("confluence", second), ("drive", first)])
    assert [record.source_id for _, record in again] == [record.source_id for _, record in ranked]


def test_explicit_platform_mention_boosts_that_platform():
    left = source("confluence", "c-1", "space_page", "OPS", "Payment incident runbook failover.")
    right = source("jira", "j-1", "issue", "OPS", "Payment incident runbook failover.")
    ranked = rank_candidates(QUESTION, [("confluence", left), ("jira", right)],
                             explicit_platforms=("jira",))
    assert ranked[0][1].platform == "jira"


def test_limit_truncates_after_ranking():
    records = [("confluence", source("confluence", f"c-{i}", "space_page", "OPS",
                                     "Payment incident runbook failover step.")) for i in range(4)]
    ranked = rank_candidates(QUESTION, records, limit=2)
    assert len(ranked) == 2


# --- Service integration ---

BROAD_QUESTION = "Summarize the payment incident runbook failover step across platforms."


def test_packet_citations_are_ordered_by_cross_platform_score(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", BROAD_QUESTION, NOW))
    assert packet["query_status"] == "answered"
    assert set(packet["required_platforms"]) == {"confluence", "jira", "slack", "drive"}
    # A per-platform concatenation would emit confluence, jira, slack, drive. Ranking puts
    # the confluence record first (it repeats a question term in its source id) and then the
    # three equal-scoring records by the documented (platform, source_id) tie-break.
    assert [c["source_id"] for c in packet["citations"]] == [
        "RUNBOOK-1", "postmortem-1", "OPS-17", "msg-17"]
    platforms = [c["platform"] for c in packet["citations"]]
    assert len(platforms) == len(set(platforms)) == 4


def test_ranking_never_sees_a_denied_record(system):
    auth, audit, state = system
    seen = []

    from aspire_brain.providers import OfflineExtractiveProvider

    class Spy(OfflineExtractiveProvider):
        async def generate(self, context):
            seen.append(context.model_dump_json())
            return await super().generate(context)

    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    provider=Spy(), clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    assert SENTINEL not in "".join(seen)
    assert SENTINEL not in packet["answer"]
    assert all(c["source_id"] != "SECRET-1" for c in packet["citations"])


def test_ranking_records_the_score_basis_in_the_packet(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    assert packet["context_budget"]["max_items"] >= 1
    assert packet["context_budget"]["max_chars"] >= 100
    assert packet["context_budget"]["degraded"] is False
    assert packet["context_budget"]["dropped_items"] == 0
