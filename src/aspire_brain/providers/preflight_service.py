"""Explicit, single-use synthetic 5E query; never registered as a default provider.

The disposable database contains one fictional source. SDK success must also pass the
unchanged QueryService claim gate, final permissions, atomic publication and readback.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from contextlib import closing
from pathlib import Path

from aspire_brain.answers import QueryError, QueryService
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.providers import ProviderOutput
from aspire_brain.providers.preflight import run_preflight

TENANT = "synthetic-5e"
READER = "synthetic-5e-reader"
VERSION = "synthetic-5e:v1"
CHUNK = "synthetic:5e-control:v1"
TEXT = "Fictional Singapore contractor travel cap: SGD 250 per claim."
QUESTION = "What is the fictional Singapore contractor travel cap?"
TEXT_SHA = hashlib.sha256(TEXT.encode()).hexdigest()


def _initial_runtime(mock):
    return {"status": "not_sent", "mode": "offline_mock" if mock else "live",
            "attempt": 0, "live_request_made": False, "postflight_validated": False,
            "settled_cost_usd": None, "uncertain_cost_usd": "0", "output": None,
            "slot_consumed": False, "network_attempted": False}


class ServiceSmokeProvider:
    """Bind one request-scoped dispatch to one concrete service and frozen projection."""

    def __init__(self, candidate, *, api_key, ledger_path, inner=None):
        self.candidate = candidate
        self._api_key = api_key
        self.ledger_path = Path(ledger_path)
        self.inner = inner
        self.mode = "stage5e_service_offline_mock" if inner is not None else "stage5e_service_live"
        self.runtime = _initial_runtime(inner is not None) | {
            "slot_consumed": self.ledger_path.exists()}
        self.request_id = None
        self._service = None

    def bind(self, service):
        if self._service is not None or service.provider is not self:
            raise ValueError("Preflight service binding unavailable")
        self._service = service

    async def generate(self, context):
        raise ValueError("5E requires the bound request-scoped query service")

    def _check_projection(self, context):
        if (context.question != QUESTION or len(context.evidence) != 1
                or context.evidence[0].chunk_id != CHUNK or context.evidence[0].text != TEXT
                or context.evidence[0].version_id != VERSION
                or context.evidence[0].content_hash != TEXT_SHA):
            raise ValueError("5E projection differs from reviewed synthetic evidence")
        body = json.loads(self.candidate.body_json)
        projected = json.loads(body["messages"][1]["content"])
        if projected != {"question": context.question, "evidence": [
                {"citation_id": CHUNK, "text": TEXT}]}:
            raise ValueError("Candidate does not match service projection")

    async def generate_for_request(self, context, *, request_id, principal, service, snapshot):
        if service is not self._service or service.provider is not self or self.request_id is not None:
            raise ValueError("Preflight request binding unavailable")
        self.request_id = request_id
        self._check_projection(context)
        service._check_snapshot(principal, snapshot)

        def check_source():
            service._check_snapshot(principal, snapshot)
            source = service.auth.source(principal, VERSION, CHUNK)
            if (source["text"] != TEXT or source["content_hash"] != TEXT_SHA
                    or source["state"] != "approved"):
                raise ValueError("Preflight source changed before send")

        def before_send():
            check_source()
            service._audit(principal, request_id, "provider_send_intent", {
                "provider_mode": self.mode, "chunk_ids": [CHUNK], "version_ids": [VERSION],
                "manifest_sha256": self.candidate.fingerprint_sha256,
                "acl_revision": snapshot[1][0], "content_revision": snapshot[1][1],
                "operation": "post_claim" if self.ledger_path.exists() else "pre_claim",
            })
            # An audit writer or concurrent metadata update can revoke access. This is the
            # last synchronous check before the transport persists and consumes its slot.
            check_source()

        self.runtime = run_preflight(self.candidate, api_key=self._api_key,
                                     ledger_path=self.ledger_path, inner=self.inner,
                                     before_send=before_send, request_id=request_id)
        service._audit(principal, request_id, "provider_attempt_result", {
            "provider_mode": self.mode, "status": self.runtime["status"],
            "outcome": "validated" if self.runtime["postflight_validated"] else "rejected",
            "manifest_sha256": self.candidate.fingerprint_sha256,
            **{field: self.runtime.get(field) for field in (
                "attempt", "slot_consumed", "network_attempted", "live_request_made",
                "http_status", "raw_response_sha256", "error_category",
                "provider_error_type", "provider_error_param", "provider_error_reason",
                "settled_cost_usd",
                "uncertain_cost_usd", "vendor_request_id")},
        })
        if not self.runtime["postflight_validated"] or self.runtime.get("output") is None:
            raise ValueError("5E provider did not produce the approved control answer")
        return ProviderOutput.model_validate(self.runtime["output"])


def _audit_key(path):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = path.read_bytes()
    else:
        value = secrets.token_bytes(32)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    if len(value) != 32:
        raise ValueError("Invalid disposable audit key")
    return value


def _synthetic_system(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = Database(state_dir / "synthetic.sqlite")
    db.initialize()
    audit = AuditWriter(db.path, _audit_key(state_dir / "audit.key"))
    audit.initialize()
    with closing(db.connect()) as connection, connection:
        connection.execute("INSERT OR IGNORE INTO tenants(id) VALUES (?)", (TENANT,))
        connection.execute("INSERT OR IGNORE INTO principals VALUES (?,?,1,?)",
                           (READER, TENANT, '["synthetic_reader"]'))
        connection.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?)",
                           ("synthetic-5e-document", TENANT, "synthetic_control", READER))
        connection.execute("INSERT OR IGNORE INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            VERSION, "synthetic-5e-document", TENANT, TEXT, TEXT_SHA, "2026-10-10T00:00:00Z",
            "approved", "2026-10-10", None, "{}", None, '["synthetic_reader"]', TEXT_SHA))
        inserted = connection.execute("INSERT OR IGNORE INTO chunks VALUES (?,?,?,?,?)", (
            CHUNK, VERSION, TEXT, TEXT_SHA, "synthetic://5e-control/v1")).rowcount
        if inserted and db.fts_available:
            connection.execute("INSERT INTO chunks_fts VALUES (?,?)", (CHUNK, TEXT))
        if connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] != 1:
            raise ValueError("Preflight database contains unreviewed sources")
    return db, AuthService(db), audit


def run_service_preflight(candidate, *, api_key, state_dir, inner=None):
    """Run exactly one synthetic QueryService request; failures return minimised reports."""
    state_dir = Path(state_dir).resolve()
    live_state = Path(__file__).resolve().parents[3] / "var/stage5e-corrected-2026-10-10"
    if inner is None and state_dir != live_state:
        raise ValueError("Live single-attempt state must use the fixed authorization directory")
    db, auth, audit = _synthetic_system(state_dir)
    provider = ServiceSmokeProvider(candidate, api_key=api_key,
                                    ledger_path=state_dir / "attempt.json", inner=inner)
    service = QueryService(db, auth, audit, provider=provider)
    provider.bind(service)
    service.timeout_seconds = candidate.config.timeout_seconds + 1
    query = QueryRequest.model_validate({"question": QUESTION, "context": {
        "workflow_id": "general", "case_date": "2026-10-10"}})
    principal = auth.principal(READER)
    packet, readable, status_code = None, False, 200
    initial_sequence = len(audit.events(TENANT, limit=1000))
    try:
        packet = asyncio.run(service.query(principal, query))
        readable = service.packet(principal, packet["request_id"]) == packet
    except QueryError as exc:
        status_code = exc.status_code
    events = audit.events(TENANT, limit=1000)[initial_sequence:]
    request_id = (provider.request_id or (packet or {}).get("request_id")
                  or next((event["request_id"] for event in events
                           if event["event_type"] == "query_attempt"), None))
    with closing(db.connect()) as connection:
        packet_count = connection.execute("SELECT COUNT(*) FROM packets WHERE request_id=?",
                                          (request_id,)).fetchone()[0]
    validated = bool(provider.runtime["postflight_validated"] and packet and readable)
    return provider.runtime | {
        "status": "service_rejected" if provider.runtime["postflight_validated"] and not validated
        else provider.runtime["status"],
        "postflight_validated": validated, "runtime": provider.runtime,
        "service_status_code": status_code, "request_id": request_id, "packet": packet,
        "packet_count": packet_count, "packet_readable": readable,
        "audit_event_types": [event["event_type"] for event in events],
        "audit_rows": events,
        "audit_chain_valid": audit.verify(TENANT)["chain_valid"],
        "database_path": str(db.path), "attempt_ledger_path": str(provider.ledger_path),
        "support_scope": "bounded_verbatim_synthetic_control_not_source_truth",
    }
