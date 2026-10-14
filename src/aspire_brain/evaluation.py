"""Run versioned fixture expectations; never substitute live-answer quality scores."""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from aspire_brain.answers import QueryService
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AuthService
from aspire_brain.db import Database
from aspire_brain.knowledge import Retriever
from aspire_brain.models import QueryRequest

#: Random UUIDs generated per request; they carry no source text but can contain a short
#: forbidden fragment such as "150" by chance, so the forbidden-text check skips them.
_GENERATED_ID_KEYS = ("request_id", "audit_event_id")


def _checks(packet, expected):
    checks = {key: packet[key] == expected[key] for key in ("query_status", "case_outcome")}
    versions = {citation["document_version_id"] for citation in packet["citations"]}
    if "required_version_ids" in expected:
        checks["cited_evidence"] = set(expected["required_version_ids"]) <= versions
    if "cap" in expected:
        caps = [Decimal(rule["value"]) for rule in packet["applied_rules"] if rule["key"] == "travel_cap"]
        checks["cap"] = bool(caps) and all(cap == Decimal(expected["cap"]) for cap in caps)
    if "has_conflicts" in expected:
        checks["conflicts"] = bool(packet["conflicts"]) == expected["has_conflicts"]
    if "missing_evidence_categories" in expected:
        checks["missing"] = set(expected["missing_evidence_categories"]) <= set(packet["missing_evidence_categories"])
    released = json.dumps({key: value for key, value in packet.items() if key not in _GENERATED_ID_KEYS})
    checks["forbidden_text_absent"] = all(
        text not in released for text in expected.get("forbidden_text", [])
    )
    return checks


def evaluate(root: Path, fixtures: Path, cases_path: Path, key: bytes):
    cases = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    results = []
    retrieval_hits = retrieval_total = 0
    with tempfile.TemporaryDirectory(prefix="aspire-evaluation-") as directory:
        db = Database(Path(directory) / "evaluation.db")
        db.initialize()
        audit = AuditWriter(db.path, key)
        audit.initialize()
        db.seed(fixtures / "manifest.json", fixtures / "principals.json", audit=audit)
        auth = AuthService(db)
        service = QueryService(db, auth, audit)
        for case in cases:
            request = QueryRequest.model_validate(case["query"])
            principal = auth.principal(case["principal"])
            packet = asyncio.run(service.query(principal, request))
            checks = _checks(packet, case["expected"])
            context = request.context.model_dump(mode="json")
            scope = {key: context[key] for key in ("jurisdiction", "worker_type", "project", "cost_centre")
                     if context[key] is not None}
            retrieved = Retriever(db).search(principal, request.question, context["case_date"], scope)
            expected_versions = set(case["expected"].get("required_version_ids", []))
            hit = expected_versions <= {row["version_id"] for row in retrieved}
            if expected_versions:
                retrieval_total += 1
                retrieval_hits += int(hit)
            results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks,
                            "query_status": packet["query_status"], "case_outcome": packet["case_outcome"],
                            "lexical_expected_versions_found": hit if expected_versions else None})
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "provider_mode": "offline_extractive",
        "total": len(results), "passed": sum(result["passed"] for result in results),
        "failed": sum(not result["passed"] for result in results), "cases": results,
        "lexical_retrieval": {"all_expected_versions_in_top_5": retrieval_hits,
                              "labelled_cases": retrieval_total},
        "live_answer_quality": "not tested; no live provider or outbound inference",
        "limitations": "Small fictional fixture suite; no universal security or accuracy guarantee.",
    }
    output = root / "artifacts"
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    rows = ["# Offline fixture evaluation", "", f"Passed {report['passed']}/{report['total']}; failed {report['failed']}.",
            "", f"Lexical top-5 found all labelled versions in {retrieval_hits}/{retrieval_total} cases.",
            "Structured policy evaluation additionally uses the full authorised rule catalogue.",
            "Live answer quality: not tested. These results cover the synthetic cases only.", "",
            "| Case | Result |", "|---|---|"]
    rows += [f"| {result['id']} | {'PASS' if result['passed'] else 'FAIL'} |" for result in results]
    (output / "evaluation.md").write_text("\n".join(rows) + "\n")
    return report


#: Evidence used for the unsupported-claim control. It is deliberately the *permitted* source,
#: so the only thing that can fail is the claim's grounding, not the permission check. Only the
#: source text is compared: a locator or document identifier is not evidence for an assertion.
_CONTROL_EVIDENCE_ID = "jira:MIGRATE-42:MIGRATE-42:v1"
_CONTROL_EVIDENCE = ("Database migration project status: in progress. "
                     "Blocker: connection pool limit.")
