"""G3 leakage assessment across denied, absent and budget-excluded sources.

Bounded comparison cases measure existence, count, error-shape and timing leakage. The
timing numbers here are observed on a tiny local fixture and are reported, not asserted:
this fixture cannot establish timing non-disclosure for a real deployment.
"""

import asyncio
import hashlib
import json
import secrets
import statistics
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.config import Settings
from aspire_brain.db import Database
from aspire_brain.main import create_app
from aspire_brain.platforms.routing import ContextBudget
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
SENTINEL = "FORBIDDEN_LEAKAGE_SENTINEL"
QUESTION = "What does the payment incident runbook say about failover?"


def rec(source_id, kind, parent, text, acl_ok=True):
    return SimulatedSource(
        platform="confluence", tenant_id="demo-a", source_id=source_id, source_kind=kind,
        version_id=f"{source_id}:v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
        locator=f"simulated://confluence/{source_id}", parent_id=parent,
        source_updated_at="2026-09-27T07:55:00Z",
    )


def build_state(records, *, space_grants, page_grants):
    return SimulatedPlatformState(
        records=records,
        principal_map={"employee": {"confluence": "conf-employee"}},
        confluence_space_grants=space_grants,
        confluence_page_grants=page_grants,
        last_successful_sync={"confluence": NOW},
        freshness_budget_seconds={"confluence": 3600},
    )


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g3leak.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"g3-leakage-audit-key-is-separate-12345")
    audit.initialize()
    return AuthService(db), audit


def denied_state():
    """A restricted record exists, but the caller has no grant."""
    return build_state(
        [rec("SECRET-1", "space_page_restricted", "SEC", "Payment incident runbook " + SENTINEL)],
        space_grants={"SEC": set()}, page_grants={"SECRET-1": set()})


def absent_state():
    """No record exists at all."""
    return build_state([], space_grants={}, page_grants={})


def permitted_state():
    return build_state(
        [rec("RUNBOOK-1", "space_page", "OPS", "Payment incident runbook: enable failover.")],
        space_grants={"OPS": {"conf-employee"}},
        page_grants={"RUNBOOK-1": {"conf-employee"}})


def outward(packet):
    return {key: value for key, value in packet.items()
            if key not in {"request_id", "audit_event_id", "source_status"}}


# --- Existence and count leakage ---

def test_denied_and_absent_sources_are_outwardly_indistinguishable(system):
    auth, audit = system
    denied = asyncio.run(SimulatedQueryService(
        auth, audit, denied_state(), required_platforms=("confluence",),
        clock=lambda: NOW).query("employee", QUESTION, NOW))
    absent = asyncio.run(SimulatedQueryService(
        auth, audit, absent_state(), required_platforms=("confluence",),
        clock=lambda: NOW).query("employee", QUESTION, NOW))
    assert outward(denied) == outward(absent)
    assert denied["query_status"] == absent["query_status"] == "abstained"
    assert denied["citations"] == absent["citations"] == []


def test_denied_packet_discloses_no_source_identifier_or_count(system):
    auth, audit = system
    packet = asyncio.run(SimulatedQueryService(
        auth, audit, denied_state(), required_platforms=("confluence",),
        clock=lambda: NOW).query("employee", QUESTION, NOW))
    serialized = json.dumps(packet)
    assert "SECRET-1" not in serialized
    assert "SEC" not in serialized.replace("SECURITY", "")
    assert SENTINEL not in serialized
    # No top-level count field, and no denied-record tally anywhere.
    assert not any("count" in key for key in packet)
    assert "denied" not in serialized


# --- Budget-excluded disclosure ---

