"""Load explicitly fictional files into the existing local synchronization model.

No credentials, network transport or live connector are used by this module.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aspire_brain.platforms.simulated import ALL_PLATFORMS, SimulatedSource
from aspire_brain.platforms.sync import SimulatedUpstream, Synchronizer, SyncIndex

_PRINCIPALS = ("user-a", "user-b")
_ROOT_FIELDS = {
    "schema_version", "mode", "fictional", "live_verified", "tenant_id", "documents", "updates",
}
_RECORD_FIELDS = {
    "platform", "source_id", "source_kind", "version_id", "content_file", "content_sha256",
    "locator", "parent_id", "thread_id", "source_updated_at", "event_at", "allowed_principals",
}
_GRANT_FIELDS = {
    "confluence": ("confluence_space_grants", "confluence_page_grants"),
    "jira": ("jira_project_grants", "jira_issue_grants"),
    "drive": ("drive_folder_grants", "drive_file_grants"),
    "slack": ("slack_channel_grants", "slack_thread_grants"),
}


@dataclass(frozen=True)
class _Fixture:
    source: SimulatedSource
    principals: tuple[str, ...]


def _read_under(root: Path, relative: str) -> bytes:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Fixture file must be a relative path")
    if ".." in Path(relative).parts:
        raise ValueError("Fixture path traversal is forbidden")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError("Fixture file must remain inside its root")
    if candidate.stat().st_size > 100_000:
        raise ValueError("Fixture file exceeds the size limit")
    return candidate.read_bytes()


def _record(root: Path, value: dict) -> _Fixture:
    if not isinstance(value, dict) or set(value) != _RECORD_FIELDS:
        raise ValueError("Invalid fixture record fields")
    allowed = value["allowed_principals"]
    if (not isinstance(allowed, list) or not allowed or
            any(not isinstance(p, str) or p not in _PRINCIPALS for p in allowed) or
            len(set(allowed)) != len(allowed)):
        raise ValueError("Fixture ACL must contain known unique identities")
    raw = _read_under(root, value["content_file"])
    if hashlib.sha256(raw).hexdigest() != value["content_sha256"]:
        raise ValueError("Fixture content hash mismatch")
    source = SimulatedSource.model_validate({
        **{k: v for k, v in value.items() if k not in ("content_file", "allowed_principals")},
        "tenant_id": "fintech-demo", "text": raw.decode("utf-8"),
    })
    if source.locator != "fixture://fintech-operations/" + source.source_id:
        raise ValueError("Fixture locator must be explicitly offline")
    if source.source_kind == "dm":
        raise ValueError("This fixture bundle does not support direct messages")
    return _Fixture(source, tuple(allowed))


def _load(root: Path) -> tuple[tuple[_Fixture, ...], tuple[_Fixture, ...]]:
    data = json.loads(_read_under(root, "manifest.json"))
    if not isinstance(data, dict) or set(data) != _ROOT_FIELDS:
        raise ValueError("Invalid fixture manifest fields")
    if (type(data["schema_version"]) is not int or data["schema_version"] != 1 or
            data["mode"] != "offline_fixture" or data["fictional"] is not True or
            data["live_verified"] is not False or data["tenant_id"] != "fintech-demo"):
        raise ValueError("Manifest must declare fictional unverified offline mode")
    if not isinstance(data["documents"], list) or not isinstance(data["updates"], list):
        raise ValueError("Fixture documents and updates must be arrays")
    initial = tuple(_record(root, item) for item in data["documents"])
    updates = tuple(_record(root, item) for item in data["updates"])
    keys = {(r.source.platform, r.source.source_id): r for r in initial}
    if len(keys) != len(initial) or {r.source.platform for r in initial} != set(ALL_PLATFORMS):
        raise ValueError("Initial fixture identities must be unique and cover four platforms")
    updated_keys = set()
    for update in updates:
        key = (update.source.platform, update.source.source_id)
        prior = keys.get(key)
        if (prior is None or key in updated_keys or update.principals != prior.principals or
                update.source.version_id == prior.source.version_id or
                update.source.source_updated_at <= prior.source.source_updated_at or
                update.source.parent_id != prior.source.parent_id or
                update.source.source_kind != prior.source.source_kind):
            raise ValueError("Fixture update must replace one known older source")
        updated_keys.add(key)
    return initial, updates


def _grants(records: tuple[_Fixture, ...], platform: str) -> dict:
    parent_field, child_field = _GRANT_FIELDS[platform]
    grants = {parent_field: {}, child_field: {}}
    for fixture in records:
        source, accounts = fixture.source, frozenset(fixture.principals)
        parents = grants[parent_field]
        parents[source.parent_id] = parents.get(source.parent_id, frozenset()) | accounts
        if platform != "slack":
            grants[child_field][source.source_id] = accounts
        elif source.thread_id:
            grants[child_field][source.thread_id] = accounts
    return grants


def load_fixture_index(root: str | Path, *, now: datetime, updates: bool = False) -> SyncIndex:
    """Validate the full bundle and synchronize fictional records on an explicit clock."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Fixture synchronization time needs a timezone")
    if type(updates) is not bool:
        raise ValueError("Fixture update switch must be boolean")
    initial, replacements = _load(Path(root).resolve())
    upstream = {}
    for platform in ALL_PLATFORMS:
        records = tuple(r for r in initial if r.source.platform == platform)
        upstream[platform] = SimulatedUpstream(
            platform=platform, tenant_id="fintech-demo",
            records=tuple(r.source for r in records), grants=_grants(records, platform),
        )
    index = SyncIndex(
        principal_map={p: {platform: p for platform in ALL_PLATFORMS} for p in _PRINCIPALS},
        freshness_budget_seconds={p: 3600 for p in ALL_PLATFORMS}, upstream=upstream,
    )
    if updates:
        for replacement in replacements:
            source = replacement.source
            upstream[source.platform].upsert(source, at=source.source_updated_at)
    for platform in ALL_PLATFORMS:
        result = Synchronizer(index, max_attempts=1).sync(platform, now)
        if result["outcome"] != "completed":
            raise ValueError("Offline fixture synchronization did not complete")
    return index
