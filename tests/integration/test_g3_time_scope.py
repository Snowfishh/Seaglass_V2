"""G3 time-scoped retrieval.

Case 1 asks for blockers "raised in Slack last week". The window is explicit and validated,
uses each message's event/creation time rather than its last update time, and never falls
back to ``source_updated_at`` when a record has no declared event time.
"""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.routing import TimeWindow, detect_time_window
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
QUESTION = "What blockers were raised in the incident channel?"


def rec(source_id, text, updated, event=None, thread=None):
    return SimulatedSource(
        platform="slack", tenant_id="demo-a", source_id=source_id,
        source_kind="thread_message" if thread else "channel_message",
        version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://slack/{source_id}", parent_id="incident", thread_id=thread,
        source_updated_at=updated, event_at=event,
    )


def build_state(records):
    return SimulatedPlatformState(
        records=records,
        principal_map={"employee": {"slack": "slack-employee"}},
        slack_channel_grants={"incident": {"slack-employee"}},
        slack_thread_grants={"thread-incident": {"slack-employee"}},
        slack_dm_grants={},
        last_successful_sync={"slack": NOW},
        freshness_budget_seconds={"slack": 3600},
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g3time.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g3-time-audit-key-is-separate-1234567")
    audit.initialize()
    return AuthService(db), audit


# --- Window model ---

def test_time_window_requires_aware_ordered_bounds():
    with pytest.raises(ValidationError):
        TimeWindow(start=datetime(2026, 9, 20, 10, 0), end=NOW)
    with pytest.raises(ValidationError):
        TimeWindow(start=NOW, end=NOW - timedelta(days=1))


def test_time_window_is_half_open_on_boundary_dates():
    start = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    end = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
    window = TimeWindow(start=start, end=end)
    assert window.contains(start)
    assert not window.contains(end)
    assert window.contains(end - timedelta(seconds=1))
    assert not window.contains(start - timedelta(seconds=1))


# --- Detection ---

def test_detect_last_week_window():
    window = detect_time_window("What blockers were raised in Slack last week?", NOW)
    assert window == TimeWindow(start=NOW - timedelta(days=7), end=NOW)


def test_detect_past_n_days_window():
    window = detect_time_window("Any incident messages in the past 3 days?", NOW)
    assert window == TimeWindow(start=NOW - timedelta(days=3), end=NOW)


def test_detect_today_and_yesterday():
    today = detect_time_window("What happened today?", NOW)
    assert today.start == datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    assert today.end == NOW
    yesterday = detect_time_window("What happened yesterday?", NOW)
    assert yesterday.start == datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
    assert yesterday.end == datetime(2026, 9, 27, 0, 0, tzinfo=UTC)


def test_detect_returns_none_without_a_time_phrase():
    assert detect_time_window("What is the latest runbook?", NOW) is None


# --- Service integration ---

def test_window_excludes_out_of_range_event_times(system):
    auth, audit = system
    state = build_state([
        rec("msg-recent", "Incident blocker raised this week.", NOW - timedelta(days=1),
            event=NOW - timedelta(days=3)),
        rec("msg-old", "Incident blocker raised long ago.", NOW - timedelta(days=1),
            event=NOW - timedelta(days=20)),
    ])
    window = TimeWindow(start=NOW - timedelta(days=7), end=NOW)
    service = SimulatedQueryService(auth, audit, state, required_platforms=("slack",),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW,
                                       time_windows={"slack": window}))
    assert {c["source_id"] for c in packet["citations"]} == {"msg-recent"}
    assert packet["time_scope"]["applied"] is True
    assert packet["time_scope"]["platforms"]["slack"]["basis"] == "event_at"


def test_window_does_not_use_source_updated_at_as_a_substitute(system):
    auth, audit = system
    # The record's last update is inside the window, but it declares no event time.
    state = build_state([
        rec("msg-null", "Incident blocker with no declared event time.", NOW - timedelta(days=1),
            event=None),
    ])
    window = TimeWindow(start=NOW - timedelta(days=7), end=NOW)
    service = SimulatedQueryService(auth, audit, state, required_platforms=("slack",),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW,
                                       time_windows={"slack": window}))
    assert packet["citations"] == []
    assert packet["time_scope"]["platforms"]["slack"]["unscopable_ids"] == ["slack:msg-null:msg-null:v1"]
    assert packet["query_status"] in {"partial", "abstained"}


def test_unscopable_record_makes_the_platform_explicitly_incomplete(system):
    auth, audit = system
    state = build_state([
        rec("msg-recent", "Incident blocker raised this week.", NOW - timedelta(days=1),
            event=NOW - timedelta(days=3)),
        rec("msg-null", "Incident blocker with no declared event time.", NOW - timedelta(days=1),
            event=None),
    ])
    window = TimeWindow(start=NOW - timedelta(days=7), end=NOW)
    service = SimulatedQueryService(auth, audit, state, required_platforms=("slack",),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW,
                                       time_windows={"slack": window}))
    assert packet["query_status"] == "partial"
    assert "slack" in packet["incomplete_platforms"]
    assert {c["source_id"] for c in packet["citations"]} == {"msg-recent"}


def test_no_window_leaves_time_scope_unapplied(system):
    auth, audit = system
    state = build_state([
        rec("msg-recent", "Incident blocker raised this week.", NOW - timedelta(days=1),
            event=NOW - timedelta(days=3)),
    ])
    service = SimulatedQueryService(auth, audit, state, required_platforms=("slack",),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    assert packet["time_scope"]["applied"] is False
    assert packet["time_scope"]["platforms"] == {}
    assert packet["query_status"] == "answered"
