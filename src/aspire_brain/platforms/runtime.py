"""The running four-platform index: one shared snapshot, a sync loop and freshness evidence.

Typed questions used to build a fresh index for every request on a fixed clock. That kept
requests apart, but nothing could change between two questions: no update could arrive, and
no permission could be removed. :class:`PlatformRuntime` keeps one synchronized index per
tenant for the life of the process and runs the synchronizer on a declared interval, so:

* a change made upstream becomes answerable at the next sync, and the runtime records how long
  that took in real elapsed seconds;
* a permission removed upstream is enforced at query time by asking the upstream again about
  each record before it is quoted, and is folded into the index at the next sync;
* a platform whose last successful sync is older than its freshness budget, or that has
  changes waiting, is reported stale and is not quoted as current.

Two upstream kinds plug in. ``fixture`` is the fictional fintech bundle held in memory; its
clock starts at the bundle's authored time and then advances in real time, and a platform
administrator can apply the bundle's runbook revision or remove a restricted grant to watch
both take effect. ``connectors`` reads real Confluence, Jira, Slack and Drive accounts through
:mod:`aspire_brain.platforms.connected` on the wall clock.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Lock

from aspire_brain.platforms.simulated import ALL_PLATFORMS
from aspire_brain.platforms.sync import Synchronizer, SyncIndex

logger = logging.getLogger(__name__)

#: Default seconds between scheduled syncs, well inside the one-hour freshness budget.
DEFAULT_SYNC_INTERVAL_SECONDS = 300
DEFAULT_FRESHNESS_BUDGET_SECONDS = 3600
#: Wall-clock seconds one query-time re-check may spend asking the source platforms. A record
#: not reached in time is "unverifiable" and so is withheld, never served unchecked.
DEFAULT_VERIFY_BUDGET_SECONDS = 20.0


class FixtureClock:
    """Starts at the fixture's authored time and then advances in real time."""

    mode = "fixture_clock"

    def __init__(self, start: datetime, *, monotonic=time.monotonic):
        self.start = start
        self._monotonic = monotonic
        self._origin = monotonic()

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self._monotonic() - self._origin)


class WallClock:
    mode = "wall_clock"

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)


