"""Encrypted, officer-only reconstruction of every query, answered or not.

The protected store keeps the exact question, the full answer, the retrieved identifiers and
the per-document allow/deny decisions, under a key separate from the session and HMAC audit
keys. It covers both query paths: the four-platform path (``simulated_protected_query``) and
the travel-policy path (``protected_query``, whose documents are reported on the
``policy_store`` platform). A query that is aborted or fails after retrieval keeps the same
record, with what was retrieved and sent to the provider and no answer. An authorised officer
can search it by user, by document or space, by platform and by time, in any combination.

Retention is explicit: :meth:`ProtectedAuditStore.apply_retention` removes only the encrypted
payload and records why. The HMAC chain is never truncated, so its unanchored tail remains
visible as an unproven completeness claim, and a payload that disappears without a retention
record is still treated as tampering.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aspire_brain.audit.engine import AuditError
from aspire_brain.audit.retention import RETENTION_NOTE, RetentionPolicy
from aspire_brain.auth import AccessDenied

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
PLATFORMS = frozenset({"confluence", "jira", "slack", "drive", "policy_store"})
#: Audit operations whose terminal event has a protected payload.
PROTECTED_OPERATIONS = frozenset({"simulated_protected_query", "protected_query"})
TERMINAL_EVENTS = frozenset({"query_completed", "query_aborted", "query_failed"})
MAX_PAYLOAD = 1_048_576
#: Officer-inquiry page bounds. The default page matches the historical behaviour; a larger
#: page is allowed but still bounded so one request cannot read an unbounded result set.
DEFAULT_INQUIRY_LIMIT = 100
MAX_INQUIRY_LIMIT = 500

ANCHORING_NOTE = (
    "A trusted external checkpoint anchors only its prefix. The unanchored tail is not proof "
    "of completeness, and database or key compromise permits forgery."
)


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid inquiry identifier")


class ProtectedAuditStore:
    """Store AES-GCM payloads in the audit database, separate from routine metadata.

    The 32-byte minimum secret must be separate from session and HMAC audit keys. The caller
    must write the payload in the same transaction as its completion audit event.
    """

    def __init__(self, db_path: Path, key: bytes, audit, auth, retention=None):
        if not isinstance(key, bytes) or len(key) < 32:
            raise AuditError("Protected audit key must contain at least 32 bytes")
        if retention is not None and not isinstance(retention, RetentionPolicy):
            raise AuditError("Retention must be a declared RetentionPolicy")
        self.db_path = Path(db_path)
        self._cipher = AESGCM(hashlib.sha256(b"aspire-protected-audit-key:v1\0" + key).digest())
        # A separate derivation authenticates inquiry cursors, so a caller cannot forge or
        # transplant a continuation token.
        self._cursor_key = hashlib.sha256(b"aspire-protected-cursor:v1\0" + key).digest()
        self.audit = audit
        self.auth = auth
        self.retention = retention

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self):
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS protected_audit_payloads (
                    request_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    audit_event_id TEXT NOT NULL UNIQUE, nonce BLOB NOT NULL,
                    ciphertext BLOB NOT NULL)""")
                connection.execute("""CREATE INDEX IF NOT EXISTS protected_audit_tenant
                    ON protected_audit_payloads(tenant_id)""")
                # A retention record is what separates an expired payload from a tampered one.
                connection.execute("""CREATE TABLE IF NOT EXISTS protected_audit_retention (
                    request_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    audit_event_id TEXT NOT NULL, removed_at TEXT NOT NULL,
                    policy TEXT NOT NULL)""")
                connection.execute("""CREATE INDEX IF NOT EXISTS protected_audit_retention_tenant
                    ON protected_audit_retention(tenant_id)""")
        except sqlite3.Error as exc:
            raise AuditError("Protected audit persistence unavailable") from exc

    @staticmethod
    def _aad(tenant_id, request_id, event_id):
        return f"aspire-protected-audit:v1\0{tenant_id}\0{request_id}\0{event_id}".encode()

    def store_in_transaction(self, connection, tenant_id, request_id, event_id, payload):
        if not connection.in_transaction:
            raise AuditError("Protected audit write requires transaction")
        for value in (tenant_id, request_id, event_id):
            _identifier(value)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > MAX_PAYLOAD:
            raise AuditError("Protected audit payload exceeds limit")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, encoded,
                                          self._aad(tenant_id, request_id, event_id))
        try:
            connection.execute("INSERT INTO protected_audit_payloads VALUES (?,?,?,?,?)",
                               (request_id, tenant_id, event_id, nonce, ciphertext))
        except sqlite3.Error as exc:
            raise AuditError("Protected audit persistence unavailable") from exc

    def _decrypt(self, row):
        try:
            encoded = self._cipher.decrypt(
                row["nonce"], row["ciphertext"],
                self._aad(row["tenant_id"], row["request_id"], row["audit_event_id"]),
            )
            if len(encoded) > MAX_PAYLOAD:
                raise AuditError("Invalid protected audit payload")
            return json.loads(encoded)
        except (InvalidTag, ValueError, TypeError, UnicodeError) as exc:
            raise AuditError("Protected audit payload integrity failure") from exc

    def _events(self, tenant_id):
        offset = 0
        result = []
        while True:
            page = self.audit.events(tenant_id, limit=1000, offset=offset)
            result.extend(page)
            if len(page) < 1000:
                return result
            offset += 1000

    # -- retention ---------------------------------------------------------------

    def _retention_plan(self, connection, tenant_id, cutoff):
        """Order one tenant's stored payloads oldest first and decide which exceed the policy."""
        rows = connection.execute(
            "SELECT p.request_id, p.tenant_id, p.audit_event_id, e.timestamp "
            "FROM protected_audit_payloads p LEFT JOIN audit_events e "
            "ON e.event_id = p.audit_event_id WHERE p.tenant_id=?", (tenant_id,)).fetchall()
        ordered = sorted(rows, key=lambda row: (row["timestamp"] or "", row["request_id"]))
        if any(row["timestamp"] is None for row in ordered):
            raise AuditError("Protected audit payload has no audit event")
        expired_by_age = {row["request_id"] for row in ordered
                          if datetime.fromisoformat(
                              row["timestamp"].replace("Z", "+00:00")) < cutoff}
        remaining = [row for row in ordered if row["request_id"] not in expired_by_age]
        keep = {row["request_id"] for row in remaining[-self.retention.max_entries:]}
        reasons, removed = {}, []
        for row in ordered:
            if row["request_id"] in expired_by_age:
                reasons[row["request_id"]] = "max_age"
                removed.append(row)
            elif row["request_id"] not in keep:
                reasons[row["request_id"]] = "max_entries"
                removed.append(row)
        return ordered, removed, reasons

    def _retention_digest(self, connection, tenant_id):
        """A digest over one tenant's current retention records, bound into the HMAC chain."""
        rows = connection.execute(
            "SELECT request_id, audit_event_id, removed_at FROM protected_audit_retention "
            "WHERE tenant_id=? ORDER BY request_id", (tenant_id,)).fetchall()
        payload = "\n".join(f"{row['request_id']}|{row['audit_event_id']}|{row['removed_at']}"
                            for row in rows)
        return self.audit.response_digest(payload.encode("utf-8"))

    def apply_retention(self, *, tenant_id, now, apply=False):
        """Apply the declared retention policy to one tenant.

        ``apply=False`` is a non-destructive rehearsal that still reports the plan. Retention is
        always tenant-scoped: one tenant's volume can never evict another tenant's payloads. When
        applied, the tombstones, the deletions and the ``retention_applied`` audit event commit in
        one transaction, and the event binds the resulting tombstone set to the HMAC chain.
        """
        if self.retention is None:
            raise AuditError("No retention policy is declared for protected audit payloads")
        _identifier(tenant_id)
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Retention time needs a timezone")
        cutoff = now - timedelta(days=self.retention.max_age_days)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            ordered, removed, reasons = self._retention_plan(connection, tenant_id, cutoff)
            if apply and removed:
                policy = json.dumps(self.retention.model_dump(mode="json"), sort_keys=True)
                for row in removed:
                    connection.execute(
                        "INSERT INTO protected_audit_retention VALUES (?,?,?,?,?)",
                        (row["request_id"], row["tenant_id"], row["audit_event_id"],
                         now.isoformat(), policy))
                    connection.execute("DELETE FROM protected_audit_payloads WHERE request_id=?",
                                       (row["request_id"],))
                self.audit.append_in_transaction(
                    connection, tenant_id, "system",
                    "retention-" + now.strftime("%Y%m%dT%H%M%SZ"), "retention_applied",
                    {"operation": "protected_audit_retention", "status": "applied",
                     "changed_fields": ["protected_audit_payloads"],
                     "source_count": len(removed),
                     "response_digest": self._retention_digest(connection, tenant_id)},
                )
        return {
            "mode": "simulated", "applied": bool(apply), "tenant_id": tenant_id,
            "policy": self.retention.model_dump(mode="json"),
            "evaluated": len(ordered), "would_remove": len(removed),
            "removed": len(removed) if apply else 0,
            "retained": len(ordered) - len(removed),
            "planned_request_ids": sorted(reasons),
            "removed_request_ids": sorted(reasons) if apply else [],
            "removal_reasons": reasons,
            "chain_preserved": True, "note": RETENTION_NOTE,
        }

    # -- officer inquiry ---------------------------------------------------------

    @staticmethod
    def _binding(subject_id, platform, parent_id, source_id, decision_mode, since, until):
        """A digest over the search filters a continuation token is bound to."""
        material = json.dumps([subject_id, platform, parent_id, source_id, decision_mode,
                               since.astimezone(UTC).isoformat(),
                               until.astimezone(UTC).isoformat()],
                              sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode()).hexdigest()

    def _encode_cursor(self, tenant_id, binding, last):
        body = json.dumps({"v": 1, "tenant": tenant_id, "binding": binding,
                           "timestamp": last["timestamp"], "request_id": last["request_id"]},
                          sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + signature

    def _decode_cursor(self, cursor, tenant_id, binding):
        """Return the ``(timestamp, request_id)`` a continuation resumes after.

        A cursor is rejected unless its signature verifies *and* it was issued for this tenant
        and this exact filter set, so a cross-tenant or cross-search token cannot be replayed.
        """
        if not isinstance(cursor, str) or "." not in cursor:
            raise ValueError("Invalid inquiry cursor")
        encoded, signature = cursor.rsplit(".", 1)
        try:
            body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid inquiry cursor") from exc
        expected = hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid inquiry cursor")
        try:
            data = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid inquiry cursor") from exc
        if (not isinstance(data, dict) or data.get("v") != 1
                or data.get("tenant") != tenant_id or data.get("binding") != binding
                or not isinstance(data.get("timestamp"), str)
                or not isinstance(data.get("request_id"), str)):
            raise ValueError("Invalid inquiry cursor")
        return data["timestamp"], data["request_id"]

    def _retention_state(self, connection, tenant_id):
        rows = connection.execute(
            "SELECT request_id FROM protected_audit_retention WHERE tenant_id=?",
            (tenant_id,)).fetchall()
        removed = sorted(row["request_id"] for row in rows)
        return {
            "policy": self.retention.model_dump(mode="json") if self.retention else None,
            "removed_count": len(removed), "removed_request_ids": removed,
            "note": RETENTION_NOTE,
            "_chain_digest": self._retention_digest(connection, tenant_id),
        }

    def _verified_packet(self, payload, event):
        """Check a payload against the digest its terminal event committed to.

        A completed four-platform record is digested over its packet. Every other record
        (travel-policy answers, and aborted or failed queries on either path) carries the exact
        text that was digested, so the check needs no re-serialisation. Returns the answer
        packet, or ``None`` for a query that produced none.
        """
        expected = event["metadata"].get("response_digest")
        if "digest_input" in payload:
            text = payload["digest_input"]
            if (not isinstance(text, str)
                    or self.audit.response_digest(text.encode()) != expected):
                raise AuditError("Protected audit response mismatch")
            packet = payload.get("packet")
            if event["event_type"] == "query_completed":
                if not isinstance(packet, dict) or packet.get("audit_event_id") != event["event_id"]:
                    raise AuditError("Protected audit packet mismatch")
                return packet
            if packet is not None:
                raise AuditError("Protected audit packet mismatch")
            return None
        packet = payload.get("packet")
        if (event["event_type"] != "query_completed" or not isinstance(packet, dict)
                or packet.get("audit_event_id") != event["event_id"]):
            raise AuditError("Protected audit packet mismatch")
        digest_packet = {**packet, "audit_event_id": "pending"}
        if self.audit.response_digest(json.dumps(digest_packet, sort_keys=True).encode()) != expected:
            raise AuditError("Protected audit response mismatch")
        return packet

    def store_terminal(self, connection, *, tenant_id, principal_id, request_id, event_type,
                       operation, error_code, question, trace):
        """Record an aborted or failed query with what it retrieved, in the caller's transaction.

        ``trace`` holds the ``decisions`` and ``retrieved_ids`` reached before the failure. The
        terminal audit event commits to the exact payload text, so the officer view can verify it.
        """
        payload = {"subject_id": principal_id, "question": question, "packet": None,
                   "retrieved_ids": list(trace.get("retrieved_ids", [])),
                   "decisions": list(trace.get("decisions", [])),
                   "provider_mode": trace.get("provider_mode"), "error_code": error_code}
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event_id = self.audit.append_in_transaction(
            connection, tenant_id, principal_id, request_id, event_type,
            {"error_code": error_code, "operation": operation,
             "response_digest": self.audit.response_digest(text.encode()),
             "source_count": len(payload["retrieved_ids"])})
        self.store_in_transaction(connection, tenant_id, request_id, event_id,
                                  {**payload, "digest_input": text})
        return event_id

    def inquire(self, officer_id, *, since, until, subject_id=None, platform=None,
                parent_id=None, source_id=None, decision_mode="retrieved",
                limit=DEFAULT_INQUIRY_LIMIT, cursor=None):
        """Search protected query records.

        ``subject_id`` (who asked), ``platform``, ``parent_id`` (space, project, channel, folder
        or policy document) and ``source_id`` (one item) are all optional filters, but at least
        one of who and what is required: "what did user X access" and "who retrieved this
        document" are both supported.
        """
        if subject_id is None and parent_id is None and source_id is None:
            raise ValueError("Inquiry needs a user, a space or a document")
        for value in (subject_id, parent_id, source_id):
            if value is not None:
                _identifier(value)
        if platform is not None and platform not in PLATFORMS:
            raise ValueError("Invalid inquiry platform")
        if decision_mode not in {"retrieved", "denied", "any"}:
            raise ValueError("Invalid inquiry decision mode")
        if type(limit) is not int or not 1 <= limit <= MAX_INQUIRY_LIMIT:
            raise ValueError("Invalid inquiry page size")
        if not isinstance(since, datetime) or not isinstance(until, datetime) or (
            since.tzinfo is None or until.tzinfo is None or since >= until
        ):
            raise ValueError("Invalid inquiry time window")
        binding = self._binding(subject_id, platform, parent_id, source_id, decision_mode,
                                since, until)
        officer = self.auth.principal(officer_id)
        if "audit" not in officer["roles"]:
            raise AccessDenied("Audit access required")
        after = (self._decode_cursor(cursor, officer["tenant_id"], binding)
                 if cursor is not None else None)
        with closing(self._connect()) as connection:
            if subject_id is not None:
                subject = connection.execute("SELECT tenant_id FROM principals WHERE id=?",
                                             (subject_id,)).fetchone()
                if subject is None or subject["tenant_id"] != officer["tenant_id"]:
                    raise AccessDenied("Audit subject unavailable")
            rows = connection.execute("SELECT * FROM protected_audit_payloads WHERE tenant_id=?",
                                      (officer["tenant_id"],)).fetchall()
            retention = self._retention_state(connection, officer["tenant_id"])
        integrity = self.audit.verify(officer["tenant_id"])
        if not integrity["chain_valid"]:
            raise AuditError("Audit chain integrity failure")
        chain = self._events(officer["tenant_id"])
        events = {event["request_id"]: event for event in chain
                  if event["event_type"] in TERMINAL_EVENTS
                  and event["metadata"].get("operation") in PROTECTED_OPERATIONS}
        stored = {row["request_id"] for row in rows}
        if not stored <= set(events):
            raise AuditError("Protected audit event or payload missing")
        # A payload removed by the declared policy is explained; one that simply vanished is not.
        unaccounted = set(events) - stored - set(retention["removed_request_ids"])
        if unaccounted:
            raise AuditError("Protected audit event or payload missing")
        # The tombstone set must match the digest the chain recorded, so a forged or deleted
        # retention record cannot pass itself off as an explanation.
        if retention["removed_count"] and not any(
            event["metadata"].get("operation") == "protected_audit_retention"
            and event["metadata"].get("response_digest") == retention["_chain_digest"]
            for event in chain
        ):
            raise AuditError("Protected audit retention is not covered by the audit chain")
        retention.pop("_chain_digest")
        matches = []
        for row in rows:
            event = events[row["request_id"]]
            if event["event_id"] != row["audit_event_id"]:
                raise AuditError("Protected audit event mismatch")
            payload = self._decrypt(row)
            packet = self._verified_packet(payload, event)
            if payload.get("subject_id") != event["principal_id"]:
                raise AuditError("Protected audit subject mismatch")
            timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            # With no document filter the inquiry is about the user and period alone, and the
            # decision mode (which concerns an item) does not apply. A query stopped before any
            # document decision, such as an aborted or failed one, therefore still matches.
            document_filter = (platform, parent_id, source_id) != (None, None, None)
            if ((subject_id is None or event["principal_id"] == subject_id)
                and since <= timestamp < until and
                (not document_filter or
                any((platform is None or decision.get("platform") == platform) and
                    (parent_id is None or decision.get("parent_id") == parent_id) and
                    (source_id is None or decision.get("source_id") == source_id)
                    and (decision_mode == "any" or
                         (decision_mode == "retrieved" and decision.get("retrieved") is True) or
                         (decision_mode == "denied" and decision.get("allowed") is False))
                    for decision in payload.get("decisions", [])))):
                matches.append({
                    "request_id": row["request_id"], "audit_event_id": event["event_id"],
                    "timestamp": timestamp.astimezone(UTC).isoformat(),
                    "subject_id": event["principal_id"],
                    "operation": event["metadata"].get("operation"),
                    "outcome": event["event_type"],
                    "error_code": event["metadata"].get("error_code"),
                    "question": payload["question"],
                    "answer": packet["answer"] if packet else None,
                    "retrieved_ids": payload["retrieved_ids"],
                    "decisions": payload["decisions"],
                    "query_status": (packet["query_status"] if packet
                                     else event["event_type"].removeprefix("query_")),
                    "provider_mode": (packet or payload).get("provider_mode"),
                    "claim_support": packet.get("claim_support") if packet else None,
                    "provider_runtime": packet.get("provider_runtime") if packet else None,
                })
        # A stable ``(timestamp, request_id)`` order makes every page deterministic and lets a
        # continuation resume exactly after the last entry without omission or duplication,
        # including when several entries share a timestamp.
        matches.sort(key=lambda entry: (entry["timestamp"], entry["request_id"]))
        total_matches = len(matches)
        if after is not None:
            matches = [entry for entry in matches
                       if (entry["timestamp"], entry["request_id"]) > after]
        page = matches[:limit]
        next_cursor = (self._encode_cursor(officer["tenant_id"], binding, page[-1])
                       if len(matches) > limit else None)
        return {"simulation_mode": "simulated", "scope": "all_protected_queries",
                "filters": {"subject_id": subject_id, "platform": platform,
                            "parent_id": parent_id, "source_id": source_id},
                "decision_mode": decision_mode, "limit": limit,
                "entries": page, "returned": len(page), "has_more": len(matches) > limit,
                "next_cursor": next_cursor, "total_matches": total_matches,
                "integrity": integrity,
                "retention": retention,
                "checkpoint_anchoring": {
                    "verified_through_checkpoint": integrity["verified_through_checkpoint"],
                    "unanchored_tail_events": integrity["unanchored_tail_events"],
                    "completeness_unproven": integrity["completeness_unproven"],
                    "note": ANCHORING_NOTE,
                }}