def test_budget_excluded_source_is_disclosed_but_its_text_is_not(system):
    auth, audit = system
    state = build_state(
        [rec("RUNBOOK-1", "space_page", "OPS", "Payment incident runbook failover step alpha."),
         rec("RUNBOOK-2", "space_page", "OPS", "Payment incident runbook failover step beta.")],
        space_grants={"OPS": {"conf-employee"}},
        page_grants={"RUNBOOK-1": {"conf-employee"}, "RUNBOOK-2": {"conf-employee"}})
    service = SimulatedQueryService(auth, audit, state, required_platforms=("confluence",),
                                    budget=ContextBudget(max_items=1, max_chars=100000),
                                    clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))
    dropped_ids = packet["context_budget"]["dropped_ids"]
    assert dropped_ids
    # The reader may see what was dropped (they can read it); the text itself is not included.
    for dropped_id in dropped_ids:
        source_id = dropped_id.split(":")[1]
        assert state.records[("confluence", source_id)].text not in packet["answer"]


# --- Sentinel containment across every boundary ---

def test_forbidden_text_never_reaches_context_response_logs_or_packet(system):
    auth, audit = system
    state = build_state(
        [rec("RUNBOOK-1", "space_page", "OPS", "Payment incident runbook failover."),
         rec("SECRET-1", "space_page_restricted", "SEC", "Payment incident runbook " + SENTINEL)],
        space_grants={"OPS": {"conf-employee"}, "SEC": set()},
        page_grants={"RUNBOOK-1": {"conf-employee"}, "SECRET-1": set()})
    seen = []

    from aspire_brain.providers import OfflineExtractiveProvider

    class Spy(OfflineExtractiveProvider):
        async def generate(self, context):
            seen.append(context.model_dump_json())
            return await super().generate(context)

    service = SimulatedQueryService(auth, audit, state, required_platforms=("confluence",),
                                    provider=Spy(), clock=lambda: NOW)
    packet = asyncio.run(service.query("employee", QUESTION, NOW))

    assert SENTINEL not in "".join(seen)                      # provider context
    assert SENTINEL not in json.dumps(packet)                 # response
    assert SENTINEL not in json.dumps(audit.events("demo-a"))  # logs
    assert SENTINEL not in json.dumps(service.packet("employee", packet["request_id"]))
    with closing(auth.db.connect()) as connection:
        rows = connection.execute("SELECT packet FROM simulated_packets").fetchall()
    assert SENTINEL not in "".join(row["packet"] for row in rows)  # stored packet


# --- Error-shape leakage at the HTTP boundary ---

def client_for(settings):
    return TestClient(create_app(settings), base_url="http://localhost",
                      client=("127.0.0.1", 50000))


def headers(client):
    session = client.get("/api/session").json()
    return {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}


@pytest.fixture
def browser_client(tmp_path):
    settings = Settings(db_path=tmp_path / "leak-cases.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)
    with client_for(settings) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=headers(client)).status_code == 200
        yield client


def test_source_error_shape_is_identical_for_denied_and_unknown(browser_client):
    # p17-contract-v1 is restricted to finance; the other id does not exist.
    denied = browser_client.get("/api/sources/p17-contract-v1/any-chunk")
    unknown = browser_client.get("/api/sources/does-not-exist-v1/any-chunk")
    assert denied.status_code == unknown.status_code == 404
    assert denied.json() == unknown.json()


# --- Timing leakage: measured and reported, not asserted ---

def test_timing_is_measured_and_reported_without_a_non_disclosure_claim(system):
    auth, audit = system

    def timed(state):
        samples = []
        for _ in range(5):
            started = time.perf_counter()
            asyncio.run(SimulatedQueryService(
                auth, audit, state, required_platforms=("confluence",),
                clock=lambda: NOW).query("employee", QUESTION, NOW))
            samples.append(time.perf_counter() - started)
        return {"min": min(samples), "max": max(samples), "mean": statistics.mean(samples)}

    measured = {"denied": timed(denied_state()), "absent": timed(absent_state()),
                "permitted": timed(permitted_state())}
    # The numbers are recorded for the report; this fixture cannot prove timing equality.
    assert all(entry["mean"] > 0 for entry in measured.values())
    assert set(measured) == {"denied", "absent", "permitted"}
