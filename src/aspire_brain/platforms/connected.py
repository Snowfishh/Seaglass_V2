"""Connector-backed upstreams: real platform reads feeding the same synchronizer and index.

Each platform has one :class:`ConnectorUpstream`. A poll crawls every configured container
(Confluence spaces, Jira projects, the Slack workspace, Drive folders) once per application
user, **with that user's own credential**, so each platform decides what that user can see
under its own permission model. Items a user can read become that user's grants in the
platform's own grant maps (space+page, project+issue, channel+thread, folder+file); nothing is
flattened into a shared ACL. The poll then publishes the difference from the previous crawl as
upsert, delete and permission changes, which :class:`~aspire_brain.platforms.sync.Synchronizer`
commits atomically like any other change feed.

A poll is all or nothing. If any user's crawl fails, nothing is published and the next sync
reports the failure category, so a partial view can never delete records or remove grants. A
container the platform refuses a user outright (403 or 404) is that user's empty view, not a
failure. When users see different text for one item, only those who saw the kept copy are
granted it, so no user is served text read with another user's credential.

:meth:`ConnectorUpstream.verify` asks the platform again, at query time and with the asking
user's credential, whether one record is still readable and unchanged.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aspire_brain.platforms.connectors import connector_for
from aspire_brain.platforms.connectors.core import (
    ConnectorError,
    ConnectorSession,
    IdentityBinding,
    SourceRef,
    SourceUnavailable,
)
from aspire_brain.platforms.simulated import ALL_PLATFORMS, SimulatedSource
from aspire_brain.platforms.sync import (
    GRANT_FIELDS,
    ChangePage,
    UpstreamChange,
    UpstreamExpired,
    UpstreamInterrupted,
    UpstreamRateLimited,
)

#: How each platform's grant maps are keyed: (parent map, child map).
_CHILD_KEY = {"confluence": "source_id", "jira": "source_id", "drive": "source_id",
              "slack": "thread_id"}


class ConnectorUpstream:
    """One platform's change feed, built by crawling each user's own view of it."""

    def __init__(self, *, platform: str, tenant_id: str, readers: dict, containers,
                 page_size: int = 50):
        if platform not in ALL_PLATFORMS or not readers:
            raise ValueError("Connector upstream needs a platform and at least one reader")
        containers = tuple(containers)
        if not containers or any(not isinstance(item, str) or not item for item in containers):
            raise ValueError("Connector upstream needs at least one container")
        self.platform = platform
        self.tenant_id = tenant_id
        #: application principal ID -> adapter built on that principal's own session
        self.readers = dict(readers)
        self.containers = containers
        self.page_size = page_size
        self.records: dict[str, SimulatedSource] = {}
        self.grants: dict[str, dict[str, frozenset[str]]] = {
            field: {} for field in GRANT_FIELDS[platform]}
        self.revision = 0
        self.changes: list[UpstreamChange] = []
        self.fault: str | None = None
        self.last_poll: dict | None = None

    # -- crawling ----------------------------------------------------------------------

    def _documents(self, connector, container):
        try:
            refs = connector.discover(container)
        except SourceUnavailable:
            # The platform refuses this user the whole container (403 or 404). That is this
            # user's view of it, empty, not a failed crawl: the other users' views still count.
            return
        for ref in refs:
            try:
                yield from connector.fetch(ref)
            except SourceUnavailable:
                continue
            if self.platform == "slack":
                for root in connector.thread_roots:
                    try:
                        yield from connector.fetch(SourceRef("slack", ref.source_id,
                                                             ref.parent_id, thread_id=root))
                    except SourceUnavailable:
                        continue

    def _crawl(self):
        parent_field, child_field = GRANT_FIELDS[self.platform][:2]
        parents: dict[str, set[str]] = {}
        #: source_id -> content hash -> (record, accounts that saw exactly that content)
        views: dict[str, dict[str, tuple[SimulatedSource, set[str]]]] = {}
        for connector in self.readers.values():
            account = connector.session.binding.account_id
            for container in self.containers:
                for doc in self._documents(connector, container):
                    record = SimulatedSource(
                        platform=doc.platform, tenant_id=self.tenant_id,
                        source_id=doc.source_id, source_kind=doc.source_kind,
                        version_id=doc.version_id, content_sha256=doc.content_sha256,
                        text=doc.text, locator=doc.locator, parent_id=doc.parent_id,
                        thread_id=doc.thread_id, source_updated_at=doc.source_updated_at,
                        event_at=doc.event_at)
                    seen = views.setdefault(record.source_id, {})
                    seen.setdefault(record.content_sha256, (record, set()))[1].add(account)
                    parents.setdefault(doc.parent_id, set()).add(account)
        records: dict[str, SimulatedSource] = {}
        children: dict[str, set[str]] = {}
        variants = 0
        for source_id, seen in views.items():
            # Two users can see different text for one item (per-user rendering, or an edit
            # between their reads). The index holds one copy, so it keeps the newest and grants
            # the item only to the users who saw exactly that copy; nobody is served text read
            # with someone else's credential. The others get it back once their views agree.
            record, accounts = max(seen.values(), key=lambda view: view[0].source_updated_at)
            if len(seen) > 1:
                variants += 1
                if self.platform == "slack":
                    # A Slack message is granted by channel or thread, never by itself, so a
                    # disagreeing message cannot be limited to its readers; it is left out.
                    continue
            records[source_id] = record
            child = getattr(record, _CHILD_KEY[self.platform])
            if child:
                children.setdefault(child, set()).update(accounts)
        grants = {field: {} for field in GRANT_FIELDS[self.platform]}
        grants[parent_field] = parents
        grants[child_field] = children
        frozen = {field: {key: frozenset(accounts) for key, accounts in entries.items()}
                  for field, entries in grants.items()}
        return records, frozen, variants

    def _append(self, **values) -> None:
        self.revision += 1
        self.changes.append(UpstreamChange(revision=self.revision, platform=self.platform,
                                           **values))

    def poll(self, now: datetime) -> dict:
        """Crawl every user's view and publish what changed since the previous crawl."""
        try:
            records, grants, variants = self._crawl()
        except ConnectorError as exc:
            self.fault = exc.code
            self.last_poll = {"platform": self.platform, "outcome": "failed",
                              "error": exc.code, "polled_at": now.isoformat()}
            return self.last_poll
        changes = 0
        for source_id, record in sorted(records.items()):
            old = self.records.get(source_id)
            if old is None or old.version_id != record.version_id \
                    or old.content_sha256 != record.content_sha256:
                self._append(kind="upsert", source_id=source_id, record=record,
                             upstream_updated_at=record.source_updated_at)
                changes += 1
        for source_id in sorted(set(self.records) - set(records)):
            self._append(kind="delete", source_id=source_id, upstream_updated_at=now)
            changes += 1
        for field in GRANT_FIELDS[self.platform]:
            old_map, new_map = self.grants.get(field, {}), grants.get(field, {})
            for key in sorted(set(old_map) | set(new_map)):
                before, after = old_map.get(key, frozenset()), new_map.get(key, frozenset())
                for account in sorted(after - before):
                    self._append(kind="acl", source_id=key, grant_field=field, grant_key=key,
                                 account_id=account, allowed=True, upstream_updated_at=now)
                    changes += 1
                for account in sorted(before - after):
                    self._append(kind="acl", source_id=key, grant_field=field, grant_key=key,
                                 account_id=account, allowed=False, upstream_updated_at=now)
                    changes += 1
        self.records = records
        self.grants = {field: dict(entries) for field, entries in grants.items()}
        self.fault = None
        self.last_poll = {"platform": self.platform, "outcome": "completed",
                          "fetched": len(records), "changes": changes,
                          "content_variants": variants, "polled_at": now.isoformat()}
        return self.last_poll

    # -- the synchronizer's read path ----------------------------------------------------

    def read_changes(self, *, since_revision: int, offset: int, limit: int) -> ChangePage:
        if self.fault == "rate_limited":
            raise UpstreamRateLimited()
        if self.fault in {"expired_access", "identity_mismatch"}:
            raise UpstreamExpired("Connector credential refused")
        if self.fault is not None:
            raise UpstreamInterrupted("Connector crawl failed")
        pending = [change for change in self.changes if change.revision > since_revision]
        items = pending[offset:offset + limit]
        next_offset = offset + len(items)
        return ChangePage(items=items, next_offset=next_offset,
                          has_more=next_offset < len(pending), upstream_revision=self.revision)

    # -- query-time re-check -------------------------------------------------------------

    def verify(self, account_id: str | None, record: SimulatedSource) -> str:
        """Re-read one record as the asking user: ``allowed``, ``denied``, ``changed`` or
        ``unverifiable``. A Slack message is checked by channel access only; an edit to it is
        picked up by the next sync."""
        connector = next((reader for reader in self.readers.values()
                          if reader.session.binding.account_id == account_id), None)
        if connector is None:
            return "denied"
        try:
            if self.platform == "slack":
                connector._authorize(SourceRef("slack", record.parent_id,
                                               connector.session.binding.workspace_id))
                return "allowed"
            documents = connector.fetch(SourceRef(self.platform, record.source_id,
                                                  record.parent_id))
        except SourceUnavailable:
            return "denied"
        except ConnectorError:
            return "unverifiable"
        current = next((doc for doc in documents if doc.source_id == record.source_id), None)
        if current is None:
            return "denied"
        if current.version_id != record.version_id or current.content_sha256 != record.content_sha256:
            return "changed"
        return "allowed"


