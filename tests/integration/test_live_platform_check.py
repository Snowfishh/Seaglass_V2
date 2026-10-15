"""The owner-run integrated live check, exercised offline against the fake platforms."""

import importlib.util
import json
import socket
from pathlib import Path

import pytest
from fake_platforms import FakePlatforms

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_platform_check", ROOT / "eval/live_platform/check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


class Clock:
    mode = "wall_clock"

    def __init__(self, fake):
        self.fake = fake

    def now(self):
        return self.fake.now


@pytest.fixture
def harness(tmp_path):
    fake = FakePlatforms()
    targets = fake.targets() | {"items": {
        "confluence": {"general": {"id": "101", "parent": "OPS"}, "restricted": {"id": "202", "parent": "OPS"}},
        "jira": {"general": {"id": "OPS-1", "parent": "OPS"}, "restricted": {"id": "OPS-2", "parent": "OPS"}},
        "slack": {"general": {"id": "CGEN"}, "restricted": {"id": "GRES"}},
        "drive": {"general": {"id": "fileGen", "parent": "folder1"},
                  "restricted": {"id": "fileRes", "parent": "folder1"}}}}
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(targets))
    return fake, check.Harness(path, fake.tokens, transport_for=fake.transport_for, clock=Clock(fake))


#: Questions the fake workspace can answer, between them touching all four platforms.
FAKE_QUESTIONS = (
    ("What is the escalation threshold for processing payments?", "general"),
    ("What is the status of the delayed payment callbacks?", "general"),
    ("Which processing payments still need a partner reference?", "general"),
    ("Why is the Cedar Quay payment held?", "restricted"),
)


def test_ingest_passes_on_positive_evidence_from_all_four_platforms(harness):
    _, h = harness
    result = check.ingest(h, FAKE_QUESTIONS)
    assert result["pass"], result
    rows = result["rows"]
    assert {row["platform"] for row in rows if row["step"] == "sync"} == set(check.PLATFORMS)
    assert all(row["indexed_records"] > 0 for row in rows if row["step"] == "sync")
    assert {row["platform"] for row in rows if row["step"] == "coverage" and row["pass"]} == set(
        check.PLATFORMS)
    held = [row for row in rows if row.get("principal") == "user-a" and row["restricted_cited"]]
    assert held, "user A should be able to see restricted evidence"
    assert rows[-1]["step"] == "answer_coverage" and rows[-1]["missing_platforms"] == []
    assert "Cedar" not in json.dumps(result)


def test_ingest_fails_when_the_questions_are_not_answered(harness):
    # The judge's false pass: every sync completes and nothing leaks, but nothing is answered.
    _, h = harness
    result = check.ingest(h, (("What is the approved travel budget for the offsite?", "general"),
                              ("Why is the Cedar Quay payment held?", "restricted")))
    assert not result["pass"]
    assert any(row["step"] == "query" and not row["pass"] for row in result["rows"])
    assert not result["rows"][-1]["pass"]  # fewer than four platforms cited


def test_ingest_fails_on_an_empty_workspace(tmp_path):
    fake = FakePlatforms()
    for platform_items in (fake.pages, fake.issues, fake.files):
        platform_items.clear()
    for channel in fake.channels.values():
        channel["messages"].clear()
    targets = fake.targets() | {"items": {}}
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(targets))
    h = check.Harness(path, fake.tokens, transport_for=fake.transport_for, clock=Clock(fake))
    result = check.ingest(h, FAKE_QUESTIONS)
    assert not result["pass"]
    assert not any(row["pass"] for row in result["rows"] if row["step"] in {"sync", "coverage"})


def test_a_restricted_question_a_cannot_answer_fails_the_positive_control(harness):
    fake, h = harness
    fake.remove_reader("A")
    result = check.ingest(h, FAKE_QUESTIONS)
    row = next(row for row in result["rows"]
               if row.get("principal") == "user-a" and row["kind"] == "restricted")
    assert row["restricted_cited"] is False and row["pass"] is False
    assert not result["pass"]


def test_freshness_measures_wall_clock_time_until_an_edit_is_answered(harness):
    fake, h = harness
    ticks = iter(range(0, 10000, 60))

    def prompt(_message):
        fake.edit_page("101", "Run the standby failover drill before restarting the service.")
    result = check.freshness(h, "standby failover drill", prompt=prompt, sleep=lambda s: fake.tick(1),
                             monotonic=lambda: next(ticks), poll_seconds=60)
    assert result["pass"] and result["visible_after_seconds"] <= 3600


def test_revocation_is_enforced_before_and_after_the_sync(harness):
    fake, h = harness
    prompts = iter([lambda: fake.remove_reader("A"), lambda: None])
    result = check.revocation(h, "Why is the Cedar Quay payment held?",
                              prompt=lambda _message: next(prompts)())
    assert result["pass"], result
    assert [row["check"] for row in result["rows"]] == [
        "a_sees_restricted_before", "not_quoted_before_any_sync", "saved_answer_closed",
        "grant_removed_after_sync"]
