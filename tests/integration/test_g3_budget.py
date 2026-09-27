"""G3 explicit overall context budget.

The total characters and item count across all platforms are capped. When the budget binds
the degradation is deterministic, the dropped evidence is recorded, and a routed platform
that is budget-excluded forces an explicit ``partial`` or ``abstained`` result.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.routing import ContextBudget, apply_budget, rank_candidates
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
# A broad question routes to all four platforms, so the overall budget has to arbitrate
# between them rather than acting inside a single platform.
QUESTION = "Summarize the payment incident runbook failover step across platforms."


def source(platform, source_id, kind, parent, text, thread=None):
    return SimulatedSource(
        platform=platform, tenant_id="demo-a", source_id=source_id, source_kind=kind,
        version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://{platform}/{source_id}", parent_id=parent, thread_id=thread,
        source_updated_at="2026-09-27T07:55:00Z",
    )


def build_state(texts):
    records = []
    for entry in texts:
        platform, source_id, kind, parent, text = entry[:5]
        thread = entry[5] if len(entry) > 5 else None
        records.append(source(platform, source_id, kind, parent, text, thread=thread))
    return SimulatedPlatformState(
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
        last_successful_sync={p: NOW for p in ("confluence", "jira", "slack", "drive")},
        freshness_budget_seconds={p: 3600 for p in ("confluence", "jira", "slack", "drive")},
    )


FOUR_RECORDS = [
    ("confluence", "RUNBOOK-1", "space_page", "OPS",
     "Payment incident runbook failover step for confluence."),
    ("jira", "OPS-17", "issue", "OPS",
     "Payment incident runbook failover step for jira."),
    ("slack", "msg-17", "thread_message", "p17-ops",
     "Payment incident runbook failover step for slack.", "thread-17"),
    ("drive", "postmortem-1", "folder_file", "ops-docs",
     "Payment incident runbook failover step for drive."),
]


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g3bud.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g3-budget-audit-key-is-separate-12345")
    audit.initialize()
    return AuthService(db), audit, build_state(FOUR_RECORDS)


# --- Budget model and pure function ---

def test_context_budget_validates_bounds():
    with pytest.raises(ValidationError):
        ContextBudget(max_items=0, max_chars=1000)
    with pytest.raises(ValidationError):
        ContextBudget(max_items=5, max_chars=10)


def test_apply_budget_caps_items_and_keeps_ranking_order():
    records = [source("confluence", f"c-{i}", "space_page", "OPS",
                      "Payment incident runbook failover step.") for i in range(5)]
    ranked = rank_candidates(QUESTION, [("confluence", record) for record in records])
    included, dropped = apply_budget(ranked, ContextBudget(max_items=2, max_chars=100000))
    assert len(included) == 2
    assert len(dropped) == 3
    assert [r.source_id for _, r in included] == [r.source_id for _, r in ranked[:2]]


def test_apply_budget_caps_characters():
    big = source("confluence", "big", "space_page", "OPS", "x" * 500)
    small = source("jira", "small", "issue", "OPS", "Payment incident runbook failover.")
    ranked = rank_candidates(QUESTION, [("jira", small), ("confluence", big)])
    included, dropped = apply_budget(ranked, ContextBudget(max_items=5, max_chars=200))
    assert len(included) == 1
    assert included[0][1].source_id == "small"
    assert [r.source_id for _, r in dropped] == ["big"]


# --- Service integration ---

def test_binding_budget_degrades_and_never_answers_completely(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    budget=ContextBudget(max_items=2, max_chars=100000),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    budget = packet["context_budget"]
    assert budget["degraded"] is True
    assert budget["included_items"] == 2
    assert budget["dropped_items"] == 2
    assert len(budget["dropped_ids"]) == 2
    assert budget["budget_excluded_platforms"]
    # A routed platform excluded by the budget must not yield an unqualified complete answer.
    assert packet["query_status"] == "partial"
    assert set(budget["budget_excluded_platforms"]) <= set(packet["incomplete_platforms"])
    assert len(packet["citations"]) == 2


def test_budget_excluded_text_is_not_in_the_answer_or_citations(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    budget=ContextBudget(max_items=1, max_chars=100000),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    dropped_ids = packet["context_budget"]["dropped_ids"]
    assert dropped_ids
    kept_sources = {c["source_id"] for c in packet["citations"]}
    for dropped_id in dropped_ids:
        platform, source_id = dropped_id.split(":")[0], dropped_id.split(":")[1]
        assert source_id not in kept_sources
        assert state.records[(platform, source_id)].text not in packet["answer"]


def test_generous_budget_does_not_degrade(system):
    auth, audit, state = system
    service = SimulatedQueryService(auth, audit, state, required_platforms=None,
                                    budget=ContextBudget(max_items=20, max_chars=50000),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    assert packet["context_budget"]["degraded"] is False
    assert packet["query_status"] == "answered"
    assert len(packet["citations"]) == 4