_CONTROL_ANSWER = "The migration is fully complete and every blocker has been closed."


def _grounding_observation(case_id, packet):
    report = packet["claim_support"]
    return {
        "id": case_id, "query_status": packet["query_status"], "mode": report["mode"],
        "provider_mode": report["provider_mode"], "method": report["method"],
        "denominator": report["denominator"],
        "supported_claims": report["supported_claims"],
        "unsupported_claims": report["unsupported_claims"],
        "abstained": report["abstained"], "all_supported": report["all_supported"],
    }


def evaluate_grounding(root: Path, key: bytes) -> dict:
    """Evaluate claim-level support with a deterministic local provider (G4).

    Support is exact quotation against the cited source text. Every number here is a
    **simulated** measurement over synthetic fixtures. No live model is contacted, so the live
    claim-support fields stay null and the provider runtime is recorded as ``not_run``.
    """
    from aspire_brain.platforms.simulated import SimulatedQueryService
    from aspire_brain.providers.claims import LIMITATION, evaluate_claim_support
    from aspire_brain.providers.grounded import GroundedAnswerProvider
    from aspire_brain.providers.runtime import runtime_record_for
    from aspire_brain.web.cases import (
        CASE_1_QUERY,
        CASE_1_STATE,
        CASE_3_QUERY,
        CASE_3_STATE,
        NOW,
    )

    provider = GroundedAnswerProvider()
    with tempfile.TemporaryDirectory(prefix="aspire-grounding-") as directory:
        db = Database(Path(directory) / "grounding.db")
        db.initialize()
        audit = AuditWriter(db.path, key)
        audit.initialize()
        fixtures = root / "data/demo"
        if not fixtures.is_dir():
            fixtures = Path(__file__).resolve().parents[2] / "data/demo"
        db.seed(fixtures / "manifest.json", fixtures / "principals.json", audit=audit)
        auth = AuthService(db)

        routed = SimulatedQueryService(auth, audit, CASE_1_STATE, provider=provider,
                                       required_platforms=None, clock=lambda: NOW)
        single = SimulatedQueryService(auth, audit, CASE_1_STATE, provider=provider,
                                       required_platforms=("jira",), clock=lambda: NOW)
        restricted = SimulatedQueryService(auth, audit, CASE_3_STATE, provider=provider,
                                           required_platforms=("confluence",),
                                           clock=lambda: NOW)
        observations = [
            ("grounded_cross_platform",
             asyncio.run(routed.query("employee", CASE_1_QUERY, NOW))),
            ("grounded_single_platform",
             asyncio.run(single.query("employee", CASE_1_QUERY, NOW))),
            ("abstention_insufficient_permitted_evidence",
             asyncio.run(restricted.query("employee", CASE_3_QUERY, NOW))),
        ]

    cases = [_grounding_observation(case_id, packet) for case_id, packet in observations]
    control = evaluate_claim_support(
        answer=_CONTROL_ANSWER, citation_ids=[_CONTROL_EVIDENCE_ID],
        evidence={_CONTROL_EVIDENCE_ID: _CONTROL_EVIDENCE},
        provider_mode="fake_grounded", mode="simulated")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "G4", "source": "project requiement.pdf pages 15-19 and 35-38",
        "mode": "simulated", "provider_mode": "fake_grounded", "method": "exact_cited_span",
        "denominator": {"cases": len(cases),
                        "claims_evaluated": sum(case["denominator"] for case in cases)},
        "supported_claims": sum(case["supported_claims"] for case in cases),
        "unsupported_claims": sum(case["unsupported_claims"] for case in cases),
        "abstention_cases": sum(case["abstained"] for case in cases),
        "unsupported_claim_control_detected": bool(control["unsupported_claims"]
                                                   and not control["all_supported"]),
        "unsupported_claim_control": {"denominator": control["denominator"],
                                      "unsupported_claims": control["unsupported_claims"],
                                      "all_supported": control["all_supported"]},
        "cases": cases,
        "provider_runtime": runtime_record_for(provider).model_dump(mode="json"),
        "live_model_claim_support": None, "live_denominator": None,
        "limitation": LIMITATION + (" These results come from a deterministic fake provider "
                                    "over synthetic fixtures, so they are not live-model "
                                    "results and carry no accuracy guarantee."),
    }
    output = root / "artifacts"
    output.mkdir(parents=True, exist_ok=True)
    (output / "g4-claim-support.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
