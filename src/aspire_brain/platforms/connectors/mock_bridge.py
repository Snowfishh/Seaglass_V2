"""Offline HTTP-adapter rehearsal through the existing simulated query/audit path.

This bridge deliberately refuses live-mode sessions. It is not a production ACL cache:
successful requester-scoped mock reads become grants only in an explicitly simulated
state. Every refresh rebuilds that state; any failure clears it, including old packet
dependencies. Real app identity, live revocation and synchronization require separate work.
"""

from dataclasses import dataclass
from datetime import datetime

from aspire_brain.platforms.simulated import SimulatedPlatformState, SimulatedSource, SourceFailure

from .core import ConnectorDocument, ConnectorError, SourceRef, SourceUnavailable

_GRANTS = {
    "confluence": ("confluence_space_grants", "confluence_page_grants"),
    "jira": ("jira_project_grants", "jira_issue_grants"),
    "drive": ("drive_folder_grants", "drive_file_grants"),
    "slack": ("slack_channel_grants", "slack_thread_grants", "slack_dm_grants"),
}


@dataclass(frozen=True)
class MockSource:
    connector: object
    refs: tuple[SourceRef, ...]

    def __post_init__(self):
        if (not isinstance(self.refs, tuple) or not 1 <= len(self.refs) <= 100
                or any(not isinstance(ref, SourceRef) for ref in self.refs)):
            raise ConnectorError("invalid_configuration")


class MockConnectorState(SimulatedPlatformState):
    def __init__(self, tenant_id, sources: tuple[MockSource, ...], *, freshness_budget_seconds=3600):
        if (not isinstance(sources, tuple) or not 1 <= len(sources) <= 32
                or any(not isinstance(item, MockSource) for item in sources)):
            raise ConnectorError("invalid_configuration")
        self.tenant_id, self.sources = tenant_id, sources
        mappings = self._bindings()
        platforms = {item.connector.session.platform for item in sources}
        super().__init__(records=[], principal_map=mappings, last_successful_sync={},
                         freshness_budget_seconds={p: freshness_budget_seconds for p in platforms})

    def _bindings(self):
        mappings = {}
        for item in self.sources:
            session = item.connector.session
            if session.mode != "offline_mock":
                raise ConnectorError("network_disabled")
            binding = session.binding
            if binding.tenant_id != self.tenant_id:
                raise ConnectorError("identity_mismatch")
            previous = mappings.get(binding.principal_id, {}).get(session.platform)
            if previous is not None and previous != binding.account_id:
                raise ConnectorError("identity_mismatch")
            mappings[binding.principal_id] = {
                **mappings.get(binding.principal_id, {}), session.platform: binding.account_id}
        return mappings

    def refresh(self, now: datetime):
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ConnectorError("invalid_request")
        with self.lock:
            try:
                mappings = self._bindings()
                records, grants = self._fetch()
            except Exception as exc:
                # No old cache or packet stays readable after an uncertain refresh.
                self.records = {}
                error = exc if isinstance(exc, ConnectorError) else ConnectorError("invalid_response")
                category = error.code if error.code in {"timeout", "rate_limited", "expired_access"} else "unavailable"
                self.failures = {p: SourceFailure(category=category) for p in self.freshness_budget_seconds}
                self.permission_revision += 1
                raise error from None
            self.records = records
            self.principal_map = mappings
            for field, entries in grants.items():
                setattr(self, field, {key: frozenset(accounts) for key, accounts in entries.items()})
            self.last_successful_sync = {p: now for p in self.freshness_budget_seconds}
            self.failures = {}
            self.permission_revision += 1

    def _fetch(self):
        records = {}
        grants = {field: {} for fields in _GRANTS.values() for field in fields}
        for item in self.sources:
            session = item.connector.session
            account = session.binding.account_id
            for ref in item.refs:
                try:
                    documents = item.connector.fetch(ref)
                except SourceUnavailable:
                    continue
                for doc in documents:
                    if not self._contained(doc, ref, session):
                        raise ConnectorError("invalid_response")
                    record = SimulatedSource(
                        platform=doc.platform, tenant_id=self.tenant_id, source_id=doc.source_id,
                        source_kind=doc.source_kind, version_id=doc.version_id,
                        content_sha256=doc.content_sha256, text=doc.text, locator=doc.locator,
                        parent_id=doc.parent_id, thread_id=doc.thread_id,
                        source_updated_at=doc.source_updated_at, event_at=doc.event_at)
                    key = (doc.platform, doc.source_id)
                    if key in records and records[key] != record:
                        raise ConnectorError("source_changed")
                    records[key] = record
                    parent, child, *_ = _GRANTS[doc.platform]
                    grants[parent].setdefault(doc.parent_id, set()).add(account)
                    child_id = doc.thread_id if doc.platform == "slack" else doc.source_id
                    if child_id:
                        grants[child].setdefault(child_id, set()).add(account)
        return records, grants

    @staticmethod
    def _contained(doc, ref, session):
        if (not isinstance(doc, ConnectorDocument) or doc.mode != "offline_mock"
                or doc.platform != session.platform or ref.platform != session.platform):
            return False
        if doc.platform != "slack":
            return (doc.source_id == ref.source_id and doc.parent_id == ref.parent_id
                    and doc.thread_id is None and ref.thread_id is None)
        return (ref.parent_id == session.binding.workspace_id
                and doc.parent_id == ref.source_id
                and doc.source_id.startswith(ref.source_id + ":")
                and (ref.thread_id is None or doc.thread_id == ref.thread_id))
