"""Real application services over fictional files; never a live-provider test."""

import asyncio
import json
import secrets
import socket
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aspire_brain.answers.service import QueryError
from aspire_brain.audit import AuditWriter, ProtectedAuditStore
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.connectors.offline import load_fixture_index
from aspire_brain.platforms.routing import ContextBudget
from aspire_brain.platforms.simulated import SimulatedQueryService
from aspire_brain.platforms.sync import Synchronizer
from aspire_brain.providers import OfflineExtractiveProvider, ProviderOutput

ROOT = Path(__file__).resolve().parents[2] / "data/fixtures/fintech_operations"
NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
ORACLE = {r["id"]: r for r in json.loads((ROOT / "expected-outcomes.json").read_text())["assertions"]}


class RecordingProvider(OfflineExtractiveProvider):
    def __init__(self):
        self.contexts = []

    async def generate(self, context):
        self.contexts.append(context)
        return await super().generate(context)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline fixture workflow attempted network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "fintech.db")
    db.initialize()
    with closing(db.connect()) as connection, connection:
        connection.execute("INSERT INTO tenants(id) VALUES (?)", ("fintech-demo",))
        for person, role in (("user-a", "staff"), ("user-b", "staff"), ("officer", "audit")):
            connection.execute("INSERT INTO principals VALUES (?,?,?,?)",
                               (person, "fintech-demo", 1, json.dumps([role])))
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    auth = AuthService(db)
    protected = ProtectedAuditStore(db.path, secrets.token_bytes(32), audit, auth)
    protected.initialize()
    index = load_fixture_index(ROOT, now=NOW)
    provider = RecordingProvider()
    service = SimulatedQueryService(
        auth, audit, index, provider=provider, protected_audit=protected,
        required_platforms=("confluence", "jira", "slack", "drive"),
        budget=ContextBudget(max_items=20, max_chars=30000), clock=lambda: NOW,
    )
    return service, index, provider, protected, audit, db


def query(service, case):
    return asyncio.run(service.query(case["principal"], case["question"], NOW))


def test_ordinary_cross_platform_evidence_and_no_hidden_metadata(system):
    service, _, provider, _, _, _ = system
    case = ORACLE["cross_platform_status"]
    packet = query(service, case)
    assert packet["query_status"] == "answered"
    assert {c["platform"] for c in packet["citations"]} == {"confluence", "jira", "slack", "drive"}
    assert set(case["required_source_ids"]) <= {c["source_id"] for c in packet["citations"]}
    assert case["expected_facts"]["jira_status"] in packet["answer"]
    serialized = json.dumps(packet) + provider.contexts[-1].model_dump_json()
    for token in ORACLE["denied_case"]["forbidden_disclosures"]:
        assert token not in serialized
    for source_id in ORACLE["denied_case"]["denied_source_ids"]:
        assert source_id not in serialized
    assert packet["claim_support"]["all_supported"] is True


def test_handover_fact_and_runbook_revision_require_synchronization(system):
    service, index, provider, _, _, _ = system
    service.required_platforms = ("confluence",)
    packet = query(service, ORACLE["morning_queue"])
    assert "three require manual review" in packet["answer"]
    assert ORACLE["morning_queue"]["expected_facts"]["manual_review"] == 3
    case = ORACLE["runbook_update"]
    initial = asyncio.run(service.query("user-b", "processing escalation runbook", NOW))
    assert f"more than {case['before']['escalation_minutes']} minutes" in initial["answer"]
    changed = load_fixture_index(ROOT, now=NOW, updates=True).records[("confluence", case["source_id"])]
    index.upstream["confluence"].upsert(changed, at=changed.source_updated_at)
    assert index.records[("confluence", case["source_id"])].version_id == case["before"]["version_id"]
    pending = asyncio.run(service.query("user-b", "processing escalation runbook", NOW))
    assert pending["query_status"] == "abstained"
    Synchronizer(index).sync("confluence", NOW)
    after = asyncio.run(service.query("user-b", "processing escalation runbook", NOW))
    assert f"more than {case['after']['escalation_minutes']} minutes" in after["answer"]
    assert "more than 30 minutes" not in after["answer"]
    assert "partner transaction reference before" in after["answer"]
    assert all(e.version_id != "1.0" for e in provider.contexts[-1].evidence)