# -- configuration ---------------------------------------------------------------------------

class ConnectorConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ConnectorConfig:
    """Who reads what. Identifiers only; credentials stay in a separate private file."""

    tenant_id: str
    allow_live: bool
    tokens_path: Path
    atlassian_site: str
    jira_site: str
    slack_workspace_id: str
    #: application principal -> {"token_user", "atlassian_email", "<platform>_account"}
    principals: dict
    #: platform -> tuple of container IDs
    containers: dict


ACCOUNT_KEYS = {"confluence": "atlassian_account_id", "jira": "atlassian_account_id",
                "slack": "slack_user_id", "drive": "drive_permission_id"}
TOKEN_KEYS = {"confluence": "atlassian", "jira": "atlassian", "slack": "slack", "drive": "drive"}


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("FILL")


def load_connector_config(path: Path, *, project_root: Path) -> ConnectorConfig:
    """Read the connector configuration, or the live-access targets file it can point to.

    The configuration names the tenant, the application principals and, for each, the platform
    account identifiers and the key of their credentials in the private tokens file. Containers
    default to the parents of the items in the live-access targets file.
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ConnectorConfigError("Connector configuration is unreadable") from exc
    if not isinstance(data, dict):
        raise ConnectorConfigError("Connector configuration must be a JSON object")
    targets = {}
    if data.get("targets_file"):
        target_path = Path(data["targets_file"]).expanduser()
        target_path = target_path if target_path.is_absolute() else project_root / target_path
        try:
            targets = json.loads(target_path.read_text())
        except (OSError, ValueError) as exc:
            raise ConnectorConfigError("Targets file is unreadable") from exc
    merged = {**targets, **{key: value for key, value in data.items() if key != "targets_file"}}
    users = merged.get("users", {})
    mapping = merged.get("principal_users", {"user-a": "A", "user-b": "B"})
    principals = {}
    for principal, user in mapping.items():
        profile = users.get(user)
        if not isinstance(profile, dict):
            raise ConnectorConfigError(f"No account profile for {principal}")
        principals[principal] = {**profile, "token_user": user}
    containers = merged.get("containers")
    if containers is None:
        items = merged.get("items", {})
        containers = {}
        for platform in ALL_PLATFORMS:
            parents = {item.get("parent") for item in items.get(platform, {}).values()
                       if isinstance(item, dict)}
            if platform == "slack":
                parents = {merged.get("slack_workspace_id")}
            containers[platform] = sorted(parent for parent in parents if _filled(parent))
    containers = {platform: tuple(values) for platform, values in containers.items() if values}
    if not containers:
        raise ConnectorConfigError("No containers to read")
    tokens_path = Path(merged.get("tokens_file")
                       or "~/.config/seaglass/live-access-tokens.json").expanduser()
    allow_live = merged.get("allow_live") is True
    return ConnectorConfig(
        tenant_id=merged.get("tenant_id", "fintech-demo"), allow_live=allow_live,
        tokens_path=tokens_path, atlassian_site=merged.get("atlassian_site", ""),
        jira_site=merged.get("jira_site") if _filled(merged.get("jira_site"))
        else merged.get("atlassian_site", ""),
        slack_workspace_id=merged.get("slack_workspace_id", ""),
        principals=principals, containers=containers)


def load_tokens(path: Path, *, project_root: Path) -> dict:
    """The private credentials file: outside the project and readable only by its owner."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConnectorConfigError("Connector tokens file not found")
    if path.is_relative_to(project_root.resolve()):
        raise ConnectorConfigError("Connector tokens file must be outside the project")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ConnectorConfigError("Connector tokens file must be readable only by its owner")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ConnectorConfigError("Connector tokens file must be a JSON object")
    return data


