"""Independent fixture integrity, isolation and declared-mode checks."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aspire_brain.platforms.connectors.offline import load_fixture_index

ROOT = Path(__file__).resolve().parents[2] / "data/fixtures/fintech_operations"
NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


def test_fixture_loads_all_platforms_and_explicit_revision():
    initial = load_fixture_index(ROOT, now=NOW)
    updated = load_fixture_index(ROOT, now=NOW, updates=True)
    assert len(initial.records) == 8
    assert set(initial.upstream) == {"confluence", "jira", "slack", "drive"}
    key = ("confluence", "conf-payment-runbook")
    assert initial.records[key].version_id == "1.0"
    assert updated.records[key].version_id == "1.1"
    assert all(not initial.pending_changes(p) for p in initial.upstream)
    with pytest.raises(ValueError):
        initial.records[key].text = "mutated"


@pytest.fixture
def copied(tmp_path):
    target = tmp_path / "fixtures"
    shutil.copytree(ROOT, target)
    return target


@pytest.mark.parametrize("field,value", [
    ("mode", "live"), ("fictional", False), ("fictional", 1),
    ("live_verified", True), ("live_verified", 0), ("schema_version", True),
    ("tenant_id", "another-tenant"), ("unknown", "extra"),
])
def test_rejects_untrusted_manifest_mode(copied, field, value):
    path = copied / "manifest.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_fixture_index(copied, now=NOW)


@pytest.mark.parametrize("change", ["hash", "traversal", "absolute", "symlink", "acl", "duplicate"])
def test_rejects_content_and_identity_tampering(copied, change):
    path = copied / "manifest.json"
    data = json.loads(path.read_text())
    row = data["documents"][0]
    if change == "hash":
        (copied / row["content_file"]).write_text("tampered")
    elif change == "traversal":
        row["content_file"] = "../outside.md"
    elif change == "absolute":
        row["content_file"] = "/etc/hosts"
    elif change == "symlink":
        external = copied.parent / "external.md"
        external.write_text("external")
        (copied / "linked.md").symlink_to(external)
        row["content_file"] = "linked.md"
    elif change == "acl":
        row["allowed_principals"] = ["unmapped-user"]
    else:
        data["documents"].append(dict(row))
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_fixture_index(copied, now=NOW)


def test_requires_aware_sync_clock():
    with pytest.raises(ValueError):
        load_fixture_index(ROOT, now=datetime(2026, 10, 12))