def test_authorized_case_distinguishes_payment_from_loss_and_fraud(system):
    service, _, provider, _, _, _ = system
    service.required_platforms = ("confluence", "drive")
    packet = query(service, ORACLE["allowed_case"])
    assert set(ORACLE["allowed_case"]["required_source_ids"]) <= {c["source_id"] for c in packet["citations"]}
    assert "not a confirmed financial loss" in packet["answer"]
    assert "does not establish fraud or account compromise" in packet["answer"]
    assert ORACLE["amount_not_loss"]["expected_facts"]["confirmed_loss"] is None
    assert ORACLE["fraud_not_established"]["expected_facts"]["fraud_established"] is False
    assert any("USD 12,480.00" in e.text for e in provider.contexts[-1].evidence)


@pytest.mark.parametrize("case_id", ["amount_not_loss", "fraud_not_established"])
def test_actual_financial_questions_return_qualified_source_evidence(system, case_id):
    service, _, _, _, _, _ = system
    service.required_platforms = ("confluence", "drive")
    packet = query(service, ORACLE[case_id])
    assert packet["query_status"] == "answered"
    assert "not a confirmed financial loss" in packet["answer"]
    assert "does not establish fraud or account compromise" in packet["answer"]
    assert "USD 12,480.00" in packet["answer"]
    assert "conf-restricted-case" in {c["source_id"] for c in packet["citations"]}


@pytest.mark.parametrize("case_id", ["denied_case", "unsupported_budget"])
def test_actual_unanswerable_questions_abstain_without_private_disclosures(system, case_id):
    service, _, provider, _, _, _ = system
    packet = query(service, ORACLE[case_id])
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert provider.contexts == []
    assert service.packet("user-b", packet["request_id"])["answer"] == packet["answer"]
    for token in ORACLE["denied_case"]["forbidden_disclosures"]:
        assert token not in json.dumps(packet)


@pytest.mark.parametrize("fabrication", [
    "Cedar Quay lost USD 12,480.00.", "The beneficiary change was confirmed fraud.",
    "The approved callback repair budget is USD 50,000.",
])
def test_unsupported_financial_conclusions_refused_without_packet(system, fabrication):
    service, _, _, _, _, db = system

    class FabricatingProvider(OfflineExtractiveProvider):
        async def generate(self, context):
            return ProviderOutput(answer=fabrication, citation_ids=[e.chunk_id for e in context.evidence])

    service.provider = FabricatingProvider()
    service.required_platforms = ("confluence", "drive")
    with pytest.raises(QueryError, match="unsupported claims"):
        query(service, ORACLE["allowed_case"])
    with closing(db.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM simulated_packets").fetchone()[0] == 0


def test_case_revocation_blocks_new_retrieval_and_saved_packet(system):
    service, index, _, _, _, _ = system
    service.required_platforms = ("confluence", "drive")
    packet = query(service, ORACLE["allowed_case"])
    for source_id in ORACLE["case_revocation"]["revoke_source_ids"]:
        platform = "confluence" if source_id.startswith("conf-") else "drive"
        field = "confluence_page_grants" if platform == "confluence" else "drive_file_grants"
        index.upstream[platform].set_grant(field, source_id, "user-a", False, at=NOW)
        Synchronizer(index).sync(platform, NOW)
    with pytest.raises(AccessDenied):
        service.packet("user-a", packet["request_id"])
    after = query(service, ORACLE["allowed_case"])
    assert after["query_status"] == "abstained"
    assert after["citations"] == []
    for token in ORACLE["denied_case"]["forbidden_disclosures"]:
        assert token not in json.dumps(after)


def test_no_matching_evidence_abstains_without_provider(system):
    service, _, provider, _, _, _ = system
    packet = asyncio.run(service.query("user-b", "xylophonic zeppelin", NOW))
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert provider.contexts == []


def test_officer_reconstructs_query_and_denial_without_ordinary_access(system):
    service, _, _, protected, audit, _ = system
    case = ORACLE["cross_platform_status"]
    since = datetime.now(UTC)
    packet = query(service, case)
    args = dict(subject_id="user-b", platform="confluence", parent_id="conf-demo-space",
                since=since, until=datetime.now(UTC))
    with pytest.raises(AccessDenied):
        protected.inquire("user-b", **args)
    reconstruction = protected.inquire("officer", **args)
    assert len(reconstruction["entries"]) == 1
    entry = reconstruction["entries"][0]
    assert entry["question"] == case["question"]
    assert entry["answer"] == packet["answer"]
    assert entry["audit_event_id"] == packet["audit_event_id"]
    assert any(d["source_id"] == "conf-restricted-case" and not d["allowed"] for d in entry["decisions"])
    assert audit.verify("fintech-demo")["chain_valid"] is True
