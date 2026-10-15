"""G2 deterministic synchronization for the four simulated platforms.

This module separates two states that G1 conflated:

* :class:`SimulatedUpstream` is the *upstream fixture state* — what each platform
  currently holds, expressed as an append-only change feed with pagination and
  injectable rate-limit, expiry and interruption faults.
* :class:`SyncIndex` is the *ingested/queryable snapshot* — the records, grants and
  watermarks the Internal Brain can actually answer from.

:class:`Synchronizer` moves changes from upstream to index. It applies a page set
atomically, advances a cursor and a successful watermark only after a complete run,
and never advertises current data after a failed or partial run. No live platform is
contacted; every result here is ``simulated``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Literal

from pydantic import Field

from aspire_brain.models import StrictModel
from aspire_brain.platforms.simulated import (
    Platform,
    SimulatedPlatformState,
    SimulatedSource,
    SourceFailure,
    grants_allow,
)

ChangeKind = Literal["upsert", "delete", "acl"]
SyncOutcome = Literal["completed", "partial", "interrupted", "rate_limited", "expired_access"]

#: The grant map field names each platform exposes. Kept distinct so a grant change
#: cannot be flattened across platforms.
GRANT_FIELDS: dict[str, tuple[str, ...]] = {
    "confluence": ("confluence_space_grants", "confluence_page_grants"),
    "jira": ("jira_project_grants", "jira_issue_grants"),
    "slack": ("slack_channel_grants", "slack_thread_grants", "slack_dm_grants"),
    "drive": ("drive_folder_grants", "drive_file_grants"),
}


class UpstreamRateLimited(Exception):
    """The upstream rejected a read because a rate limit was reached."""

    def __init__(self, retry_after_seconds: int = 1):
        super().__init__("Upstream rate limited")
        self.retry_after_seconds = retry_after_seconds


class UpstreamExpired(Exception):
    """The stored credential for the platform is no longer valid."""


class UpstreamInterrupted(Exception):
    """The upstream connection dropped part-way through a page sequence."""


class UpstreamChange(StrictModel):
    revision: int = Field(ge=1)
    platform: Platform
    kind: ChangeKind
    source_id: str = Field(min_length=1)
    record: SimulatedSource | None = None
    grant_field: str | None = None
    grant_key: str | None = None
    account_id: str | None = None
    allowed: bool | None = None
    upstream_updated_at: datetime


class ChangePage(StrictModel):
    items: list[UpstreamChange]
    next_offset: int
    has_more: bool
    upstream_revision: int


class SimulatedUpstream:
    """Mutable upstream fixture state with a paginated, fault-injectable change feed."""

    def __init__(self, *, platform: Platform, tenant_id: str, page_size: int = 2,
                 records=(), grants=None, retry_after_seconds: int = 1):
        if platform not in GRANT_FIELDS:
            raise ValueError("Unsupported simulated platform")
        if type(page_size) is not int or page_size < 1:
            raise ValueError("Page size must be a positive integer")
        self.platform = platform
        self.tenant_id = tenant_id
        self.page_size = page_size
        self.retry_after_seconds = retry_after_seconds
        self.records: dict[str, SimulatedSource] = {}
        self.grants: dict[str, dict[str, frozenset[str]]] = {field: {} for field in GRANT_FIELDS[platform]}
        self.revision = 0
        self.changes: list[UpstreamChange] = []
        # Injectable faults; all deterministic and controllable by the caller.
        self.rate_limit_calls = 0
        self.expired = False
        self.interrupt_after_pages: int | None = None
        self._pages_served = 0
        for record in records:
            self.upsert(record, at=record.source_updated_at)
        for field, mapping in (grants or {}).items():
            for key, accounts in mapping.items():
                for account in accounts:
                    self.set_grant(field, key, account, True, at=records[0].source_updated_at
                                   if records else _EPOCH)

    # -- upstream mutations (a platform-side write) --

    def _append(self, change: UpstreamChange) -> UpstreamChange:
        self.revision += 1
        committed = change.model_copy(update={"revision": self.revision})
        self.changes.append(committed)
        return committed

    def upsert(self, record: SimulatedSource, *, at: datetime) -> UpstreamChange:
        if record.platform != self.platform:
            raise ValueError("Record platform does not match upstream")
        self.records[record.source_id] = record
        return self._append(UpstreamChange(
            revision=1, platform=self.platform, kind="upsert", source_id=record.source_id,
            record=record, upstream_updated_at=at))

    def delete(self, source_id: str, *, at: datetime) -> UpstreamChange:
        self.records.pop(source_id, None)
        return self._append(UpstreamChange(
            revision=1, platform=self.platform, kind="delete", source_id=source_id,
            upstream_updated_at=at))

    def set_grant(self, field: str, key: str, account: str, allowed: bool, *, at: datetime):
        if field not in GRANT_FIELDS[self.platform]:
            raise ValueError("Grant field does not belong to platform")
        if not all(isinstance(value, str) and value for value in (key, account)):
            raise ValueError("Grant identifiers are required")
        accounts = set(self.grants[field].get(key, frozenset()))
        accounts.add(account) if allowed else accounts.discard(account)
        self.grants[field] = {**self.grants[field], key: frozenset(accounts)}
        return self._append(UpstreamChange(
            revision=1, platform=self.platform, kind="acl", source_id=key, grant_field=field,
            grant_key=key, account_id=account, allowed=allowed, upstream_updated_at=at))

    # -- query-time re-check --

    def verify(self, account_id: str | None, record: SimulatedSource) -> str:
        """Ask the upstream, as it is now, whether ``account_id`` may read ``record`` unchanged.

        Returns ``allowed``, ``denied`` (no longer readable, or deleted: the two are reported
        the same way) or ``changed`` (readable, but the upstream holds a different version).
        """
        current = self.records.get(record.source_id)
        if current is None or not grants_allow(
                current, account_id, lambda field, key: self.grants.get(field, {}).get(key, ())):
            return "denied"
        if (current.version_id != record.version_id
                or current.content_sha256 != record.content_sha256):
            return "changed"
        return "allowed"

    def poll(self, now: datetime) -> dict:
        """A fixture upstream records each change as it is made, so there is nothing to fetch."""
        return {"platform": self.platform, "outcome": "completed", "fetched": 0}

    # -- sync read path --

    def read_changes(self, *, since_revision: int, offset: int, limit: int) -> ChangePage:
        if self.expired:
            raise UpstreamExpired("Upstream credential expired")
        if self.rate_limit_calls > 0:
            self.rate_limit_calls -= 1
            raise UpstreamRateLimited(retry_after_seconds=self.retry_after_seconds)
        if self.interrupt_after_pages is not None and self._pages_served >= self.interrupt_after_pages:
            raise UpstreamInterrupted("Upstream connection interrupted")
        self._pages_served += 1
        pending = [change for change in self.changes if change.revision > since_revision]
        items = pending[offset:offset + limit]
        next_offset = offset + len(items)
        return ChangePage(items=items, next_offset=next_offset,
                          has_more=next_offset < len(pending), upstream_revision=self.revision)


class SyncIndex(SimulatedPlatformState):
    """The ingested/queryable snapshot, plus cursors, tombstones and a sync log."""

    def __init__(self, *, principal_map, freshness_budget_seconds, upstream, **grants):
        super().__init__(records=[], principal_map=principal_map, last_successful_sync={},
                         freshness_budget_seconds=freshness_budget_seconds, **grants)
        self.upstream: dict[str, SimulatedUpstream] = dict(upstream)
        self.cursors: dict[str, int] = {platform: 0 for platform in self.upstream}
        self.tombstones: dict[tuple[str, str], dict] = {}
        self.sync_log: list[dict] = []

    def pending_changes(self, platform: str) -> bool:
        upstream = self.upstream.get(platform)
        return upstream is not None and self.cursors.get(platform, 0) < upstream.revision

    def source_status(self, platform, now):
        status = super().source_status(platform, now)
        if status["freshness_state"] == "fresh" and self.pending_changes(platform):
            return {**status, "freshness_state": "stale", "pending_upstream_changes": True}
        return status


class Synchronizer:
    """Pull upstream changes into a :class:`SyncIndex` with all-or-nothing commits."""

    def __init__(self, index: SyncIndex, *, max_attempts: int = 3, max_pages: int | None = None):
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
            raise ValueError("max_pages must be a positive integer")
        self.index = index
        self.max_attempts = max_attempts
        self.max_pages = max_pages
        self.lock = RLock()

    def sync(self, platform: str, now: datetime) -> dict:
        upstream = self.index.upstream.get(platform)
        if upstream is None:
            raise ValueError(f"No upstream configured for {platform}")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Sync time needs a timezone")
        # Hold the index lock for the whole run so a concurrent sync or grant change
        # cannot be clobbered by this run's staged snapshot.
        with self.index.lock, self.lock:
            return self._run(platform, upstream, now)

    def _run(self, platform: str, upstream: SimulatedUpstream, now: datetime) -> dict:
        start_cursor = self.index.cursors.get(platform, 0)
        staged_records, staged_tombstones, staged_grants, counts = self._staging(platform)
        offset, pages, attempts, applied_revision = 0, 0, 1, start_cursor

        while True:
            try:
                page = upstream.read_changes(since_revision=start_cursor, offset=offset,
                                             limit=upstream.page_size)
            except UpstreamRateLimited as exc:
                if attempts >= self.max_attempts:
                    return self._record(platform, "rate_limited", counts, start_cursor,
                                        start_cursor, pages, attempts, now,
                                        error="rate_limited",
                                        retry_after_seconds=exc.retry_after_seconds)
                attempts += 1
                # Restart from the committed cursor with fresh staging; nothing is committed.
                staged_records, staged_tombstones, staged_grants, counts = self._staging(platform)
                offset, pages, applied_revision = 0, 0, start_cursor
                continue
            except UpstreamInterrupted:
                return self._record(platform, "interrupted", counts, start_cursor, start_cursor,
                                    pages, attempts, now, error="interrupted")
            except UpstreamExpired:
                self.index.set_failure(platform, SourceFailure(category="expired_access"))
                return self._record(platform, "expired_access", counts, start_cursor, start_cursor,
                                    pages, attempts, now, error="expired_access")
            pages += 1
            for change in page.items:
                self._apply(change, staged_records, staged_tombstones, staged_grants, counts)
                applied_revision = max(applied_revision, change.revision)
            if not page.has_more:
                break
            if self.max_pages is not None and pages >= self.max_pages:
                return self._record(platform, "partial", counts, start_cursor, start_cursor,
                                    pages, attempts, now, error="page_limit")
            offset = page.next_offset

        self.index.records = staged_records
        self.index.tombstones = staged_tombstones
        for field, grants in staged_grants.items():
            setattr(self.index, field, grants)
        # Advance only to the highest revision actually applied, so a change appended
        # during the run stays pending and cannot be silently reported as current.
        self.index.cursors[platform] = applied_revision
        self.index.last_successful_sync = {**self.index.last_successful_sync, platform: now}
        self.index.failures = {key: value for key, value in self.index.failures.items()
                               if key != platform}
        if counts["acl_changes"]:
            self.index.permission_revision += 1
        return self._record(platform, "completed", counts, start_cursor, applied_revision,
                            pages, attempts, now, watermark_advanced=True)

    def _staging(self, platform):
        return (dict(self.index.records), dict(self.index.tombstones),
                {field: dict(getattr(self.index, field)) for field in GRANT_FIELDS[platform]},
                {"created": 0, "updated": 0, "deleted": 0, "acl_changes": 0})

    @staticmethod
    def _apply(change, staged_records, staged_tombstones, staged_grants, counts):
        key = (change.platform, change.source_id)
        if change.kind == "upsert":
            existed = key in staged_records
            staged_records[key] = change.record
            staged_tombstones.pop(key, None)
            counts["updated" if existed else "created"] += 1
        elif change.kind == "delete":
            previous = staged_records.pop(key, None)
            if previous is not None:
                counts["deleted"] += 1
            staged_tombstones[key] = {
                "deleted_at": change.upstream_updated_at.isoformat(),
                "last_version_id": previous.version_id if previous else None,
            }
        else:
            grants = staged_grants.setdefault(change.grant_field, {})
            accounts = set(grants.get(change.grant_key, frozenset()))
            accounts.add(change.account_id) if change.allowed else accounts.discard(change.account_id)
            grants[change.grant_key] = frozenset(accounts)
            counts["acl_changes"] += 1

    def _record(self, platform, outcome, counts, cursor_before, cursor_after, pages, attempts,
                now, *, error=None, watermark_advanced=False, retry_after_seconds=None):
        run = {
            "platform": platform, "outcome": outcome, "attempts": attempts,
            "pages_read": pages, "created": counts["created"], "updated": counts["updated"],
            "deleted": counts["deleted"], "acl_changes": counts["acl_changes"],
            "changes_applied": sum(counts.values()),
            "cursor_before": cursor_before, "cursor_after": cursor_after,
            "watermark_advanced": watermark_advanced,
            "watermark": (self.index.last_successful_sync.get(platform).isoformat()
                          if self.index.last_successful_sync.get(platform) else None),
            "error": error, "retry_after_seconds": retry_after_seconds,
            "simulation_mode": "simulated", "time_mode": "simulated_elapsed",
            "wall_clock_seconds": None,
        }
        self.index.sync_log.append(run)
        return run


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def measure_freshness(*, platform: str, mutation_at: datetime, ingested_at: datetime,
                      observed_answer_at: datetime, budget_seconds: int,
                      first_post_sync_query_at: datetime | None = None,
                      first_post_sync_answer_contains_update: bool | None = None,
                      observed_answer_contains_update: bool | None = None,
                      observation_mode: str = "observed_query") -> dict:
    """Record a mutation -> ingestion -> observed answer measurement.

    ``propagation_seconds`` is the mutation-to-ingestion delay that the declared budget
    bounds. ``observed_answer_at`` is a query that was actually run, not the earliest
    moment an answer could have existed; the simulator samples rather than polling, so
    ``earliest_correct_answer_at`` stays ``null`` and ``earliest_visibility`` is
    ``"unknown"``. ``first_post_sync_query_at`` is the earliest query this fixture
    actually ran after ingestion, with the observed content flag beside it. Elapsed values
    are deterministic simulated time; wall-clock and live propagation remain unmeasured.
    """
    propagation = (ingested_at - mutation_at).total_seconds()
    within_budget = propagation <= budget_seconds
    return {
        "platform": platform, "simulation_mode": "simulated", "time_mode": "simulated_elapsed",
        "mutation_at": mutation_at.isoformat(), "ingested_at": ingested_at.isoformat(),
        "observed_answer_at": observed_answer_at.isoformat(),
        "observed_answer_contains_update": observed_answer_contains_update,
        "first_post_sync_query_at": (first_post_sync_query_at.isoformat()
                                     if first_post_sync_query_at else None),
        "first_post_sync_answer_contains_update": first_post_sync_answer_contains_update,
        "earliest_correct_answer_at": None, "earliest_visibility": "unknown",
        "observation_mode": observation_mode,
        "budget_seconds": budget_seconds, "propagation_seconds": propagation,
        "answer_latency_seconds": (observed_answer_at - mutation_at).total_seconds(),
        "within_budget": within_budget,
        "outcome": "within_budget" if within_budget else "over_budget",
        "wall_clock_seconds": None, "live_propagation_seconds": None,
    }
