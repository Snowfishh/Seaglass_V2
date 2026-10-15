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


class AuditWitness:
    def __init__(self, path: Path, key: bytes):
        if not isinstance(key, bytes) or len(key) < 32:
            raise AuditError("Audit witness key must contain at least 32 bytes")
        self.path = Path(path)
        self._key = key

    def _mac(self, entry: dict) -> str:
        body = {name: entry[name] for name in ("tenant_id", "sequence", "head_hmac",
                                                 "recorded_at", "previous")}
        return hmac.new(self._key, DOMAIN + _canonical(body), hashlib.sha256).hexdigest()

    @contextmanager
    def _locked(self, mode):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, mode) as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            else:  # pragma: no cover - Windows only
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _entries(self, handle) -> list[dict]:
        handle.seek(0)
        entries, previous = [], GENESIS
        for number, line in enumerate(handle.read().splitlines(), 1):
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
            entries.append(entry)
            previous = entry["mac"]
        return entries

    def record(self, tenant_id: str, sequence: int, head_hmac: str) -> bool:
        """Witness a committed head. Older or repeated heads are ignored; a conflict raises."""
        if type(sequence) is not int or sequence < 1 or not DIGEST.fullmatch(head_hmac or ""):
            raise AuditError("Invalid audit head")
        with self._locked("a+") as handle:
            entries = self._entries(handle)
            mine = [entry for entry in entries if entry["tenant_id"] == tenant_id]
            if mine and mine[-1]["sequence"] >= sequence:
                same = next((entry for entry in mine if entry["sequence"] == sequence), None)
                if same is not None and not hmac.compare_digest(same["head_hmac"], head_hmac):
                    raise AuditError("Audit chain head conflicts with its witness")
                return False
            entry = {"tenant_id": tenant_id, "sequence": sequence, "head_hmac": head_hmac,
                     "recorded_at": datetime.now(UTC).isoformat(timespec="microseconds"),
                     "previous": entries[-1]["mac"] if entries else GENESIS}
            entry["mac"] = self._mac(entry)
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return True

    def heads(self, tenant_id: str) -> list[dict]:
        """Every witnessed head for one tenant, oldest first, after verifying the witness."""
        if not self.path.exists():
            return []
        with self._locked("a+") as handle:
            return [entry for entry in self._entries(handle) if entry["tenant_id"] == tenant_id]