def build_upstreams(config: ConnectorConfig, tokens: dict, *, transport_for=None) -> dict:
    """One :class:`ConnectorUpstream` per configured platform.

    ``transport_for(platform)`` supplies an ``httpx.MockTransport`` for offline tests. Without
    it, sessions are live and the configuration must say ``"allow_live": true``.
    """
    if transport_for is None and not config.allow_live:
        raise ConnectorConfigError("Live connector reads need allow_live: true")
    base_urls = {"confluence": config.atlassian_site, "jira": config.jira_site,
                 "slack": "https://slack.com", "drive": "https://www.googleapis.com"}
    upstreams = {}
    for platform, containers in config.containers.items():
        readers = {}
        for principal, profile in config.principals.items():
            account = profile.get(ACCOUNT_KEYS[platform])
            token = tokens.get(profile["token_user"], {}).get(TOKEN_KEYS[platform])
            if not (_filled(account) and _filled(token)):
                raise ConnectorConfigError(f"{principal} has no {platform} account or token")
            binding = IdentityBinding(
                tenant_id=config.tenant_id, principal_id=principal, account_id=account,
                workspace_id=config.slack_workspace_id if platform == "slack" else "")
            transport = transport_for(platform) if transport_for else None
            session = ConnectorSession(
                platform=platform, base_url=base_urls[platform], binding=binding,
                credential=token,
                auth_user=(profile.get("atlassian_email")
                           if platform in {"confluence", "jira"} else None),
                transport=transport, allow_live=transport is None)
            readers[principal] = connector_for(session)
        upstreams[platform] = ConnectorUpstream(platform=platform, tenant_id=config.tenant_id,
                                                readers=readers, containers=containers)
    return upstreams


def principal_map(config: ConnectorConfig) -> dict:
    return {principal: {platform: profile[ACCOUNT_KEYS[platform]]
                        for platform in config.containers}
            for principal, profile in config.principals.items()}
