"""Run the corrected synthetic 5E request once with a separate durable ledger."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from aspire_brain.providers.preflight import load_candidate
from aspire_brain.providers.preflight_service import run_service_preflight

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STATE = ROOT / "var/stage5e-corrected-2026-10-10"


def credential():
    value = os.environ.get("GROQ_API_KEY")
    if value:
        return value
    files = list(ROOT.glob("5e test key*"))
    if len(files) != 1:
        raise ValueError("One local, ignored credential file is required")
    values = re.findall(r"\bgsk_[A-Za-z0-9]+\b", files[0].read_text())
    if len(values) != 1:
        raise ValueError("The local file must contain exactly one provider credential")
    return values[0]


def main():
    verification = json.loads((HERE / "corrected-verification.json").read_text())
    if verification.get("checks_passed") is not True:
        raise ValueError("Completed local verification is required")
    for relative, expected in verification["source_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed source snapshot changed; no request sent")
    if not (ROOT / "var/stage5e-2026-10-10/attempt.json").exists():
        raise ValueError("The original attempt provenance is unavailable")
    if (STATE / "attempt.json").exists() or (STATE / "result.json").exists():
        raise ValueError("The corrected single attempt has already been consumed")
    key = credential()
    result = run_service_preflight(load_candidate(HERE / "5e-corrected-candidate.json"),
                                   api_key=key, state_dir=STATE)
    result = result | {"source_sha256": verification["source_sha256"],
                       "source_snapshot_unchanged": all(
                           hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                           for name, digest in verification["source_sha256"].items()),
                       "human_review": "pending_on_this_result",
                       "authorization": "user-requested corrected single attempt; max_cost_usd=0.01",
                       "inference_region": None, "connector_acceptance": "unverified"}
    raw = json.dumps(result, indent=2, ensure_ascii=False)
    if key in raw or re.search(r"\bgsk_[A-Za-z0-9]+\b", raw):
        raise ValueError("Result contains credential-like data; publication blocked")
    with (STATE / "result.json").open("x") as stream:
        stream.write(raw + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({field: result.get(field) for field in (
        "service_status_code", "http_status", "status", "attempt", "live_request_made",
        "postflight_validated", "packet_count", "packet_readable", "error_category",
        "provider_error_type", "provider_error_param", "provider_error_reason",
        "settled_cost_usd", "uncertain_cost_usd")}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("5E corrected request stopped; inspect its ledger. No automatic retry.")
        raise SystemExit(1) from None