class PlatformRuntime:
    def __init__(self, *, tenant_id: str, index: SyncIndex, clock, source: str,
                 sync_interval_seconds: int = DEFAULT_SYNC_INTERVAL_SECONDS,
                 fixture_updates=(), restricted=(), monotonic=time.monotonic,
                 verify_budget_seconds: float = DEFAULT_VERIFY_BUDGET_SECONDS):
        if type(sync_interval_seconds) is not int or sync_interval_seconds < 0:
            raise ValueError("Sync interval must be a non-negative integer")
        if (isinstance(verify_budget_seconds, bool)
                or not isinstance(verify_budget_seconds, (int, float))
                or not 0 < verify_budget_seconds <= 120):
            raise ValueError("Verify budget must be between 0 and 120 seconds")
        budgets = set(index.freshness_budget_seconds.values())
        if sync_interval_seconds and budgets and sync_interval_seconds >= min(budgets):
            raise ValueError("Sync interval must be shorter than the freshness budget")
        self.tenant_id = tenant_id
        self.index = index
        self.clock = clock
        self.source = source
        self.sync_interval_seconds = sync_interval_seconds
        self.verify_budget_seconds = verify_budget_seconds
        self.synchronizer = Synchronizer(index, max_attempts=2)
        self.fixture_updates = tuple(fixture_updates)
        self.restricted = tuple(restricted)
        self._monotonic = monotonic
        self._sync_lock = Lock()
        self.runs: deque = deque(maxlen=40)
        self.measurements: deque = deque(maxlen=40)
        #: Upstream changes made through the fixture controls, not yet ingested:
        #: (platform, revision, monotonic time, clock time, description)
        self._pending_marks: list[tuple] = []
        self.next_sync_at: datetime | None = None
        self.started_at = clock.now()

    @property
    def platforms(self):
        return [platform for platform in ALL_PLATFORMS if platform in self.index.upstream]

    # -- synchronization ---------------------------------------------------------------

    def sync_all(self, reason: str = "scheduled") -> list[dict]:
        """Poll and synchronize every platform once. One sync runs at a time."""
        results = []
        with self._sync_lock:
            for platform in self.platforms:
                upstream = self.index.upstream[platform]
                started = self.clock.now()
                wall = self._monotonic()
                before = {key: record for key, record in self.index.records.items()
                          if key[0] == platform}
                previous_sync = self.index.last_successful_sync.get(platform)
                poll = upstream.poll(started)
                run = self.synchronizer.sync(platform, started)
                run = {**run, "reason": reason, "poll": poll,
                       "time_mode": getattr(self.clock, "mode", "wall_clock"),
                       "wall_clock_seconds": round(self._monotonic() - wall, 3)}
                if run["outcome"] == "completed":
                    # A change is answerable once the crawl that read it has finished, not when
                    # the crawl began: an item edited mid-crawl would otherwise show a negative lag.
                    self._measure(platform, run, self.clock.now(), before, previous_sync)
                self.runs.append(run)
                results.append(run)
            if self.sync_interval_seconds:
                self.next_sync_at = self.clock.now() + timedelta(seconds=self.sync_interval_seconds)
        return results

    def _budget(self, platform):
        return self.index.freshness_budget_seconds.get(platform, DEFAULT_FRESHNESS_BUDGET_SECONDS)

    def _measure(self, platform, run, ingested_at, before, previous_sync=None):
        budget = self._budget(platform)
        now_wall = self._monotonic()
        remaining = []
        for mark in self._pending_marks:
            mark_platform, revision, wall, changed_at, description = mark
            if mark_platform != platform or revision > run["cursor_after"]:
                remaining.append(mark)
                continue
            elapsed = round(now_wall - wall, 3)
            self.measurements.append({
                "platform": platform, "change": description, "basis": "measured_elapsed",
                "changed_at": changed_at.isoformat(), "ingested_at": ingested_at.isoformat(),
                "propagation_seconds": elapsed, "budget_seconds": budget,
                "within_budget": elapsed <= budget, "time_mode": "wall_clock_elapsed"})
        self._pending_marks = remaining
        if self.source != "connectors" or previous_sync is None:
            return  # the initial load is not a propagation measurement
        # A live platform reports when each item last changed; the gap to ingestion is the
        # propagation delay this sync achieved for that item. Only an item modified since the
        # previous sync began counts. An old item that merely became visible (newly shared, or
        # its permissions changed) did not change, so its age is not a propagation delay.
        for key, record in self.index.records.items():
            if (key[0] != platform or before.get(key) == record
                    or record.source_updated_at <= previous_sync):
                continue
            lag = round((ingested_at - record.source_updated_at).total_seconds(), 3)
            if lag < 0:
                continue  # the platform's clock is ahead of ours; no honest figure exists
            self.measurements.append({
                "platform": platform, "change": f"{record.source_kind} updated",
                "source_id": record.source_id, "basis": "platform_modified_time",
                "changed_at": record.source_updated_at.isoformat(),
                "ingested_at": ingested_at.isoformat(), "propagation_seconds": lag,
                "budget_seconds": budget, "within_budget": lag <= budget,
                "time_mode": "wall_clock"})

    async def run_forever(self):
        """Sync on the declared interval until cancelled. A failed run is logged and retried."""
        if not self.sync_interval_seconds:
            return
        while True:
            await asyncio.sleep(self.sync_interval_seconds)
            try:
                await asyncio.to_thread(self.sync_all, "scheduled")
            except Exception as exc:  # keep the loop alive; the status shows the gap
                logger.warning("Scheduled platform sync failed: %s", type(exc).__name__)

    # -- query-time re-check -----------------------------------------------------------

    def verifier(self, principal, records) -> dict:
        """Ask each record's source platform about it, within one overall time budget.

        Connector checks are blocking network calls, so callers on the event loop run this in a
        worker thread. Once the budget is spent, the remaining records are ``unverifiable``.
        """
        outcomes = {}
        deadline = self._monotonic() + self.verify_budget_seconds
        for record in records:
            upstream = self.index.upstream.get(record.platform)
            account = self.index.principal_map.get(principal["id"], {}).get(record.platform)
            if self._monotonic() >= deadline:
                outcome = "unverifiable"
            else:
                try:
                    outcome = upstream.verify(account, record) if upstream else "unverifiable"
                except Exception:
                    outcome = "unverifiable"
            outcomes[(record.platform, record.source_id)] = outcome
        return outcomes

    # -- reporting ---------------------------------------------------------------------

    def status(self) -> dict:
        now = self.clock.now()
        platforms = {}
        for platform in self.platforms:
            state = self.index.source_status(platform, now)
            last = next((run for run in reversed(self.runs) if run["platform"] == platform), None)
            platforms[platform] = {
                **state,
                "pending_upstream_changes": self.index.pending_changes(platform),
                "records": sum(1 for key in self.index.records if key[0] == platform),
                "last_run": None if last is None else {
                    key: last.get(key) for key in ("outcome", "reason", "error", "created",
                                                   "updated", "deleted", "acl_changes",
                                                   "watermark", "wall_clock_seconds")},
            }
        return {
            "tenant_id": self.tenant_id, "source": self.source,
            "clock": {"mode": getattr(self.clock, "mode", "wall_clock"), "now": now.isoformat(),
                      "started_at": self.started_at.isoformat()},
            "sync_interval_seconds": self.sync_interval_seconds,
            "next_sync_at": self.next_sync_at.isoformat() if self.next_sync_at else None,
            "freshness_budget_seconds": {platform: self._budget(platform)
                                         for platform in self.platforms},
            "platforms": platforms,
            "measurements": list(self.measurements)[-10:],
            "fixture_controls": self.source == "fixture",
            "note": ("Freshness is measured in real elapsed seconds from the change to the sync "
                     "that ingested it. A permission removed upstream is enforced at query time "
                     "before the next sync."),
        }

    # -- fixture controls (simulate a platform-side change) ----------------------------

    def _mark(self, platform, description):
        upstream = self.index.upstream[platform]
        self._pending_marks.append((platform, upstream.revision, self._monotonic(),
                                    self.clock.now(), description))

    def apply_fixture_updates(self) -> list[str]:
        if self.source != "fixture":
            raise ValueError("Fixture controls apply only to the fixture source")
        applied = []
        for record in self.fixture_updates:
            upstream = self.index.upstream[record.platform]
            current = upstream.records.get(record.source_id)
            if current is not None and current.version_id == record.version_id:
                continue
            upstream.upsert(record, at=self.clock.now())
            self._mark(record.platform, f"{record.source_id} revised to {record.version_id}")
            applied.append(record.source_id)
        return applied

    def set_restricted_access(self, principal_id: str, allowed: bool) -> list[str]:
        """Grant or remove one user's access to every restricted fixture record, upstream."""
        if self.source != "fixture":
            raise ValueError("Fixture controls apply only to the fixture source")
        changed = []
        for record in self.restricted:
            upstream = self.index.upstream[record.platform]
            account = self.index.principal_map.get(principal_id, {}).get(record.platform)
            if account is None:
                raise ValueError("Unknown principal for this tenant")
            field = {"confluence": "confluence_page_grants",
                     "drive": "drive_file_grants"}[record.platform]
            has = account in upstream.grants.get(field, {}).get(record.source_id, ())
            if has == allowed:
                continue
            upstream.set_grant(field, record.source_id, account, allowed, at=self.clock.now())
            self._mark(record.platform, f"{principal_id} {'granted' if allowed else 'removed'} "
                                        f"on {record.source_id}")
            changed.append(record.source_id)
        return changed


