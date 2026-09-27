"""G4 claim-level support: every asserted claim must be grounded in the cited evidence.

Written before the implementation. The evaluation must go beyond "the citation ID exists":
a sentence the cited evidence does not actually contain fails, an abstention asserts nothing,
and the report always carries a denominator and a simulated/live label.

**Contract note (G5 correction).** Support is *exact quotation* — a claim must be a contiguous
span of one cited source's text — not a 60% token-overlap threshold. The earlier lexical proxy
accepted contradictions such as ``Failover is enabled`` against ``Failover is not enabled``, so
the assertions below were tightened to the exact-span contract. The overlap ratio survives only
as a diagnostic and is never the gate.
"""

import asyncio
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aspire_brain.answers import QueryError
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.evaluation import evaluate_grounding
from aspire_brain.platforms.simulated import (
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)
from aspire_brain.providers import ProviderInput, ProviderOutput
from aspire_brain.providers.claims import evaluate_claim_support, split_claims
from aspire_brain.providers.grounded import GroundedAnswerProvider

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
QUESTION = "What is the status of the database migration project?"
EVIDENCE_TEXT = ("Database migration project status: in progress. "
                 "Blocker: connection pool limit.")
EVIDENCE_ID = "jira:MIGRATE-42:MIGRATE-42:v1"


def source(source_id, text, *, kind="issue", parent="DB", platform="jira"):
    return SimulatedSource(
        platform=platform, tenant_id="demo-a", source_id=source_id, source_kind=kind,
        version_id=f"{source_id}:v1", content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text, locator=f"simulated://{platform}/{source_id}", parent_id=parent,
        source_updated_at=NOW - timedelta(minutes=5),
    )


def build_state(records):
    return SimulatedPlatformState(
        records=records,
        principal_map={"employee": {"jira": "jira-employee"}},
        jira_project_grants={"DB": {"jira-employee"}},
        jira_issue_grants={record.source_id: {"jira-employee"} for record in records
                           if record.source_id == "MIGRATE-42"},
        last_successful_sync={"jira": NOW},
        freshness_budget_seconds={"jira": 3600},
    )


class UnsupportedClaimProvider(GroundedAnswerProvider):
    """Emits a confident sentence the cited evidence does not contain."""

    async def generate(self, context: ProviderInput) -> ProviderOutput:
        return ProviderOutput(
            answer="The migration is fully complete and every blocker has been closed.",
            citation_ids=[item.chunk_id for item in context.evidence])


class SupportedClaimProvider(GroundedAnswerProvider):
    async def generate(self, context: ProviderInput) -> ProviderOutput:
        item = context.evidence[0]
        return ProviderOutput(
            answer="Database migration project status: in progress.",
            citation_ids=[item.chunk_id])


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "g4-claims.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    auth = AuthService(db)

    def service(provider, records):
        return SimulatedQueryService(auth, audit, build_state(records), provider=provider,
                                     required_platforms=("jira",), clock=lambda: NOW)

    return db, audit, auth, service


def test_claim_split_is_deterministic_and_sentence_based():
    assert split_claims("First claim. Second claim!\nThird claim?") == [
        "First claim.", "Second claim!", "Third claim?"]


def test_supported_claims_pass_with_an_explicit_denominator():
    # An exact quotation of the cited source: each sentence is a contiguous span of it.
    report = evaluate_claim_support(
        answer="Database migration project status: in progress. Blocker: connection pool limit.",
        citation_ids=[EVIDENCE_ID],
        evidence={EVIDENCE_ID: EVIDENCE_TEXT},
        provider_mode="fake_grounded", mode="simulated")
    assert report["denominator"] == 2
    assert report["supported_claims"] == 2
    assert report["unsupported_claims"] == 0
    assert report["all_supported"] is True
    assert report["abstained"] is False
    assert report["method"] == "exact_cited_span"
    assert {claim["reason"] for claim in report["claims"]} == {"supported_by_exact_cited_span"}


def test_unsupported_claim_fails_the_evaluation():
    report = evaluate_claim_support(
        answer="The migration is fully complete and every blocker has been closed.",
        citation_ids=[EVIDENCE_ID],
        evidence={EVIDENCE_ID: EVIDENCE_TEXT},
        provider_mode="fake_grounded", mode="simulated")
    assert report["denominator"] == 1
    assert report["unsupported_claims"] == 1
    assert report["all_supported"] is False
    assert report["claims"][0]["reason"] == "no_exact_cited_span"
    assert report["claims"][0]["supporting_ids"] == []
    # The overlap ratio is still reported, but only as a diagnostic; it is not the gate.
    assert report["claims"][0]["support_ratio"] < 1.0


def test_a_claim_with_no_citation_at_all_fails():
    report = evaluate_claim_support(
        answer="The migration is complete.", citation_ids=[],
        evidence={EVIDENCE_ID: EVIDENCE_TEXT},
        provider_mode="fake_grounded", mode="simulated")
    assert report["claims"][0]["supported"] is False
    assert report["claims"][0]["reason"] == "no_cited_evidence"


def test_service_notices_are_excluded_from_the_denominator():
    report = evaluate_claim_support(
        answer="Simulated cross-platform evidence for inspection only. "
               "Blocker: connection pool limit.",
        citation_ids=[EVIDENCE_ID], evidence={EVIDENCE_ID: EVIDENCE_TEXT},
        notices=["Simulated cross-platform evidence for inspection only."],
        provider_mode="offline_extractive", mode="simulated")
    assert report["denominator"] == 1
    assert report["notices_excluded"] == 1
    assert report["all_supported"] is True


