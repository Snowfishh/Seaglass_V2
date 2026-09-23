"""HMAC audit chains; integrity does not prove an unanchored tail is complete."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
DOMAIN = b"aspire-brain:audit-event:v1\x00"
GENESIS = "0" * 64
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SAFE_METADATA = frozenset(
    {
        "status",
        "query_status",
        "case_outcome",
        "provider_mode",
        "error_code",
        "reason",
        "category",
        "categories",
        "version_ids",
        "chunk_ids",
        "rule_ids",
        "document_ids",
        "response_digest",
        "acl_revision",
        "content_revision",
        "outcome",
        "operation",
        "changed_fields",
        "source_count",
        "conflict_count",
        "missing_evidence_categories",
    }
)
TERMINAL_EVENTS = frozenset({"query_completed", "query_failed", "query_denied", "query_aborted"})
PAYLOAD_COLUMNS = (
    "event_id",
    "schema_version",
    "key_id",
    "tenant_id",
    "sequence",
    "timestamp",
    "request_id",
    "principal_id",
    "event_type",
    "metadata_json",
    "previous_hmac",
)


class AuditError(RuntimeError):
    """A safe audit failure that callers must treat as a failed operation."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise AuditError("Invalid audit identifier")


def _metadata(metadata: dict) -> str:
    if not isinstance(metadata, dict) or not set(metadata).issubset(SAFE_METADATA):
        raise AuditError("Audit metadata must use minimised approved fields")
    for value in metadata.values():
        values = value if isinstance(value, list) else [value]
        if len(values) > 200:
            raise AuditError("Audit metadata exceeds limits")
        for item in values:
            if item is not None and type(item) not in (str, bool, int):
                raise AuditError("Audit metadata must contain safe identifiers and categories")
            if isinstance(item, str) and (len(item) > 256 or "\n" in item or "\r" in item):
                raise AuditError("Audit metadata exceeds limits")
    try:
        serialized = _canonical(metadata)
    except (TypeError, ValueError) as exc:
        raise AuditError("Invalid audit metadata") from exc
    if len(serialized.encode("utf-8")) > 32768:
        raise AuditError("Audit metadata exceeds limits")
    return serialized


