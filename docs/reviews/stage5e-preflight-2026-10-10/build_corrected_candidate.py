"""Build the separate, reviewed 5E correction without changing the first attempt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_candidate import build

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE / "5e-preflight-candidate.json"
CORRECTED = HERE / "5e-corrected-candidate.json"


def corrected_candidate():
    candidate = build()
    return candidate | {
        "stage": "5E corrected single synthetic service request",
        "authorization_basis": "User requested corrected rerun on 2026-10-10",
        "correction": "Remove unsupported uniqueItems and unconfirmed schema constraints; "
                      "retain local ProviderOutput and claim-support validation",
        "original_candidate_sha256": hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
        "live_result_location": "var/stage5e-corrected-2026-10-10/",
        "supersedes_candidate_sha256": hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    CORRECTED.write_text(json.dumps(corrected_candidate(), indent=2,
                                    ensure_ascii=False) + "\n")
    print("Corrected candidate generated; no external request made")