def test_abstention_asserts_nothing_and_is_labelled():
    report = evaluate_claim_support(
        answer="Incomplete permitted cross-platform evidence; human review required.",
        citation_ids=[], evidence={}, provider_mode="fake_grounded", mode="simulated",
        abstained=True)
    assert report["abstained"] is True
    assert report["denominator"] == 0
    assert report["all_supported"] is True
    assert report["mode"] == "simulated"
    assert report["live_model_claim_support"] is None


def test_report_is_labelled_simulated_and_never_claims_live():
    report = evaluate_claim_support(
        answer="Database migration project status is in progress.",
        citation_ids=[EVIDENCE_ID], evidence={EVIDENCE_ID: EVIDENCE_TEXT},
        provider_mode="fake_grounded", mode="simulated")
    assert report["mode"] == "simulated"
    assert report["provider_mode"] == "fake_grounded"
    assert report["limitation"]
    assert report["live_model_claim_support"] is None


def test_a_local_provider_cannot_be_labelled_a_live_result():
    with pytest.raises(ValueError):
        evaluate_claim_support(answer="Database migration project status is in progress.",
                               citation_ids=[EVIDENCE_ID], evidence={EVIDENCE_ID: EVIDENCE_TEXT},
                               provider_mode="fake_grounded", mode="live")
    with pytest.raises(ValueError):
        evaluate_claim_support(answer="Any answer.", citation_ids=[], evidence={},
                               provider_mode="offline_extractive", mode="unlabelled")


def test_tokens_spread_across_citations_do_not_support_one_claim():
    report = evaluate_claim_support(
        answer="Migration complete failover.",
        citation_ids=["a", "b", "c"],
        evidence={"a": "migration plan", "b": "complete checklist", "c": "failover guide"},
        provider_mode="fake_grounded", mode="simulated")
    claim = report["claims"][0]
    assert claim["supported"] is False
    assert claim["reason"] == "no_exact_cited_span"
    assert claim["supporting_ids"] == []
    assert report["all_supported"] is False


def test_a_sentence_with_no_checkable_content_fails_closed():
    report = evaluate_claim_support(
        answer="...", citation_ids=[EVIDENCE_ID], evidence={EVIDENCE_ID: EVIDENCE_TEXT},
        provider_mode="fake_grounded", mode="simulated")
    assert report["denominator"] == 1
    assert report["claims"][0]["supported"] is False
    assert report["claims"][0]["reason"] == "no_checkable_tokens"
    assert report["all_supported"] is False


def test_service_releases_a_supported_answer_and_records_its_grounding(system):
    _db, _audit, _auth, service = system
    records = [source("MIGRATE-42", EVIDENCE_TEXT)]
    packet = asyncio.run(service(SupportedClaimProvider(), records).query("employee", QUESTION, NOW))
    assert packet["query_status"] == "answered"
    assert packet["claim_support"]["all_supported"] is True
    assert packet["claim_support"]["denominator"] == 1
    assert packet["claim_support"]["mode"] == "simulated"


def test_service_refuses_an_answer_with_an_unsupported_claim(system):
    _db, _audit, _auth, service = system
    records = [source("MIGRATE-42", EVIDENCE_TEXT)]
    with pytest.raises(QueryError) as failure:
        asyncio.run(service(UnsupportedClaimProvider(), records).query("employee", QUESTION, NOW))
    assert failure.value.status_code == 502


def test_insufficient_permitted_evidence_abstains_without_asserting(system):
    _db, audit, auth, _service = system
    # The record exists in the simulator but the caller holds no grant for it.
    records = [source("MIGRATE-42", EVIDENCE_TEXT)]
    state = build_state(records)
    state.jira_issue_grants = {}
    packet = asyncio.run(
        SimulatedQueryService(auth, audit, state, provider=GroundedAnswerProvider(),
                              required_platforms=("jira",), clock=lambda: NOW)
        .query("employee", QUESTION, NOW))
    assert packet["query_status"] == "abstained"
    assert packet["citations"] == []
    assert packet["claim_support"]["abstained"] is True
    assert packet["claim_support"]["denominator"] == 0
    assert packet["claim_support"]["all_supported"] is True
    assert packet["provider_runtime"]["outcome"] == "not_run"


def test_grounding_evaluation_artifact_has_a_denominator_and_null_live_fields(tmp_path):
    report = evaluate_grounding(tmp_path, secrets.token_bytes(32))
    assert report["stage"] == "G4"
    assert report["mode"] == "simulated"
    assert report["provider_mode"] == "fake_grounded"
    assert report["denominator"]["cases"] >= 3
    assert report["denominator"]["claims_evaluated"] >= 1
    assert report["unsupported_claims"] == 0
    assert report["abstention_cases"] >= 1
    assert report["unsupported_claim_control_detected"] is True
    assert report["live_model_claim_support"] is None
    assert report["live_denominator"] is None
    assert report["provider_runtime"]["outcome"] == "not_run"
    artifact = tmp_path / "artifacts" / "g4-claim-support.json"
    assert artifact.is_file()
    stored = json.loads(artifact.read_text())
    assert stored["denominator"] == report["denominator"]
    assert stored["mode"] == "simulated"
