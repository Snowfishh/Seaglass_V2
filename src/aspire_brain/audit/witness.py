"""An append-only witness of each tenant's audit chain head, kept outside the audit database.

The HMAC chain shows that no event in the middle of the history was altered, inserted or
removed. It cannot show that the *newest* events are all still there: delete the last few rows
and what remains is still a valid chain. The witness closes that gap. After every committed
audit write the writer records the tenant's chain head (sequence and HMAC) here, in a separate
file under a separate key, with each witness line chained to the one before it.

Verification then compares the database against the witness:

* the witness's own chain must verify, so a witness line cannot be edited or removed quietly;
* the database must still contain the witnessed head, with the same HMAC, so truncating or
  rewriting the tail is detected;
* when the witness head equals the database head, no event is outside the witness, so the
  history is complete *relative to the witness*.

The guarantee is relative, and it has a hole no local file can close: the witness chain, like the
audit chain, only proves its own prefix. Someone who can write both files can delete the newest
events from the database *and* the matching newest lines from the witness, with no key at all,
and both still verify. Rewriting rather than deleting needs both keys. Keep the witness on
separately protected storage, and retain an exported checkpoint (``audit-checkpoint``) elsewhere
to detect a rollback of both past it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

from aspire_brain.audit.engine import DIGEST, GENESIS, AuditError

DOMAIN = b"aspire-brain:audit-witness:v1\x00"
WITNESS_NOTE = (
    "Completeness is proven relative to the separate audit witness: every committed event up to "
    "the witnessed head is present and unaltered. Deleting the newest events from both the "
    "database and the witness needs no key and is not detected here; only a checkpoint kept "
    "elsewhere catches it. Rewriting both needs both keys."
)


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass
class _Prefix:
    """The part of the witness file this process has already verified.

    ``tail`` is the last verified line and ``tail_start`` its byte offset. An append re-reads
    that line and checks only the lines after ``end``, so its cost does not grow with the
    history. Full verification (:meth:`AuditWitness.heads`) always re-reads every line.
    """

    identity: tuple
    end: int = 0
    tail_start: int = 0
    tail: bytes = b""
    last_mac: str = GENESIS
    lines: int = 0
    #: tenant -> {sequence: head HMAC}, in witnessed (ascending) order
    heads: dict = field(default_factory=dict)

    def extend(self, found):
        for entry, start, line in found:
            self.heads.setdefault(entry["tenant_id"], {})[entry["sequence"]] = entry["head_hmac"]
            self.tail_start, self.tail = start, line
            self.end, self.last_mac = start + len(line), entry["mac"]
            self.lines += 1


class AuditWitness:
    def __init__(self, path: Path, key: bytes):
        if not isinstance(key, bytes) or len(key) < 32:
            raise AuditError("Audit witness key must contain at least 32 bytes")
        self.path = Path(path)
        self._key = key
        self._prefix: _Prefix | None = None

    def _mac(self, entry: dict) -> str:
        body = {name: entry[name] for name in ("tenant_id", "sequence", "head_hmac",
                                                 "recorded_at", "previous")}
        return hmac.new(self._key, DOMAIN + _canonical(body), hashlib.sha256).hexdigest()

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "ab+") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            else:  # pragma: no cover - Windows only
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self, handle, start=0, previous=GENESIS, first_line=1) -> list[tuple]:
        """Verify every line from byte ``start`` on, each chained to the one before it.

        Returns ``(entry, byte offset, raw line)`` for each line.
        """
        handle.seek(start)
        found, offset = [], start
        for number, line in enumerate(handle.read().splitlines(keepends=True), first_line):
            try:
                entry = json.loads(line)
                valid = (isinstance(entry, dict)
                         and set(entry) == {"tenant_id", "sequence", "head_hmac", "recorded_at",
                                            "previous", "mac"}
                         and type(entry["sequence"]) is int and entry["sequence"] >= 1
                         and isinstance(entry["head_hmac"], str)
                         and DIGEST.fullmatch(entry["head_hmac"])
                         and hmac.compare_digest(str(entry["previous"]), previous)
                         and hmac.compare_digest(str(entry["mac"]), self._mac(entry)))
            except (ValueError, TypeError, KeyError):
                valid = False
            if not valid:
                raise AuditError(f"Audit witness integrity failure at line {number}")
            found.append((entry, offset, line))
            offset += len(line)
            previous = entry["mac"]
        return found

    def _verified(self, handle) -> _Prefix:
        """The verified state of the whole file, re-reading only what was appended since the
        last call when the file is the same one and its last verified line is unchanged."""
        status = os.fstat(handle.fileno())
        identity = (status.st_dev, status.st_ino)
        prefix = self._prefix
        if prefix is not None and prefix.identity == identity and status.st_size >= prefix.end:
            handle.seek(prefix.tail_start)
            if handle.read(prefix.end - prefix.tail_start) == prefix.tail:
                prefix.extend(self._read(handle, prefix.end, prefix.last_mac, prefix.lines + 1))
                return prefix
        self._prefix = None
        prefix = _Prefix(identity)
        prefix.extend(self._read(handle))
        self._prefix = prefix
        return prefix

    def record(self, tenant_id: str, sequence: int, head_hmac: str) -> bool:
        """Witness a committed head. Older or repeated heads are ignored; a conflict raises."""
        if type(sequence) is not int or sequence < 1 or not DIGEST.fullmatch(head_hmac or ""):
            raise AuditError("Invalid audit head")
        with self._locked() as handle:
            prefix = self._verified(handle)
            mine = prefix.heads.get(tenant_id, {})
            if mine and next(reversed(mine)) >= sequence:
                same = mine.get(sequence)
                if same is not None and not hmac.compare_digest(same, head_hmac):
                    raise AuditError("Audit chain head conflicts with its witness")
                return False
            entry = {"tenant_id": tenant_id, "sequence": sequence, "head_hmac": head_hmac,
                     "recorded_at": datetime.now(UTC).isoformat(timespec="microseconds"),
                     "previous": prefix.last_mac}
            entry["mac"] = self._mac(entry)
            line = (json.dumps(entry, sort_keys=True) + "\n").encode()
            self._prefix = None  # until the line is known to be on disk
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
            prefix.extend([(entry, prefix.end, line)])
            self._prefix = prefix
            return True

    def heads(self, tenant_id: str) -> list[dict]:
        """Every witnessed head for one tenant, oldest first, after verifying the whole witness."""
        if not self.path.exists():
            return []
        with self._locked() as handle:
            self._prefix = None
            found = self._read(handle)
            status = os.fstat(handle.fileno())
            prefix = _Prefix((status.st_dev, status.st_ino))
            prefix.extend(found)
            self._prefix = prefix
            return [entry for entry, _, _ in found if entry["tenant_id"] == tenant_id]
