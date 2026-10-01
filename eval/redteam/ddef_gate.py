#!/usr/bin/env python
"""Deterministic D-DEF regression gate for the ``exact_cited_span`` support rule.

D-DEF is the claim-support release-gate defect: ``claims.py`` tokenised with ``[a-z0-9]+``, so a
sign, a currency symbol, a unit, a percent sign and every non-ASCII character were discarded
before the contiguous-span comparison. ``SGD 250`` accepted as ``SGD -250`` and an inserted
``无需审批`` were released and persisted.

This gate is the *required* deterministic regression check for the repair. It runs a fixed vector
set at two levels and exits ``0`` only when the release decision matches the declared ground
truth everywhere:

* **unit** — :func:`aspire_brain.providers.claims.evaluate_claim_support` over each vector, and
* **service** — the real ASGI ``POST /api/queries`` and ``GET /api/packets`` routes, including
  release, exact audit events, packet persistence, packet reads and audit-chain verification.

It is offline and deterministic: no network, no credential, no new dependency, and the fake
provider is in-process. A non-zero exit means a declared support/release contract failed.

Usage::

    .venv/bin/python eval/redteam/ddef_gate.py [--out DIR]

``--out`` writes ``ddef-gate.json`` next to the other gate artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: Import this checkout's own ``src`` rather than any installed copy of the package.
sys.path.insert(0, str(ROOT / "src"))

#: Cited source used by the reproduced vectors (two sentences).
CAP_SOURCE = (
    "Singapore contractor travel cap: SGD 250 per claim from 1 September 2026. "
    "This approved version explicitly supersedes v1 for its effective dates."
)
#: Source carrying a currency code, a percentage and a unit.
RULE_SOURCE = (
    "Fictional claim rule: the cap is SGD 250 per claim, a 50% advance is permitted, "
    "and the luggage limit is 30 kg."
)
#: Source whose exact text contains non-ASCII characters.
UNICODE_SOURCE = "Fictional rule: \u65e0\u9700\u5ba1\u6279 is required for amounts below SGD 250."

# (case id, source, asserted text, is_exact_quotation)
UNIT_VECTORS = [
    ("control_exact_quote", CAP_SOURCE, CAP_SOURCE, True),
    ("control_exact_unicode_quote", UNICODE_SOURCE, UNICODE_SOURCE, True),
    ("v1_sign_loss", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD -250"), False),
    ("v2_zero_token_addition", CAP_SOURCE,
     CAP_SOURCE.replace("2026.", "2026 \u65e0\u9700\u5ba1\u6279."), False),
    ("sign_ascii_plus", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD +250"), False),
    ("sign_unicode_minus", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u2212250"), False),
    ("sign_unicode_en_dash", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u2013250"), False),
    ("sign_unicode_plus_minus", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u00b1250"), False),
    ("currency_dollar_symbol", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD $250"), False),
    ("currency_yen_symbol", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u00a5250"), False),
    ("currency_euro_symbol", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u20ac250"), False),
    ("percent_sign_dropped", RULE_SOURCE, RULE_SOURCE.replace("50% advance", "50 advance"), False),
    ("unit_dropped", RULE_SOURCE, RULE_SOURCE.replace("30 kg", "30"), False),
    ("unit_nonascii_ligature", RULE_SOURCE, RULE_SOURCE.replace("30 kg", "30\u338f"), False),
    ("nonascii_fullwidth_digits", CAP_SOURCE,
     CAP_SOURCE.replace("SGD 250", "SGD \uff12\uff15\uff10"), False),
    ("nonascii_fullwidth_punct", CAP_SOURCE, CAP_SOURCE.replace("cap:", "cap\uff1a"), False),
    ("nonascii_cjk_substitution", UNICODE_SOURCE,
     UNICODE_SOURCE.replace("\u65e0\u9700\u5ba1\u6279", "\u9700\u5ba1\u6279"), False),
    ("control_numeric_change", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD 900"), False),
    ("control_negation", CAP_SOURCE,
     CAP_SOURCE.replace("explicitly supersedes", "does not supersede"), False),
    ("control_entity_swap", CAP_SOURCE,
     CAP_SOURCE.replace("Singapore contractor", "Alice approved Bob"), False),
    ("numeric_prefix", "2500", "250", False),
    ("numeric_suffix", CAP_SOURCE, "50" + CAP_SOURCE.split("SGD 250", 1)[1], False),
    ("numeric_subtoken", "250", "50", False),
    ("numeric_decimal", "250.75", "250", False),
    ("numeric_comma", "250,000", "250", False),
    ("sign_boundary", "-250.", "250.", False),
    ("currency_boundary", "SGD 250.", "250.", False),
    ("percent_boundary", "50%", "50", False),
    ("unit_boundary", "30 kg", "30", False),
    ("unicode_boundary", "无需审批.", "需审批.", False),
    ("combining_boundary", "cafe\u0301", "cafe", False),
    ("newline_sign_boundary", "-\n250", "250", False),
    ("newline_currency_boundary", "SGD\n250", "250", False),
    ("newline_unit_boundary", "30\nkg", "30", False),
    ("control_line_wrapped_quote", "Cap is 250 SGD.", "Cap is\n250 SGD.", True),
    ("control_exact_numeric", "250.", "250.", True),
    ("control_exact_signed", "-250.", "-250.", True),
    ("control_exact_currency", "$250.", "$250.", True),
    ("control_exact_percent", "50%.", "50%.", True),
    ("control_exact_unit", "30 kg.", "30 kg.", True),
    ("control_exact_unicode", "无需审批.", "无需审批.", True),
]

#: Service-level mutations applied to the quoted evidence blocks only (never the notice).
SERVICE_VECTORS = {
    "v1_sign_loss": lambda body: body.replace("SGD 250", "SGD -250"),
    "v2_zero_token_addition": lambda body: body.replace("2026.", "2026 \u65e0\u9700\u5ba1\u6279."),
    "v3_currency_symbol": lambda body: body.replace("SGD 250", "SGD $250"),
    "v4_unicode_sign": lambda body: body.replace("SGD 250", "SGD \u2212250"),
    "numeric_suffix": lambda body: "50" + body.split("SGD 250", 1)[1],
    "notice_only": lambda body: "",
    "control_unchanged": lambda body: body,
}

_CID = "sg-travel-v2:p2"
FORBIDDEN_OUTWARD = frozenset({"answer", "claim", "claims", "claim_support", "packet",
                              "packets", "citations", "citation_ids", "request_id"})


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _source_hashes():
    paths = [Path(__file__).resolve(), ROOT / "src/aspire_brain/providers/claims.py",
             ROOT / "src/aspire_brain/answers/service.py", ROOT / "src/aspire_brain/main.py",
             ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json"]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def _unit_report():
    from aspire_brain.providers.claims import evaluate_claim_support

    rows = []
    for case_id, source, claim, is_exact in UNIT_VECTORS:
        report = evaluate_claim_support(
            answer=claim, citation_ids=[_CID], evidence={_CID: source},
            provider_mode="offline_extractive", mode="simulated", abstained=False)
        accepted = report["all_supported"]
        rows.append({
            "case_id": case_id,
            "fixture_hash": _hash({"source": source, "claim": claim, "is_exact": is_exact}),
            "expected": {"all_supported": is_exact, "nonzero_denominator": True},
            "observed": {"all_supported": accepted, "denominator": report["denominator"],
                         "unsupported_claims": report["unsupported_claims"]},
            "checks": {"exact_release_decision": accepted is is_exact,
                       "nonzero_denominator": report["denominator"] > 0},
            "is_exact_quotation": is_exact,
            "gate_all_supported": accepted,
            "ok": accepted is is_exact and report["denominator"] > 0,
            "reason": [c["reason"] for c in report["claims"]],
        })
    return rows


def _case_checks(is_control, outcome):
    """Require the declared reason and observable side effects, not merely any error."""
    checks = {
        "provider_called": outcome["provider_called"] is True,
        "one_query_attempt": outcome["query_attempt_count"] == 1,
        "audited_request_id": bool(outcome["request_id_from_audit"]),
        "read_targets_audited_request": (
            outcome["read_request_id"] == outcome["request_id_from_audit"]
            and bool(outcome["read_request_id"])),
        "valid_audit_chain": outcome["chain_valid"] is True,
        "no_query_failed": outcome["query_failed_count"] == 0,
    }
    if is_control:
        return {**checks, "status_200": outcome["status_code"] == 200,
                "released": outcome["released"] is True,
                "all_supported": outcome["all_supported"] is True,
                "nonzero_support_denominator": outcome["support_denominator"] > 0,
                "zero_unsupported_claims": outcome["unsupported_claims"] == 0,
                "no_provider_error": outcome["provider_error_count"] == 0,
                "no_query_aborted": outcome["query_aborted_count"] == 0,
                "one_query_completed": outcome["query_completed_count"] == 1,
                "one_persisted_packet": outcome["packet_count"] == 1,
                "owner_read_200": outcome["packet_read_status"] == 200,
                "exact_answer_equality": outcome["exact_answer_equal"] is True}
    return {**checks, "status_502": outcome["status_code"] == 502,
            "not_released": outcome["released"] is False,
            "one_provider_error": outcome["provider_error_count"] == 1,
            "exactly_unsupported_claim": outcome["unsupported_claim_error_count"] == 1,
            "one_query_aborted": outcome["query_aborted_count"] == 1,
            "no_query_completed": outcome["query_completed_count"] == 0,
            "zero_persisted_packets": outcome["packet_count"] == 0,
            "owner_read_denied": outcome["packet_read_status"] == 404,
            "no_outward_answer_claim_packet": not FORBIDDEN_OUTWARD.intersection(
                outcome["outward_fields"]),
            "no_read_answer_claim_packet": not FORBIDDEN_OUTWARD.intersection(
                outcome["read_outward_fields"])}


def _fields(value):
    """Collect JSON field names at every depth so nesting cannot conceal released data."""
    if isinstance(value, dict):
        return set(value).union(*(_fields(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_fields(item) for item in value))
    return set()


def _run_http(case_id, mutate):
    from fastapi.testclient import TestClient

    from aspire_brain.config import Settings
    from aspire_brain.main import create_app
    from aspire_brain.providers import OfflineExtractiveProvider, ProviderOutput

    class Mutating(OfflineExtractiveProvider):
        called = False
        answer = None
        evidence_hash = None

        async def generate(self, context):
            self.called = True
            self.evidence_hash = _hash({item.chunk_id: item.text for item in context.evidence})
            if case_id == "notice_only":
                self.answer = context.decision_summary
                return ProviderOutput(answer=self.answer, citation_ids=[context.evidence[0].chunk_id])
            if case_id == "numeric_suffix":
                item = next(item for item in context.evidence if item.chunk_id == _CID)
                self.answer = mutate(item.text)
                return ProviderOutput(answer=self.answer, citation_ids=[item.chunk_id])
            base = await super().generate(context)
            head, separator, body = base.answer.partition("\n\n")
            self.answer = head + separator + mutate(body) if separator else mutate(base.answer)
            return ProviderOutput(answer=self.answer, citation_ids=base.citation_ids)

    with tempfile.TemporaryDirectory(prefix="ddef-http-gate-") as tmp:
        provider = Mutating()
        settings = Settings(db_path=Path(tmp) / "gate.db", session_secret="ddef-local-session",
                            audit_key=b"ddef-gate-key-separate-secret-1234", demo_mode=True)
        with TestClient(create_app(settings, provider=provider), base_url="http://localhost",
                        client=("127.0.0.1", 50000)) as client:
            client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                     ROOT / "data/demo/principals.json")

            def headers():
                return {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"],
                        "Origin": "http://localhost"}

            client.post("/api/demo/session", json={"user_id": "employee"}, headers=headers())
            response = client.post("/api/queries", headers=headers(), json={
                "question": "What is the general travel cap?",
                "context": {"workflow_id": "general", "case_date": "2026-09-10",
                            "jurisdiction": "SG", "worker_type": "contractor",
                            "currency": "SGD"}})
            body = response.json()
            audit = client.app.state.audit
            events = audit.events("demo-a", limit=1000)
            attempts = [event for event in events if event["event_type"] == "query_attempt"]
            request_id = attempts[0]["request_id"] if len(attempts) == 1 else None
            scoped = [event for event in events if event["request_id"] == request_id]
            errors = [event for event in scoped if event["event_type"] == "provider_error"]
            read = client.get(f"/api/packets/{request_id}") if request_id else None
            with closing(client.app.state.db.connect()) as connection:
                packets = connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            support = body.get("claim_support") or {}
            return {
                "status_code": response.status_code, "released": response.status_code == 200,
                "support_denominator": support.get("denominator", 0),
                "all_supported": support.get("all_supported"),
                "unsupported_claims": support.get("unsupported_claims"),
                "query_attempt_count": len(attempts), "provider_error_count": len(errors),
                "unsupported_claim_error_count": sum(
                    event["metadata"].get("error_code") == "unsupported_claim" for event in errors),
                "query_aborted_count": sum(event["event_type"] == "query_aborted"
                                           for event in scoped),
                "query_completed_count": sum(event["event_type"] == "query_completed"
                                             for event in scoped),
                "query_failed_count": sum(event["event_type"] == "query_failed"
                                          for event in scoped),
                "request_id_from_audit": request_id, "read_request_id": request_id,
                "packet_count": packets, "packet_read_status": read.status_code if read else None,
                "outward_fields": sorted(_fields(body)),
                "read_outward_fields": sorted(_fields(read.json())) if read else [],
                "chain_valid": audit.verify("demo-a")["chain_valid"],
                "exact_answer_equal": bool(response.status_code == 200 and read is not None
                                           and read.status_code == 200
                                           and body.get("answer") == provider.answer
                                           and read.json().get("answer") == provider.answer),
                "provider_called": provider.called, "evidence_hash": provider.evidence_hash,
                "provider_answer_hash": _hash(provider.answer),
            }


def _service_report():
    rows = []
    for case_id, mutate in SERVICE_VECTORS.items():
        outcome = _run_http(case_id, mutate)
        is_control = case_id == "control_unchanged"
        checks = _case_checks(is_control, outcome)
        expected = {"status_code": 200 if is_control else 502,
                    "provider_error_count": 0 if is_control else 1,
                    "unsupported_claim_error_count": 0 if is_control else 1,
                    "query_aborted_count": 0 if is_control else 1,
                    "packet_count": 1 if is_control else 0,
                    "packet_read_status": 200 if is_control else 404,
                    "read_target": "same request_id as query_attempt audit event",
                    "chain_valid": True, "nonzero_support_denominator": is_control,
                    "exact_answer_equal": is_control}
        rows.append({"case_id": case_id, "path": "ASGI /api/queries + /api/packets",
                     "fixture_hash": _hash({"source": CAP_SOURCE, "mutation": mutate(CAP_SOURCE),
                                            "expected": expected}),
                     "expected": expected, "observed": outcome, "checks": checks,
                     "expected_released": is_control, "released": outcome["released"],
                     "status_code": outcome["status_code"], "ok": all(checks.values())})
    return rows


def run_ddef_gate():
    source_before = _source_hashes()
    unit = _unit_report()
    service = _service_report()
    source_after = _source_hashes()
    unit_ok = all(row["ok"] for row in unit)
    service_ok = all(row["ok"] for row in service)
    return {
        "gate": "D-DEF exact_cited_span support",
        "unit_vectors": unit,
        "service_vectors": service,
        "unit_ok": unit_ok,
        "service_ok": service_ok,
        "source_hashes": source_before,
        "source_hashes_after": source_after,
        "source_snapshot_unchanged": source_before == source_after,
        "passed": unit_ok and service_ok and source_before == source_after,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    report = run_ddef_gate()
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "ddef-gate.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in
                      ("gate", "unit_ok", "service_ok", "passed")}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
