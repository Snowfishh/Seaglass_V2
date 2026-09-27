"""Release-gate parity for the ``/api/queries`` path (red-team Step 1).

Before this change the main query path validated only that a returned citation id was a
**member** of the released evidence. A provider could therefore cite a genuinely permitted
source and still assert something the source never said, and the forged-but-cited claim was
released and persisted (recorded as RT-009). The simulated path already refuses the same
provider output (RT-004).

These tests require the same source-derived claim-support release contract on both paths:

* a failed claim check returns a safe error,
* saves **no** packet, and
* audits the aborted attempt.

Exact cited spans establish extractive support only. They are not entailment and say nothing
about source truth. The default provider stays ``offline_extractive``.
"""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path

import pytest

from aspire_brain.answers import QueryError, QueryService
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.providers import OfflineExtractiveProvider, ProviderOutput

ROOT = Path(__file__).resolve().parents[2]

#: A claim that is an exact span of no permitted source in the demo corpus.
FORGED_CLAIM = "The travel cap is 9999 SGD per claim."


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, b"rt-claim-support-key-separate-secret-1234")
    audit.initialize()
    return db, AuthService(db), audit


def request(**overrides):
    return QueryRequest.model_validate({
        "question": "What is the Singapore contractor travel cap?",
        "context": {"workflow_id": "general", "case_date": "2026-09-10",
                    "jurisdiction": "SG", "worker_type": "contractor", "currency": "SGD",
                    **overrides},
    })


def run(service, principal, query):
    return asyncio.run(service.query(principal, query))


def packet_rows(db):
    with closing(db.connect()) as connection:
        return connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0]


def aborted_events(audit, tenant="demo-a"):
    return [event for event in audit.events(tenant, limit=200, offset=0)
            if event["event_type"] == "query_aborted"]


# --------------------------------------------------------------------------------------
# The release gate: a forged-but-cited claim must be refused
# --------------------------------------------------------------------------------------

class ForgedCitedProvider(OfflineExtractiveProvider):
    """Cites a genuinely permitted source but asserts something the source never said."""

    async def generate(self, context):
        ids = [item.chunk_id for item in context.evidence][:1]
        return ProviderOutput(answer=FORGED_CLAIM, citation_ids=ids)


def test_forged_but_cited_claim_is_refused(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit, ForgedCitedProvider())
    with pytest.raises(QueryError) as excinfo:
        run(service, auth.principal("employee"), request())
    assert "unsupported claim" in str(excinfo.value).lower()
    # A safe error, no packet, and a visible aborted attempt.
    assert packet_rows(db) == 0
    assert aborted_events(audit), "the aborted attempt must be audited"


def test_unsupported_addition_after_a_valid_quotation_is_refused(system):
    """The provider quotes a permitted span verbatim and then appends an unsupported claim."""
    db, auth, audit = system

    class Addition(OfflineExtractiveProvider):
        async def generate(self, context):
            item = context.evidence[0]
            answer = f"Evidence ({item.source_locator}): {item.text}\n\n{FORGED_CLAIM}"
            return ProviderOutput(answer=answer, citation_ids=[item.chunk_id])

    service = QueryService(db, auth, audit, Addition())
    with pytest.raises(QueryError):
        run(service, auth.principal("employee"), request())
    assert packet_rows(db) == 0


def test_claim_from_a_different_source_than_the_one_cited_is_refused(system):
    """Support is checked against the *cited* source only. Quoting source B while citing
    source A is a wrong pairing and must be refused even though both are permitted."""
    db, auth, audit = system

    class Mispaired(OfflineExtractiveProvider):
        async def generate(self, context):
            items = {item.chunk_id: item for item in context.evidence}
            ids = list(items)
            assert len(ids) >= 2, "fixture needs two permitted sources"
            cited, other = items[ids[0]], items[ids[1]]
            answer = f"Evidence ({cited.source_locator}): {other.text}"
            return ProviderOutput(answer=answer, citation_ids=[cited.chunk_id])

    service = QueryService(db, auth, audit, Mispaired())
    with pytest.raises(QueryError):
        run(service, auth.principal("employee"), request())
    assert packet_rows(db) == 0


def test_citation_that_was_not_released_is_refused(system):
    db, auth, audit = system

    class Invented(OfflineExtractiveProvider):
        async def generate(self, context):
            return ProviderOutput(answer="Unsupported", citation_ids=["invented"])

    service = QueryService(db, auth, audit, Invented())
    with pytest.raises(QueryError):
        run(service, auth.principal("employee"), request())
    assert packet_rows(db) == 0


# --------------------------------------------------------------------------------------
# Valid answers and clear abstentions are preserved
# --------------------------------------------------------------------------------------

def test_valid_answer_is_released_with_a_claim_support_report(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit)  # default offline_extractive
    packet = run(service, auth.principal("employee"), request())
    assert packet["query_status"] == "answered"
    assert packet["claim_support"]["all_supported"] is True
    assert packet["claim_support"]["method"] == "exact_cited_span"
    assert packet["claim_support"]["mode"] == "simulated"
    assert packet["claim_support"]["denominator"] >= 1
    assert packet_rows(db) == 1


def test_absent_evidence_abstains_without_a_claim_failure(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit)
    query = request().model_copy(update={"question": "What is the parental leave entitlement?"})
    packet = run(service, auth.principal("employee"), query)
    assert packet["query_status"] == "insufficient_evidence"
    assert packet["citations"] == []
    assert packet["claim_support"]["abstained"] is True
    assert packet["claim_support"]["all_supported"] is True


# --------------------------------------------------------------------------------------
# Revocation: packet read/export after a contributing source is withdrawn
# --------------------------------------------------------------------------------------

def test_revocation_after_query_denies_the_saved_packet(system):
    db, auth, audit = system
    service = QueryService(db, auth, audit)
    principal = auth.principal("employee")
    packet = run(service, principal, request())
    assert packet_rows(db) == 1
    db.revoke(packet["citations"][0]["document_version_id"], audit)
    with pytest.raises(AccessDenied):
        service.packet(principal, packet["request_id"])