# -- factories ----------------------------------------------------------------------------

def fixture_runtime(root, *, start: datetime, tenant_id: str = "fintech-demo",
                    sync_interval_seconds: int = DEFAULT_SYNC_INTERVAL_SECONDS,
                    clock=None, monotonic=time.monotonic) -> PlatformRuntime:
    """The fictional fintech bundle, synchronized once at ``start`` and kept for the process."""
    from aspire_brain.platforms.connectors.offline import fixture_bundle, load_fixture_index

    clock = clock or FixtureClock(start, monotonic=monotonic)
    index = load_fixture_index(root, now=start)
    initial, updates = fixture_bundle(root)
    runtime = PlatformRuntime(
        tenant_id=tenant_id, index=index, clock=clock, source="fixture",
        sync_interval_seconds=sync_interval_seconds, fixture_updates=updates,
        restricted=[record for record in initial if record.source_kind.endswith("_restricted")],
        monotonic=monotonic)
    runtime.runs.extend({**run, "reason": "startup"} for run in index.sync_log)
    if sync_interval_seconds:
        runtime.next_sync_at = clock.now() + timedelta(seconds=sync_interval_seconds)
    return runtime


def connector_runtime(config, tokens, *, sync_interval_seconds: int = DEFAULT_SYNC_INTERVAL_SECONDS,
                      freshness_budget_seconds: int = DEFAULT_FRESHNESS_BUDGET_SECONDS,
                      transport_for=None, clock=None, monotonic=time.monotonic) -> PlatformRuntime:
    """Real platform accounts behind the same index. The caller runs the first sync."""
    from aspire_brain.platforms.connected import build_upstreams, principal_map

    upstreams = build_upstreams(config, tokens, transport_for=transport_for)
    index = SyncIndex(principal_map=principal_map(config),
                      freshness_budget_seconds={platform: freshness_budget_seconds
                                                for platform in upstreams},
                      upstream=upstreams)
    return PlatformRuntime(tenant_id=config.tenant_id, index=index, clock=clock or WallClock(),
                           source="connectors", sync_interval_seconds=sync_interval_seconds,
                           monotonic=monotonic)
