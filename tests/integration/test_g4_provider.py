"""G4 grounded-answer provider: permitted evidence only, explicit enablement, minimised records.

These expectations were written before the implementation. They pin the G4 provider contract:

* the provider sees only evidence the caller may read, and never a denied source;
* it cannot introduce a new source identifier or set an authoritative outcome field;
* ``offline_extractive`` stays the default and a live runtime needs explicit enablement
  *and* confirmed entitlement, and is still refused here because none is implemented;
* every local packet carries a minimised runtime record whose live fields are null.
"""

import asyncio
import hashlib
import json
import secrets
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aspire_brain.answers import QueryError
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)
from aspire_brain.providers import (
    ExternalProviderUnavailable,
    OfflineExtractiveProvider,
    ProviderEntitlementError,
    ProviderInput,
    ProviderOutput,
    configured_provider,
)
from aspire_brain.providers.grounded import GroundedAnswerProvider
from aspire_brain.providers.runtime import ProviderRuntimeConfig, runtime_record_for

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
SPACE = "DB"
DENIED_SENTINEL = "CONFIDENTIAL-RESTRICTED-SENTINEL"
QUESTION = "What is the status of the database migration project?"
END_TO_END = "https://api.example-tenant.invalid/v1/chat/completions"


def source(source_id, text, *, kind="issue", parent=SPACE, platform="jira"):
    return SimulatedSource(
        platform=platform, tenant_id="demo-a", source_id=source_id, source_kind=kind,
        version_id=f"{source_id}:v1", content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text, locator=f"simulated://{platform}/{source_id}", parent_id=parent,
        source_updated_at=NOW - timedelta(minutes=5),
    )


def build_state():
    return SimulatedPlatformState(
        records=[
            source("MIGRATE-42", "Database migration project status: in progress. "
                                 "Blocker: connection pool limit."),
            source("SECRET-9", f"Restricted security issue: {DENIED_SENTINEL}."),
        ],
        principal_map={"employee": {"jira": "jira-employee"}},
        jira_project_grants={SPACE: {"jira-employee"}},
        jira_issue_grants={"MIGRATE-42": {"jira-employee"}},
        last_successful_sync={"jira": NOW},
        freshness_budget_seconds={"jira": 3600},
    )


class RecordingGroundedProvider(GroundedAnswerProvider):
    """The real G4 provider, plus a record of exactly what the service handed it."""

    def __init__(self):
        super().__init__()
        self.inputs = []

    async def generate(self, context: ProviderInput) -> ProviderOutput:
        self.inputs.append(context)
        return await super().generate(context)


class HostileCitationProvider(GroundedAnswerProvider):
    """Tries to cite a source identifier the caller was never given."""

    async def generate(self, context: ProviderInput) -> ProviderOutput:
        return ProviderOutput(answer="Database migration is complete.",
                              citation_ids=["jira:SECRET-9:v1"])


class HostileFieldProvider(GroundedAnswerProvider):
    """Tries to set an authoritative outcome field through the provider contract."""

    async def generate(self, context: ProviderInput):
        return {"answer": "Database migration is complete.",
                "citation_ids": [item.chunk_id for item in context.evidence],
                "query_status": "answered"}


class FailingProvider(GroundedAnswerProvider):
    async def generate(self, context: ProviderInput) -> ProviderOutput:
        raise RuntimeError("simulated upstream failure")


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g4-provider.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    auth = AuthService(db)
    state = build_state()

    def service(provider=None):
        return SimulatedQueryService(auth, audit, state, provider=provider,
                                     required_platforms=("jira",), clock=lambda: NOW)

    return db, audit, auth, state, service


def test_grounded_provider_sees_only_permitted_evidence(system):
    _db, _audit, _auth, _state, service = system
    provider = RecordingGroundedProvider()
    packet = asyncio.run(service(provider).query("employee", QUESTION, NOW))
    assert packet["query_status"] == "answered"
    assert len(provider.inputs) == 1
    received = provider.inputs[0]
    assert {item.chunk_id for item in received.evidence} == {"jira:MIGRATE-42:MIGRATE-42:v1"}
    assert DENIED_SENTINEL not in json.dumps(received.model_dump(mode="json"))
    assert "SECRET-9" not in json.dumps(received.model_dump(mode="json"))
    assert received.context == {"simulation_mode": "simulated"}


