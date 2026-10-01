"""Offline service boundaries, with synthetic identities and no external transports."""

import asyncio
import hashlib
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from aspire_brain.answers import QueryService
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)
from aspire_brain.providers import (
    ExternalProviderUnavailable,
    OfflineExtractiveProvider,
    ProviderEntitlementError,
    configured_provider,
)
from aspire_brain.providers.grounded import GroundedAnswerProvider
from aspire_brain.providers.runtime import ProviderRuntimeConfig

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
QUESTION = "What is the migration status?"
TEXT = "Migration status: staging validation is pending."
ENDPOINT = "https://provider.invalid/v1/chat/completions"


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "service-5b.db")
    db.initialize()
    with closing(db.connect()) as connection, connection:
        connection.execute("INSERT INTO tenants(id) VALUES ('synthetic')")
        connection.executemany("INSERT INTO principals VALUES (?, 'synthetic', 1, ?)",
                               [("reader", '["employee"]'), ("other", '["employee"]')])
    audit = AuditWriter(db.path, b"synthetic-stage5b-audit-only-not-a-real-key")
    audit.initialize()
    return db, AuthService(db), audit


def request(case_date="2026-09-29"):
    return QueryRequest.model_validate({
        "question": QUESTION,
        "context": {"workflow_id": "general", "case_date": case_date},
    })


def simulated_service(system, provider, *, granted=True):
    _db, auth, audit = system
    source = SimulatedSource(
        platform="jira", tenant_id="synthetic", source_id="TASK-5B", source_kind="issue",
        version_id="TASK-5B:v1", content_sha256=hashlib.sha256(TEXT.encode()).hexdigest(),
        text=TEXT, locator="simulated://jira/TASK-5B", parent_id="SYNTHETIC",
        source_updated_at=NOW - timedelta(minutes=1),
    )
    state = SimulatedPlatformState(
        records=[source], principal_map={"reader": {"jira": "synthetic-reader"}},
        jira_project_grants={"SYNTHETIC": {"synthetic-reader"}},
        jira_issue_grants={"TASK-5B": {"synthetic-reader"}} if granted else {},
        last_successful_sync={"jira": NOW}, freshness_budget_seconds={"jira": 3600},
    )
    return SimulatedQueryService(auth, audit, state, provider=provider,
                                 required_platforms=("jira",), clock=lambda: NOW)


class MustNotGenerate(OfflineExtractiveProvider):
    def __init__(self):
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        raise AssertionError("An empty evidence request must never reach the provider")


@pytest.mark.parametrize("case_date, expected_status", [
    ("2026-09-29", "insufficient_evidence"), (None, "needs_review"),
])
def test_query_empty_evidence_is_service_authored_without_provider_call(
        system, case_date, expected_status):
    db, auth, audit = system
    provider = MustNotGenerate()
    service = QueryService(db, auth, audit, provider)
    packet = asyncio.run(service.query(auth.principal("reader"), request(case_date)))
    assert provider.calls == 0
    assert packet["query_status"] == expected_status
    assert packet["answer"] == (
        "No adequate evidence is available for this question and declared case context."
        " No relevant readable passages were found.")
    assert packet["citations"] == []
    assert packet["claim_support"]["abstained"] is True
    assert packet["claim_support"]["denominator"] == 0
    assert packet["claim_support"]["all_supported"] is True
    assert service.packet(auth.principal("reader"), packet["request_id"]) == packet
    events = audit.events("synthetic", limit=100, offset=0)
    assert [event["event_type"] for event in events].count("query_completed") == 1
    assert not any(event["event_type"] == "provider_error" for event in events)


def test_simulated_empty_permitted_evidence_skips_provider(system):
    provider = MustNotGenerate()
    service = simulated_service(system, provider, granted=False)
    packet = asyncio.run(service.query("reader", QUESTION, NOW))
    assert provider.calls == 0
    assert packet["query_status"] == "abstained"
    assert packet["answer"] == "Incomplete permitted cross-platform evidence; human review required."
    assert packet["citations"] == []
    assert packet["claim_support"]["abstained"] is True
    assert packet["claim_support"]["denominator"] == 0


