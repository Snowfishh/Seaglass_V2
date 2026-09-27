"""G2 deterministic synchronization: upstream fixture state vs indexed snapshot.

These tests specify incremental create/update/delete/ACL processing, pagination,
idempotent replay, interrupted sync, bounded rate-limit retries, expired access and
recovery for the four simulated platforms. They are written before the implementation.
"""

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
)
from aspire_brain.platforms.sync import (
    SimulatedUpstream,
    Synchronizer,
    SyncIndex,
    UpstreamInterrupted,
    UpstreamRateLimited,
)

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
SENTINEL = "FORBIDDEN_SYNC_SENTINEL"

CONFLUENCE_GRANTS = {
    "confluence_space_grants": {"payment-gateway": {"conf-employee"}},
    "confluence_page_grants": {"RUNBOOK-PAY": {"conf-employee"}},
}
JIRA_GRANTS = {
    "jira_project_grants": {"OPS": {"jira-employee"}},
    "jira_issue_grants": {"OPS-17": {"jira-employee"}},
}
SLACK_GRANTS = {
    "slack_channel_grants": {"p17-ops": {"slack-employee"}},
    "slack_thread_grants": {"thread-17": {"slack-employee"}},
}
DRIVE_GRANTS = {
    "drive_folder_grants": {"ops-docs": {"drive-employee"}},
    "drive_file_grants": {"postmortem-1": {"drive-employee"}},
}
ACCOUNTS = {"confluence": "conf-employee", "jira": "jira-employee",
            "slack": "slack-employee", "drive": "drive-employee"}


def rec(platform, source_id, kind, parent, text, updated=T0, thread=None, version="v1"):
    return SimulatedSource(
        platform=platform,
        tenant_id="demo-a",
        source_id=source_id,
        source_kind=kind,
        version_id=f"{source_id}:{version}",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        locator=f"simulated://{platform}/{source_id}",
        parent_id=parent,
        thread_id=thread,
        source_updated_at=updated,
    )


def make_index(*upstreams, budgets=None):
    budgets = budgets or {platform: 3600 for platform in ALL_PLATFORMS}
    return SyncIndex(
        principal_map={"employee": dict(ACCOUNTS)},
        freshness_budget_seconds=budgets,
        upstream={upstream.platform: upstream for upstream in upstreams},
    )


ALL_PLATFORMS = ("confluence", "jira", "slack", "drive")