def test_grounded_answer_cites_only_permitted_evidence(system):
    _db, _audit, _auth, _state, service = system
    packet = asyncio.run(service(GroundedAnswerProvider()).query("employee", QUESTION, NOW))
    assert {item["source_id"] for item in packet["citations"]} == {"MIGRATE-42"}
    assert "migration" in packet["answer"].lower()
    assert packet["provider_mode"] == "fake_grounded"


def test_provider_cannot_introduce_a_new_source_identifier(system):
    _db, _audit, _auth, _state, service = system
    with pytest.raises(QueryError) as failure:
        asyncio.run(service(HostileCitationProvider()).query("employee", QUESTION, NOW))
    assert failure.value.status_code == 502


def test_provider_cannot_set_authoritative_outcome_fields(system):
    _db, _audit, _auth, _state, service = system
    with pytest.raises(QueryError) as failure:
        asyncio.run(service(HostileFieldProvider()).query("employee", QUESTION, NOW))
    assert failure.value.status_code == 502


def test_provider_failure_releases_no_evidence(system):
    db, _audit, _auth, _state, service = system
    with pytest.raises(QueryError) as failure:
        asyncio.run(service(FailingProvider()).query("employee", QUESTION, NOW))
    assert failure.value.status_code == 502
    with closing(db.connect()) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM simulated_packets").fetchone()[0]
    assert rows == 0


def test_offline_extractive_remains_the_default(system):
    _db, _audit, _auth, _state, service = system
    assert configured_provider("offline_extractive").mode == "offline_extractive"
    assert isinstance(configured_provider("offline_extractive"), OfflineExtractiveProvider)
    assert service().provider.mode == "offline_extractive"
    assert configured_provider("fake_grounded").mode == "fake_grounded"


def test_live_provider_requires_explicit_enablement_and_entitlement():
    assert issubclass(ProviderEntitlementError, ExternalProviderUnavailable)
    with pytest.raises(ProviderEntitlementError):
        configured_provider("live_grounded")
    disabled = ProviderRuntimeConfig(service="example", model="example-model",
                                     endpoint=END_TO_END, region="ap-southeast-1")
    assert disabled.enabled is False and disabled.entitlement == "unknown"
    with pytest.raises(ProviderEntitlementError):
        configured_provider("live_grounded", runtime=disabled)
    unentitled = ProviderRuntimeConfig(service="example", model="example-model",
                                       endpoint=END_TO_END, region="ap-southeast-1",
                                       enabled=True, entitlement="unknown")
    with pytest.raises(ProviderEntitlementError):
        configured_provider("live_grounded", runtime=unentitled)
    entitled = ProviderRuntimeConfig(service="example", model="example-model",
                                     endpoint=END_TO_END, region="ap-southeast-1",
                                     enabled=True, entitlement="entitled")
    # Entitlement alone is not enough: no live runtime is implemented, so no request is made.
    with pytest.raises(ExternalProviderUnavailable):
        configured_provider("live_grounded", runtime=entitled)


def test_runtime_config_rejects_credentials_and_non_https_endpoints():
    for endpoint in ("https://user:secret@host.invalid/v1", "http://host.invalid/v1",
                     f"{END_TO_END}?api_key=secret", f"{END_TO_END}#fragment"):
        with pytest.raises(ValidationError):
            ProviderRuntimeConfig(service="example", model="example-model",
                                  endpoint=endpoint, region="ap-southeast-1")
    valid = ProviderRuntimeConfig(service="example", model="example-model",
                                  endpoint=END_TO_END, region="ap-southeast-1")
    assert valid.endpoint_host == "api.example-tenant.invalid"
    assert "secret" not in json.dumps(valid.model_dump(mode="json"))


def test_local_packets_record_a_minimised_not_run_runtime(system):
    _db, _audit, _auth, _state, service = system
    packet = asyncio.run(service(GroundedAnswerProvider()).query("employee", QUESTION, NOW))
    record = packet["provider_runtime"]
    assert record["mode"] == "simulated"
    assert record["outcome"] == "not_run"
    assert record["live_request_made"] is False
    for field in ("service", "model", "endpoint_host", "region", "cost_usd", "latency_ms"):
        assert record[field] is None
    assert record["error_category"] is None


def test_runtime_record_for_an_unknown_provider_is_conservative():
    class Bare:
        mode = "unknown_local"

    record = runtime_record_for(Bare()).model_dump(mode="json")
    assert record["mode"] == "simulated" and record["outcome"] == "not_run"
    assert record["provider_mode"] == "unknown_local"
    assert record["model"] is None