class AuditWriter:
    """Use a separate 32-byte minimum secret held outside the database.

    Callers enforce tenant authorization. This class provides no administrative
    bypass or update/delete operations. One connection per operation permits
    use by concurrent request threads. Appends use SQLite's reserved write lock.
    """

    def __init__(self, db_path: Path, key: bytes):
        if not isinstance(key, bytes) or len(key) < 32:
            raise AuditError("Audit key must contain at least 32 bytes")
        self.db_path = Path(db_path)
        self._key = key
        self.key_id = hashlib.sha256(b"aspire-audit-key-id\x00" + key).hexdigest()[:24]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        """Create only missing audit tables; reject incompatible schema versions."""
        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS audit_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM audit_meta WHERE name='schema_version'"
            ).fetchone()
            if row is not None and row[0] != str(SCHEMA_VERSION):
                raise AuditError("Incompatible audit schema")
            connection.execute(
                "INSERT OR IGNORE INTO audit_meta(name,value) VALUES ('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                key_id TEXT NOT NULL, tenant_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence>0),
                timestamp TEXT NOT NULL, request_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                event_type TEXT NOT NULL, metadata_json TEXT NOT NULL,
                previous_hmac TEXT NOT NULL, current_hmac TEXT NOT NULL,
                UNIQUE(tenant_id, sequence)
            )""")
            connection.execute(
                "SELECT " + ",".join(PAYLOAD_COLUMNS) + ",current_hmac FROM audit_events LIMIT 0"
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise AuditError("Audit persistence unavailable") from exc
        finally:
            if connection is not None:
                connection.close()

    def _mac(self, event: dict) -> str:
        payload = {name: event[name] for name in PAYLOAD_COLUMNS if name != "metadata_json"}
        payload["metadata"] = json.loads(event["metadata_json"])
        return hmac.new(
            self._key, DOMAIN + _canonical(payload).encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def append(
        self, tenant_id: str, principal_id: str, request_id: str, event_type: str, metadata: dict
    ) -> str:
        """Durably commit an event or raise; never permit best-effort success."""
        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            event_id = self.append_in_transaction(
                connection, tenant_id, principal_id, request_id, event_type, metadata
            )
            connection.commit()
            return event_id
        except sqlite3.Error as exc:
            raise AuditError("Audit persistence unavailable") from exc
        finally:
            if connection is not None:
                connection.close()

    def append_in_transaction(
        self,
        connection: sqlite3.Connection,
        tenant_id: str,
        principal_id: str,
        request_id: str,
        event_type: str,
        metadata: dict,
    ) -> str:
        """Append to caller's BEGIN IMMEDIATE transaction; caller must commit.

        Use this to atomically save a protected packet or controlled state change
        and its audit outcome. Do not return evidence before the caller commits.
        """
        if not connection.in_transaction:
            raise AuditError("Audit append requires an active write transaction")
        for value in (tenant_id, principal_id, request_id, event_type):
            _identifier(value)
        metadata_json = _metadata(metadata)
        try:
            return self._insert(
                connection, tenant_id, principal_id, request_id, event_type, metadata_json
            )
        except sqlite3.Error as exc:
            raise AuditError("Audit persistence unavailable") from exc

    def _insert(self, connection, tenant_id, principal_id, request_id, event_type, metadata_json):
        cursor = connection.cursor()
        cursor.row_factory = sqlite3.Row
        previous = cursor.execute(
            "SELECT sequence,current_hmac,key_id FROM audit_events WHERE tenant_id=? ORDER BY sequence DESC LIMIT 1",
            (tenant_id,),
        ).fetchone()
        if previous is not None and previous["key_id"] != self.key_id:
            raise AuditError("Audit key does not match existing chain")
        if previous is not None and (
            type(previous["sequence"]) is not int
            or previous["sequence"] < 1
            or not isinstance(previous["current_hmac"], str)
            or not DIGEST.fullmatch(previous["current_hmac"])
        ):
            raise AuditError("Invalid stored audit chain head")
        event = {
            "event_id": str(uuid4()),
            "schema_version": SCHEMA_VERSION,
            "key_id": self.key_id,
            "tenant_id": tenant_id,
            "sequence": previous["sequence"] + 1 if previous else 1,
            "timestamp": datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "request_id": request_id,
            "principal_id": principal_id,
            "event_type": event_type,
            "metadata_json": metadata_json,
            "previous_hmac": previous["current_hmac"] if previous else GENESIS,
        }
        values = tuple(event[name] for name in PAYLOAD_COLUMNS) + (self._mac(event),)
        cursor.execute(
            "INSERT INTO audit_events ("
            + ",".join(PAYLOAD_COLUMNS)
            + ",current_hmac) VALUES ("
            + ",".join("?" for _ in values)
            + ")",
            values,
        )
        return event["event_id"]

    def _read(self, tenant_id: str, limit: int | None = None, offset: int = 0) -> list[dict]:
        _identifier(tenant_id)
        connection = None
        try:
            connection = self._connect()
            sql = "SELECT * FROM audit_events WHERE tenant_id=? ORDER BY sequence"
            parameters: tuple = (tenant_id,)
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                parameters += (limit, offset)
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        except sqlite3.Error as exc:
            raise AuditError("Audit persistence unavailable") from exc
        finally:
            if connection is not None:
                connection.close()

    def events(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """Return minimised tenant metadata; the route must authorize audit access."""
        if (
            type(limit) is not int
            or type(offset) is not int
            or not 1 <= limit <= 1000
            or offset < 0
        ):
            raise AuditError("Invalid audit pagination")
        result = []
        for event in self._read(tenant_id, limit, offset):
            try:
                metadata = json.loads(event["metadata_json"])
                _metadata(metadata)
                result.append(
                    {name: value for name, value in event.items() if name != "metadata_json"}
                    | {"metadata": metadata}
                )
            except (ValueError, TypeError) as exc:
                raise AuditError("Invalid stored audit metadata") from exc
        return result

    def _inspect(self, tenant_id: str, events: list[dict], checkpoint: dict | None) -> dict:
        errors: list[str] = []
        previous = GENESIS
        incomplete: dict[str, bool] = {}
        for expected_sequence, event in enumerate(events, 1):
            try:
                valid = (
                    event["sequence"] == expected_sequence
                    and event["schema_version"] == SCHEMA_VERSION
                    and event["key_id"] == self.key_id
                    and event["tenant_id"] == tenant_id
                    and hmac.compare_digest(event["previous_hmac"], previous)
                    and hmac.compare_digest(event["current_hmac"], self._mac(event))
                )
            except (TypeError, ValueError, KeyError):
                valid = False
            if not valid:
                errors.append("invalid_event_at_sequence_" + str(expected_sequence))
            previous = event["current_hmac"]
            if event["event_type"] == "query_attempt":
                incomplete[event["request_id"]] = True
            elif event["event_type"] in TERMINAL_EVENTS:
                incomplete.pop(event["request_id"], None)
        chain_valid = not errors
        anchored, anchored_sequence = self._check_anchor(
            events, checkpoint, tenant_id, chain_valid, errors
        )
        return {
            "tenant_id": tenant_id,
            "schema_version": SCHEMA_VERSION,
            "key_id": self.key_id,
            "chain_valid": chain_valid,
            "verified_through_checkpoint": anchored,
            "completeness_unproven": True,
            "event_count": len(events),
            "head_sequence": events[-1]["sequence"] if events else 0,
            "head_hmac": previous,
            "checkpoint_sequence": anchored_sequence,
            "unanchored_tail_events": max(0, len(events) - anchored_sequence)
            if anchored
            else len(events),
            "incomplete_requests": sorted(incomplete),
            "errors": errors,
            "limitation": "A trusted external checkpoint anchors only its prefix. Completeness of a later tail is unproven; database and key compromise permits forgery.",
        }

    def _check_anchor(self, events, checkpoint, tenant_id, chain_valid, errors):
        if checkpoint is None:
            return False, 0
        required = {"tenant_id", "schema_version", "key_id", "sequence", "head_hmac"}
        if not isinstance(checkpoint, dict) or set(checkpoint) != required:
            errors.append("invalid_checkpoint")
            return False, 0
        sequence = checkpoint["sequence"]
        if (
            checkpoint["tenant_id"] != tenant_id
            or checkpoint["schema_version"] != SCHEMA_VERSION
            or checkpoint["key_id"] != self.key_id
            or type(sequence) is not int
            or sequence < 0
            or not isinstance(checkpoint["head_hmac"], str)
            or not DIGEST.fullmatch(checkpoint["head_hmac"])
        ):
            errors.append("checkpoint_scope_mismatch")
            return False, 0
        if sequence > len(events):
            errors.append("checkpoint_missing")
            return False, sequence
        observed = events[sequence - 1]["current_hmac"] if sequence else GENESIS
        if (
            not isinstance(observed, str)
            or not DIGEST.fullmatch(observed)
            or not hmac.compare_digest(observed, checkpoint["head_hmac"])
        ):
            errors.append("checkpoint_head_mismatch")
            return False, sequence
        return chain_valid, sequence

    def verify(self, tenant_id: str, checkpoint: dict | None = None) -> dict:
        """Verify sequence-ordered rows and, optionally, a caller-trusted anchor."""
        return self._inspect(tenant_id, self._read(tenant_id), checkpoint)

    def checkpoint(self, tenant_id: str) -> dict:
        """Export a chain head; independence/trust of retained storage is external."""
        result = self.verify(tenant_id)
        if not result["chain_valid"]:
            raise AuditError("Cannot checkpoint an invalid audit chain")
        return {
            "tenant_id": tenant_id,
            "schema_version": SCHEMA_VERSION,
            "key_id": self.key_id,
            "sequence": result["head_sequence"],
            "head_hmac": result["head_hmac"],
        }