def test_concurrent_packets_have_request_scoped_runtime_and_never_read_last_callback(system):
    class InterleavedProvider(GroundedAnswerProvider):
        def __init__(self):
            super().__init__()
            self.arrivals = 0
            self.callback_calls = 0
            self.both_arrived = asyncio.Event()

        async def generate(self, context):
            self.arrivals += 1
            if self.arrivals == 2:
                self.both_arrived.set()
            await self.both_arrived.wait()
            return await super().generate(context)

        def runtime_record(self):
            self.callback_calls += 1
            raise AssertionError("Shared last-call runtime records are not request-scoped")

    async def queries():
        provider = InterleavedProvider()
        service = simulated_service(system, provider)
        packets = await asyncio.wait_for(asyncio.gather(
            service.query("reader", QUESTION, NOW),
            service.query("reader", QUESTION, NOW),
        ), timeout=2)
        return service, provider, packets

    service, provider, packets = asyncio.run(queries())
    assert provider.arrivals == 2
    assert provider.callback_calls == 0
    assert len({packet["request_id"] for packet in packets}) == 2
    for packet in packets:
        runtime = packet["provider_runtime"]
        assert runtime["correlation_id"] == packet["request_id"]
        assert runtime["mode"] == "simulated"
        assert runtime["outcome"] == "not_run"
        assert runtime["live_request_made"] is False
        for field in ("service", "model", "endpoint_host", "region", "cost_usd", "latency_ms"):
            assert runtime[field] is None
        assert packet["claim_support"]["all_supported"] is True
        assert service.packet("reader", packet["request_id"]) == packet
    packets[0]["provider_runtime"]["correlation_id"] = "mutated-client-copy"
    assert packets[1]["provider_runtime"]["correlation_id"] == packets[1]["request_id"]
    assert service.packet("reader", packets[0]["request_id"])["provider_runtime"][
        "correlation_id"] == packets[0]["request_id"]


def test_grounded_provider_has_no_shared_runtime_record():
    provider = GroundedAnswerProvider()
    assert "_runtime" not in vars(provider)
    assert not hasattr(provider, "runtime_record")


def test_simulated_packets_remain_owner_and_current_grant_bound(system):
    service = simulated_service(system, GroundedAnswerProvider())
    packet = asyncio.run(service.query("reader", QUESTION, NOW))
    with pytest.raises(AccessDenied):
        service.packet("other", packet["request_id"])
    service.state.set_jira_issue_grant("TASK-5B", "synthetic-reader", False)
    with pytest.raises(AccessDenied):
        service.packet("reader", packet["request_id"])


@pytest.mark.parametrize("enabled, entitlement", [
    (False, "unknown"), (False, "entitled"), (True, "unknown"), (True, "not_entitled"),
])
def test_live_runtime_still_requires_enablement_and_entitlement(enabled, entitlement):
    runtime = ProviderRuntimeConfig(service="synthetic", model="synthetic-model",
                                    endpoint=ENDPOINT, region="synthetic-region",
                                    enabled=enabled, entitlement=entitlement)
    with pytest.raises(ProviderEntitlementError):
        configured_provider("live_grounded", runtime=runtime)


def test_entitled_live_runtime_still_has_no_implemented_transport():
    runtime = ProviderRuntimeConfig(service="synthetic", model="synthetic-model",
                                    endpoint=ENDPOINT, region="synthetic-region",
                                    enabled=True, entitlement="entitled")
    with pytest.raises(ExternalProviderUnavailable):
        configured_provider("live_grounded", runtime=runtime)
    with pytest.raises(ProviderEntitlementError):
        configured_provider("live_grounded")