def confluence_upstream(page_size=2, records=None, grants=None):
    return SimulatedUpstream(
        platform="confluence", tenant_id="demo-a", page_size=page_size,
        records=records if records is not None else [
            rec("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway",
                "Payment incident runbook: step 1 restart service.")],
        grants=grants if grants is not None else CONFLUENCE_GRANTS,
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g2.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g2-test-audit-key-is-separate-123456")
    audit.initialize()
    return AuthService(db), audit


# --- Upstream/index separation ---

def test_upstream_state_is_separate_from_indexed_snapshot():
    upstream = confluence_upstream()
    index = make_index(upstream)
    assert index.records == {}
    assert not index.can_read({"id": "employee", "active": True, "tenant_id": "demo-a"},
                              "confluence", "RUNBOOK-PAY")
    Synchronizer(index).sync("confluence", T0)
    assert ("confluence", "RUNBOOK-PAY") in index.records


def test_upstream_update_is_invisible_until_sync():
    upstream = confluence_upstream()
    index = make_index(upstream)
    syncer = Synchronizer(index)
    syncer.sync("confluence", T0)
    before = index.records[("confluence", "RUNBOOK-PAY")].text
    upstream.upsert(rec("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway",
                        "Payment incident runbook: step 1 restart service; step 2 enable failover.",
                        updated=datetime(2026, 9, 27, 13, 0, tzinfo=UTC), version="v2"),
                    at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    assert index.records[("confluence", "RUNBOOK-PAY")].text == before
    assert index.pending_changes("confluence") is True
    syncer.sync("confluence", datetime(2026, 9, 27, 13, 10, tzinfo=UTC))
    assert "failover" in index.records[("confluence", "RUNBOOK-PAY")].text


# --- Create events for all four platforms ---

def test_initial_sync_ingests_all_four_platforms():
    upstreams = {
        "confluence": confluence_upstream(records=[
            rec("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway", "runbook")],
            grants=CONFLUENCE_GRANTS),
        "jira": SimulatedUpstream(platform="jira", tenant_id="demo-a",
                                  records=[rec("jira", "OPS-17", "issue", "OPS", "issue body")],
                                  grants=JIRA_GRANTS),
        "slack": SimulatedUpstream(platform="slack", tenant_id="demo-a",
                                   records=[rec("slack", "msg-17", "thread_message", "p17-ops",
                                                "thread body", thread="thread-17")],
                                   grants=SLACK_GRANTS),
        "drive": SimulatedUpstream(platform="drive", tenant_id="demo-a",
                                   records=[rec("drive", "postmortem-1", "folder_file", "ops-docs",
                                                "postmortem body")],
                                   grants=DRIVE_GRANTS),
    }
    index = make_index(*upstreams.values())
    syncer = Synchronizer(index)
    for platform in ALL_PLATFORMS:
        run = syncer.sync(platform, T0)
        assert run["outcome"] == "completed"
        assert run["created"] == 1
        assert run["watermark_advanced"] is True
    principal = {"id": "employee", "active": True, "tenant_id": "demo-a"}
    assert index.can_read(principal, "confluence", "RUNBOOK-PAY")
    assert index.can_read(principal, "jira", "OPS-17")
    assert index.can_read(principal, "slack", "msg-17")
    assert index.can_read(principal, "drive", "postmortem-1")


# --- Pagination ---

def test_pagination_continues_until_cursor_reaches_upstream_revision():
    records = [rec("confluence", f"PAGE-{i}", "space_page", "payment-gateway", f"page {i} text")
               for i in range(5)]
    upstream = SimulatedUpstream(platform="confluence", tenant_id="demo-a", page_size=2,
                                 records=records, grants={})
    index = make_index(upstream)
    run = Synchronizer(index).sync("confluence", T0)
    assert run["pages_read"] == 3
    assert run["created"] == 5
    assert index.cursors["confluence"] == upstream.revision
    assert len(index.records) == 5


def test_partial_page_limit_does_not_commit():
    records = [rec("confluence", f"PAGE-{i}", "space_page", "payment-gateway", f"page {i} text")
               for i in range(5)]
    upstream = SimulatedUpstream(platform="confluence", tenant_id="demo-a", page_size=2,
                                 records=records, grants={})
    index = make_index(upstream)
    run = Synchronizer(index, max_pages=1).sync("confluence", T0)
    assert run["outcome"] == "partial"
    assert run["watermark_advanced"] is False
    assert index.records == {}
    assert index.cursors["confluence"] == 0


# --- Idempotency ---

def test_repeated_delivery_is_idempotent():
    upstream = confluence_upstream()
    index = make_index(upstream)
    syncer = Synchronizer(index)
    first = syncer.sync("confluence", T0)
    revision_after_first = index.permission_revision
    second = syncer.sync("confluence", T0)
    assert first["created"] == 1
    assert second["changes_applied"] == 0
    assert second["outcome"] == "completed"
    assert index.permission_revision == revision_after_first
    assert index.records[("confluence", "RUNBOOK-PAY")].version_id == "RUNBOOK-PAY:v1"


# --- Update ---

def test_update_replaces_version_hash_and_text():
    upstream = confluence_upstream()
    index = make_index(upstream)
    syncer = Synchronizer(index)
    syncer.sync("confluence", T0)
    new_text = "Payment incident runbook: step 1 restart service; step 2 enable failover."
    upstream.upsert(rec("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway", new_text,
                        updated=datetime(2026, 9, 27, 13, 0, tzinfo=UTC), version="v2"),
                    at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    run = syncer.sync("confluence", datetime(2026, 9, 27, 13, 10, tzinfo=UTC))
    assert run["updated"] == 1
    record = index.records[("confluence", "RUNBOOK-PAY")]
    assert record.version_id == "RUNBOOK-PAY:v2"
    assert record.text == new_text
    assert record.content_sha256 == hashlib.sha256(new_text.encode()).hexdigest()


# --- Delete / tombstone ---

def test_delete_is_tombstoned_and_not_queryable():
    upstream = confluence_upstream()
    index = make_index(upstream)
    syncer = Synchronizer(index)
    syncer.sync("confluence", T0)
    upstream.delete("RUNBOOK-PAY", at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    run = syncer.sync("confluence", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))
    assert run["deleted"] == 1
    assert ("confluence", "RUNBOOK-PAY") not in index.records
    assert ("confluence", "RUNBOOK-PAY") in index.tombstones
    principal = {"id": "employee", "active": True, "tenant_id": "demo-a"}
    assert not index.can_read(principal, "confluence", "RUNBOOK-PAY")
    assert index.candidates(principal, "confluence", "payment runbook") == []


# --- ACL changes ---

def test_acl_change_revokes_indexed_access():
    upstream = confluence_upstream()
    index = make_index(upstream)
    syncer = Synchronizer(index)
    syncer.sync("confluence", T0)
    principal = {"id": "employee", "active": True, "tenant_id": "demo-a"}
    assert index.can_read(principal, "confluence", "RUNBOOK-PAY")
    before_revision = index.permission_revision
    upstream.set_grant("confluence_page_grants", "RUNBOOK-PAY", "conf-employee", False,
                       at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    run = syncer.sync("confluence", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))
    assert run["acl_changes"] == 1
    assert not index.can_read(principal, "confluence", "RUNBOOK-PAY")
    assert index.permission_revision > before_revision


# --- Interrupted sync ---

def test_interrupted_sync_does_not_advance_watermark_or_cursor():
    records = [rec("confluence", f"PAGE-{i}", "space_page", "payment-gateway", f"page {i} text")
               for i in range(5)]
    upstream = SimulatedUpstream(platform="confluence", tenant_id="demo-a", page_size=2,
                                 records=records, grants=CONFLUENCE_GRANTS)
    index = make_index(upstream)
    syncer = Synchronizer(index)
    syncer.sync("confluence", T0)
    syncer2 = Synchronizer(index)
    upstream.interrupt_after_pages = 1
    upstream.upsert(rec("confluence", "PAGE-0", "space_page", "payment-gateway", "changed text",
                        updated=datetime(2026, 9, 27, 13, 0, tzinfo=UTC), version="v2"),
                    at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    watermark_before = index.last_successful_sync["confluence"]
    run = syncer2.sync("confluence", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))
    assert run["outcome"] == "interrupted"
    assert run["watermark_advanced"] is False
    assert index.last_successful_sync["confluence"] == watermark_before
    assert index.cursors["confluence"] == 0 or index.records[("confluence", "PAGE-0")].version_id == "PAGE-0:v1"


def test_recovery_after_interrupt_completes_and_applies_changes():
    records = [rec("confluence", f"PAGE-{i}", "space_page", "payment-gateway", f"page {i} text")
               for i in range(5)]
    upstream = SimulatedUpstream(platform="confluence", tenant_id="demo-a", page_size=2,
                                 records=records, grants=CONFLUENCE_GRANTS)
    index = make_index(upstream)
    Synchronizer(index).sync("confluence", T0)
    upstream.interrupt_after_pages = 1
    upstream.upsert(rec("confluence", "PAGE-0", "space_page", "payment-gateway", "changed text",
                        updated=datetime(2026, 9, 27, 13, 0, tzinfo=UTC), version="v2"),
                    at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    assert Synchronizer(index).sync("confluence", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))["outcome"] == "interrupted"
    upstream.interrupt_after_pages = None
    run = Synchronizer(index).sync("confluence", datetime(2026, 9, 27, 13, 10, tzinfo=UTC))
    assert run["outcome"] == "completed"
    assert run["updated"] == 1
    assert index.records[("confluence", "PAGE-0")].version_id == "PAGE-0:v2"
    assert index.cursors["confluence"] == upstream.revision


# --- Rate limits ---

def test_bounded_rate_limit_retry_recovers_within_attempts():
    upstream = confluence_upstream()
    index = make_index(upstream)
    upstream.rate_limit_calls = 1
    run = Synchronizer(index, max_attempts=3).sync("confluence", T0)
    assert run["outcome"] == "completed"
    assert run["attempts"] == 2
    assert index.cursors["confluence"] == upstream.revision


def test_rate_limit_retry_does_not_inflate_counts():
    upstream = confluence_upstream()
    index = make_index(upstream)
    upstream.rate_limit_calls = 1
    run = Synchronizer(index, max_attempts=3).sync("confluence", T0)
    assert run["outcome"] == "completed"
    assert run["attempts"] == 2
    assert run["created"] == 1
    assert run["updated"] == 0
    assert run["changes_applied"] == 3


def test_exhausted_rate_limit_retries_do_not_commit():
    upstream = confluence_upstream()
    index = make_index(upstream)
    upstream.rate_limit_calls = 99
    run = Synchronizer(index, max_attempts=3).sync("confluence", T0)
    assert run["outcome"] == "rate_limited"
    assert run["attempts"] == 3
    assert run["watermark_advanced"] is False
    assert index.records == {}
    assert index.last_successful_sync.get("confluence") is None


class RacingUpstream(SimulatedUpstream):
    """Appends one change immediately after serving a page, as a live platform could."""

    def __init__(self, *args, late=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._late = late
        self._raced = False

    def read_changes(self, *, since_revision, offset, limit):
        page = super().read_changes(since_revision=since_revision, offset=offset, limit=limit)
        if not self._raced and self._late is not None:
            self._raced = True
            self.upsert(self._late, at=self._late.source_updated_at)
        return page


def test_change_appended_mid_sync_stays_pending_and_cursor_stops_at_applied_revision():
    late = rec("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway",
               "Payment incident runbook: step 1 restart service; step 2 enable failover.",
               updated=datetime(2026, 9, 27, 13, 0, tzinfo=UTC), version="v2")
    upstream = RacingUpstream(
        platform="confluence", tenant_id="demo-a", page_size=10,
        records=[rec("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway",
                     "Payment incident runbook: step 1 restart service.")],
        grants=CONFLUENCE_GRANTS, late=late)
    index = make_index(upstream, budgets={"confluence": 7200})
    initial_revision = upstream.revision
    run = Synchronizer(index).sync("confluence", T0)
    assert run["outcome"] == "completed"
    assert run["cursor_after"] == initial_revision
    assert index.cursors["confluence"] == initial_revision
    assert upstream.revision > initial_revision
    assert index.pending_changes("confluence") is True
    assert index.source_status("confluence", T0)["freshness_state"] == "stale"
    assert index.records[("confluence", "RUNBOOK-PAY")].version_id == "RUNBOOK-PAY:v1"


# --- Expired access ---

def test_expired_access_marks_platform_failed_without_commit():
    upstream = confluence_upstream()
    index = make_index(upstream)
    upstream.expired = True
    run = Synchronizer(index).sync("confluence", T0)
    assert run["outcome"] == "expired_access"
    assert index.records == {}
    assert index.source_status("confluence", T0)["freshness_state"] == "failed"
    assert index.source_status("confluence", T0)["source_failure"] == "expired_access"


def test_pending_change_is_stale_and_never_silently_current():
    upstream = confluence_upstream()
    index = make_index(upstream, budgets={"confluence": 7200})
    Synchronizer(index).sync("confluence", T0)
    upstream.upsert(rec("confluence", "RUNBOOK-PAY", "space_page", "payment-gateway",
                        "Payment incident runbook: step 1 restart service; step 2 enable failover.",
                        updated=datetime(2026, 9, 27, 13, 0, tzinfo=UTC), version="v2"),
                    at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    status = index.source_status("confluence", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))
    assert status["freshness_state"] == "stale"
    assert status.get("pending_upstream_changes") is True


# --- Query path against a synchronized index ---

def test_query_uses_indexed_snapshot_and_denies_tombstoned_saved_packet(system):
    auth, audit = system
    upstream = confluence_upstream()
    index = make_index(upstream)
    syncer = Synchronizer(index)
    syncer.sync("confluence", T0)
    service = SimulatedQueryService(auth, audit, index, required_platforms=("confluence",),
                                    clock=lambda: T0)
    packet = asyncio.run(service.query("employee", "What is the payment incident runbook?", T0))
    assert packet["query_status"] == "answered"
    upstream.delete("RUNBOOK-PAY", at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    syncer.sync("confluence", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])
    after = asyncio.run(service.query("employee", "What is the payment incident runbook?",
                                      datetime(2026, 9, 27, 13, 5, tzinfo=UTC)))
    assert after["query_status"] == "abstained"
    assert after["citations"] == []


def test_revoked_acl_change_blocks_saved_packet(system):
    auth, audit = system
    upstream = confluence_upstream()
    index = make_index(upstream)
    syncer = Synchronizer(index)
    syncer.sync("confluence", T0)
    service = SimulatedQueryService(auth, audit, index, required_platforms=("confluence",),
                                    clock=lambda: T0)
    packet = asyncio.run(service.query("employee", "What is the payment incident runbook?", T0))
    upstream.set_grant("confluence_page_grants", "RUNBOOK-PAY", "conf-employee", False,
                       at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    syncer.sync("confluence", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))
    with pytest.raises(AccessDenied):
        service.packet("employee", packet["request_id"])


def test_four_platform_delete_events_apply_independently():
    upstreams = {
        "confluence": confluence_upstream(),
        "jira": SimulatedUpstream(platform="jira", tenant_id="demo-a",
                                  records=[rec("jira", "OPS-17", "issue", "OPS", "issue body")],
                                  grants=JIRA_GRANTS),
        "slack": SimulatedUpstream(platform="slack", tenant_id="demo-a",
                                   records=[rec("slack", "msg-17", "thread_message", "p17-ops",
                                                "thread body", thread="thread-17")],
                                   grants=SLACK_GRANTS),
        "drive": SimulatedUpstream(platform="drive", tenant_id="demo-a",
                                   records=[rec("drive", "postmortem-1", "folder_file", "ops-docs",
                                                "postmortem body")],
                                   grants=DRIVE_GRANTS),
    }
    index = make_index(*upstreams.values())
    syncer = Synchronizer(index)
    for platform in ALL_PLATFORMS:
        syncer.sync(platform, T0)
    assert len(index.records) == 4
    upstreams["drive"].delete("postmortem-1", at=datetime(2026, 9, 27, 13, 0, tzinfo=UTC))
    run = syncer.sync("drive", datetime(2026, 9, 27, 13, 5, tzinfo=UTC))
    assert run["deleted"] == 1
    assert ("drive", "postmortem-1") not in index.records
    assert ("drive", "postmortem-1") in index.tombstones
    # Other platforms are untouched.
    assert ("confluence", "RUNBOOK-PAY") in index.records
    assert ("jira", "OPS-17") in index.records
    assert ("slack", "msg-17") in index.records


def test_unknown_permission_state_fails_closed():
    upstream = confluence_upstream(grants={})
    index = make_index(upstream)
    Synchronizer(index).sync("confluence", T0)
    principal = {"id": "employee", "active": True, "tenant_id": "demo-a"}
    assert not index.can_read(principal, "confluence", "RUNBOOK-PAY")


def test_upstream_change_feed_is_read_only_and_bounded():
    records = [rec("confluence", f"PAGE-{i}", "space_page", "payment-gateway", f"page {i} text")
               for i in range(2)]
    upstream = SimulatedUpstream(platform="confluence", tenant_id="demo-a", page_size=1,
                                 records=records, grants={})
    page = upstream.read_changes(since_revision=0, offset=0, limit=1)
    assert page.has_more is True
    assert page.next_offset == 1
    assert page.upstream_revision == upstream.revision
    second = upstream.read_changes(since_revision=0, offset=1, limit=1)
    assert second.has_more is False


def test_rate_limited_exception_carries_retry_hint():
    upstream = confluence_upstream()
    upstream.rate_limit_calls = 1
    upstream.retry_after_seconds = 7
    with pytest.raises(UpstreamRateLimited) as error:
        upstream.read_changes(since_revision=0, offset=0, limit=1)
    assert error.value.retry_after_seconds == 7


def test_interrupted_exception_is_raised_by_upstream():
    upstream = confluence_upstream()
    upstream.interrupt_after_pages = 0
    with pytest.raises(UpstreamInterrupted):
        upstream.read_changes(since_revision=0, offset=0, limit=1)


def test_index_remains_a_platform_state_for_the_query_service():
    upstream = confluence_upstream()
    index = make_index(upstream)
    assert isinstance(index, SimulatedPlatformState)
    assert index.permission_revision == 0
    assert json.dumps(index.source_status("confluence", T0)) is not None
    assert SENTINEL not in json.dumps(index.source_status("confluence", T0))
