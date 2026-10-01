#!/usr/bin/env python
"""Deterministic local release gate for the Seaglass query paths.

One reproducible local command over the trust boundaries this checkout actually exercises:
input validation, authorised retrieval, freshness, context/provider input, output/citation
release, packet reads, audit, and (separately) ingestion. It runs the red-team playbook, checks
the goal-specific release contract, and writes machine-readable results.

What it is *not*: it is not a general security gate, not an ingestion gate, and not an
unauthorized-action gate. The action-tool path does not exist in this checkout (see
``playbook.v1.json -> not_applicable``), and the ingestion path is covered by a single case.

Usage::

    .venv/bin/python eval/redteam/release_gate.py [--out DIR]

Exit status is the gate: ``0`` only when every hard check passes and the one reviewed
non-critical threshold is not exceeded. ``--out`` defaults to ``artifacts/redteam/``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import socket
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = ROOT / "eval" / "redteam" / "harness.py"
BASELINE_PATH = ROOT / "eval" / "redteam" / "gate-baseline.json"
DDEF_GATE_PATH = ROOT / "eval" / "redteam" / "ddef_gate.py"

#: Boundaries that must each have at least one case. ``ingestion`` is reported separately
#: because it is driven by a different harness function and is a single case, not a gate.
REQUIRED_BOUNDARIES = ("input_validation", "authorized_retrieval", "freshness",
                       "context_provider_input", "output_citation_release", "packet_read", "audit")


def load_harness():
    spec = importlib.util.spec_from_file_location("redteam_harness", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_ddef_gate():
    spec = importlib.util.spec_from_file_location("redteam_ddef_gate", DDEF_GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NetworkGuard:
    """Python IP-socket connect guard, scoped to this interpreter during the gate.

    Records and refuses ``connect``, ``connect_ex`` and ``create_connection`` for IP sockets.
    Unix sockets pass through. This is not process-wide isolation: DNS, UDP sends, native code
    and subprocesses are not comprehensively intercepted. A nonempty list fails the gate;
    an empty list describes only these guarded Python calls.
    """

    def __init__(self):
        self.attempts = []
        self._saved = {}

    def __enter__(self):
        guard = self
        inet = (socket.AF_INET, socket.AF_INET6)

        def wrap_connect(original):
            def wrapper(sock, address, *args, **kwargs):
                if sock.family in inet:
                    guard.attempts.append(f"inet:{address}")
                    raise OSError("outbound network is not permitted inside the release gate")
                return original(sock, address, *args, **kwargs)
            return wrapper

        def create_connection(address, *args, **kwargs):
            guard.attempts.append(f"create_connection:{address}")
            raise OSError("outbound network is not permitted inside the release gate")

        self._saved["connect"] = socket.socket.connect
        self._saved["connect_ex"] = socket.socket.connect_ex
        self._saved["create_connection"] = socket.create_connection
        socket.socket.connect = wrap_connect(socket.socket.connect)
        socket.socket.connect_ex = wrap_connect(socket.socket.connect_ex)
        socket.create_connection = create_connection
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._saved["connect"]
        socket.socket.connect_ex = self._saved["connect_ex"]
        socket.create_connection = self._saved["create_connection"]
        return False


def _redact(text, case):
    """Remove any fixture sentinel or attack marker from text destined for a saved artifact."""
    oracle = case.get("oracle") or {}
    secrets_ = [s for s in oracle.get("forbidden_in_outward", []) if s]
    if oracle.get("attack_marker"):
        secrets_.append(oracle["attack_marker"])
    for secret in secrets_:
        text = text.replace(secret, "[redacted]")
    return text


def failure_packet(row, case):
    """A short, reviewable failure record: case id, fixture hash, path, boundary, failed check.

    Deliberately excludes answer bodies, provider input and any fixture sentinel.
    """
    return {
        "case_id": row["case_id"],
        "fixture_hash": row["fixture_hash"],
        "path": row["path"],
        "boundary": row.get("boundary"),
        "expected_outcome": row["expected_outcome"],
        "observed_outcome": row["observed_outcome"],
        "failed_checks": sorted(name for name, ok in row["checks"].items() if not ok),
        "reason": _redact("; ".join(row.get("reasons") or [])[:400], case),
        "consequences": row.get("consequences", []),
    }


def record_source_hashes():
    """Hash the authored code, dependency declarations and fixtures before/after execution."""
    paths = {HARNESS_PATH, BASELINE_PATH, DDEF_GATE_PATH, ROOT / "eval/redteam/playbook.v1.json",
             ROOT / "eval/redteam/playbook.schema.json", Path(__file__),
             ROOT / "pyproject.toml", ROOT / "requirements.lock"}
    for folder in (ROOT / "src", ROOT / "data/demo"):
        paths.update(path for path in folder.rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix != ".pyc")
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def evaluate():
    source_before = record_source_hashes()
    harness = load_harness()
    ddef_gate = load_ddef_gate()
    playbook, valid, invalid = harness.load_playbook()
    with NetworkGuard() as guard:
        report = harness.run_playbook()
        ddef_report = ddef_gate.run_ddef_gate()
    cases = {case["id"]: case for case in playbook["cases"]}

    covered = {case["boundary"] for case in valid}
    missing_boundaries = sorted(set(REQUIRED_BOUNDARIES) - covered)

    baseline = json.loads(BASELINE_PATH.read_text())
    threshold = baseline["thresholds"]["availability_loss"]
    source_after = record_source_hashes()

    hard_checks = {
        "playbook_gate_passed": report["gate"]["passed"],
        "no_failed_cases": report["failures"] == [],
        "no_critical_consequence": report["critical_failures"] == [],
        "no_benign_false_positive": report["benign"]["false_positives"] == [],
        "no_wrong_benign_answer": report["benign"]["wrong_answers"] == [],
        "availability_objectives_met": report["availability"]["objective_not_met"] == [],
        "boundaries_covered": missing_boundaries == [],
        "no_network_attempt": guard.attempts == [],
        "invalid_case_declared": report["controls"]["unexpected_invalid_cases"] == [],
        "source_snapshot_unchanged": source_before == source_after,
        # D-DEF: the exact-cited-span support rule must retain meaning-affecting characters. A
        # failure of the unrelated RT-004/RT-009 playbook cases alone does not prove this.
        "ddef_claim_support_gate_passed": ddef_report["passed"],
    }
    noncritical = {
        "availability_loss_within_reviewed_baseline": (
            report["consequences"]["availability_loss"]["count"] <= threshold["max"]),
    }

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "playbook_version": report["playbook_version"],
        "boundary_coverage": {
            "required": list(REQUIRED_BOUNDARIES),
            "covered": sorted(covered),
            "missing": missing_boundaries,
            "ingestion_cases": [row["case_id"] for row in report["results"]
                                if row["path"] == "ingestion"],
        },
        "denominators": report["denominators"],
        "observed": report["observed"],
        "consequences": {name: entry["count"]
                         for name, entry in report["consequences"].items()},
        "availability": {"declared": report["availability"]["declared"],
                         "preserved": report["availability"]["preserved"],
                         "degraded": report["availability"]["degraded"],
                         "objective_not_met": report["availability"]["objective_not_met"]},
        "benign": report["benign"],
        "hard_checks": hard_checks,
        "noncritical_threshold": {
            "name": "availability_loss",
            "observed": report["consequences"]["availability_loss"]["count"],
            "max": threshold["max"],
            "numerator": threshold["numerator"],
            "denominator": threshold["denominator"],
            "basis": threshold["basis"],
            "uncertainty": threshold["uncertainty"],
            "within_baseline": noncritical["availability_loss_within_reviewed_baseline"],
        },
        "network_attempts": guard.attempts,
        "ddef_gate": {"unit_ok": ddef_report["unit_ok"],
                      "service_ok": ddef_report["service_ok"],
                      "passed": ddef_report["passed"]},
        "per_case_report_path": "per-case-report.json",
        "failures": [failure_packet(row, cases[row["case_id"]])
                     for row in report["results"] if not row["passed"]],
    }
    result["passed"] = all(hard_checks.values()) and all(noncritical.values())
    result["_per_case_report"] = {
        "playbook_version": report["playbook_version"],
        "schema_version": report["schema_version"],
        "denominators": report["denominators"],
        "gate": report["gate"],
        "source_hashes": source_before,
        "source_hashes_before": source_before,
        "source_hashes_after": source_after,
        "source_snapshot_unchanged": source_before == source_after,
        "network_attempts": guard.attempts,
        "invalid_cases": report["invalid_cases"],
        "results": report["results"],
        "ddef_gate": ddef_report,
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "redteam"))
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    result = evaluate()
    per_case = result.pop("_per_case_report")
    (out / "per-case-report.json").write_text(json.dumps(per_case, indent=2) + "\n")
    (out / "release-gate.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / "failure-packets.json").write_text(
        json.dumps({"playbook_version": result["playbook_version"],
                    "packets": result["failures"]}, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                      ("playbook_version", "boundary_coverage", "denominators", "observed",
                       "consequences", "availability", "benign", "hard_checks",
                       "noncritical_threshold", "network_attempts", "passed")}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
