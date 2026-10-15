"""The audit witness verifies an append against what it already checked, not its whole history."""

import json
import secrets

import pytest

from aspire_brain.audit.engine import AuditError
from aspire_brain.audit.witness import AuditWitness


def head(number):
    return f"{number:064x}"


@pytest.fixture
def key():
    return secrets.token_bytes(32)


@pytest.fixture
def witness(tmp_path, key):
    return AuditWitness(tmp_path / "witness.jsonl", key)


def reads(monkeypatch, witness):
    """Record the byte offset every verification pass starts from."""
    starts = []
    original = witness._read

    def spy(handle, start=0, *args, **kwargs):
        starts.append(start)
        return original(handle, start, *args, **kwargs)
    monkeypatch.setattr(witness, "_read", spy)
    return starts


def test_an_append_reads_only_what_was_written_since_the_last_one(witness, monkeypatch):
    for sequence in range(1, 21):
        assert witness.record("tenant", sequence, head(sequence)) is True
    starts = reads(monkeypatch, witness)
    size = witness.path.stat().st_size
    assert witness.record("tenant", 21, head(21)) is True
    assert starts == [size]
    assert [entry["sequence"] for entry in witness.heads("tenant")] == list(range(1, 22))


def test_repeated_and_conflicting_heads_are_still_recognised(witness):
    witness.record("tenant", 1, head(1))
    witness.record("other", 1, head(7))
    assert witness.record("tenant", 1, head(1)) is False
    with pytest.raises(AuditError, match="conflicts"):
        witness.record("tenant", 1, head(2))


def test_lines_another_writer_appended_are_verified_and_chained(tmp_path, key):
    first = AuditWitness(tmp_path / "witness.jsonl", key)
    second = AuditWitness(tmp_path / "witness.jsonl", key)
    first.record("tenant", 1, head(1))
    second.record("tenant", 2, head(2))
    first.record("tenant", 3, head(3))
    assert [entry["sequence"] for entry in first.heads("tenant")] == [1, 2, 3]


def test_a_rewritten_tail_makes_the_next_append_reread_everything(witness, monkeypatch):
    for sequence in (1, 2, 3):
        witness.record("tenant", sequence, head(sequence))
    lines = witness.path.read_text().splitlines()
    witness.path.write_text("\n".join(lines[:-1]) + "\n" + lines[-1].replace("3", "4", 1) + "\n")
    starts = reads(monkeypatch, witness)
    with pytest.raises(AuditError, match="line 3"):
        witness.record("tenant", 4, head(4))
    assert starts == [0]


def test_an_edited_earlier_line_is_caught_by_full_verification(witness):
    for sequence in (1, 2, 3):
        witness.record("tenant", sequence, head(sequence))
    lines = witness.path.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["head_hmac"] = head(9)
    witness.path.write_text("\n".join([json.dumps(entry, sort_keys=True)] + lines[1:]) + "\n")
    with pytest.raises(AuditError, match="line 1"):
        witness.heads("tenant")
