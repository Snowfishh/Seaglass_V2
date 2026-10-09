"""Build a request envelope; the historical proposal must never be overwritten."""
import hashlib
from pathlib import Path

from aspire_brain.providers.preflight import (
    ANSWER,
    BODY_SHA256,
    CITATION,
    QUESTION,
    SDK_VERSION,
    approved_config,
    approved_rates,
)
from aspire_brain.providers.runtime import reserve_budget
from aspire_brain.providers.target import (
    TargetEvidence,
    TargetInput,
    TargetTemplate,
    build_manifest,
)

HERE = Path(__file__).resolve().parent


def build():
    template = TargetTemplate.consume((HERE / "target-template.json").read_text(),
        expected_fingerprint="56ff8ac945c293404af14a1b8f81f4d1a1c5e184f33720bb20c61c32dbc5b6dc")
    config, rates = approved_config(), approved_rates()
    manifest = build_manifest(TargetInput(QUESTION, (TargetEvidence(CITATION, ANSWER),),
                                        "synthetic-5e-control"), template, config,
                              correlation_id="5e-2026-10-10")
    if manifest.fingerprint_sha256 != BODY_SHA256:
        raise ValueError("Synthetic request differs from the reviewed candidate")
    packet = {
        "stage": "5E fixed synthetic service smoke preflight",
        "status": "prepared_not_run", "actual_external_requests": 0,
        "authorization_basis": "User authorized one request after checks on 2026-10-10",
        "service": config.service, "model": config.model, "https_endpoint": config.endpoint,
        "sdk": {"package": "groq", "pinned_version": SDK_VERSION, "max_retries": 0,
                "httpx_version": "0.28.1", "http_transport_retries": 0,
                "application_retries": 0, "fallbacks": 0, "follow_redirects": False,
                "trust_env": False},
        "runtime_config": config.model_dump(mode="json"),
        "rate_card": rates.model_dump(mode="json"),
        "price_provenance": {
            "url": "https://console.groq.com/docs/model/openai/gpt-oss-20b",
            "verified_date": "2026-10-10", "unit": "USD per million tokens",
            "reasoning_accounting": "completion_tokens includes reasoning; charged once",
        },
        "reservation_usd": str(reserve_budget(config, rates).reservation_usd),
        "template_sha256": template.fingerprint_sha256,
        "manifest_sha256": manifest.fingerprint_sha256,
        "config_sha256": manifest.config_sha256,
        "system_message_sha256": manifest.system_message_sha256,
        "synthetic_question": QUESTION,
        "synthetic_source": {"citation_id": CITATION, "text": ANSWER,
                             "content_sha256": hashlib.sha256(ANSWER.encode()).hexdigest()},
        "exact_candidate_body_json": manifest.body_json,
        "request_body_bytes": len(manifest.body_json.encode()),
        "input_byte_plus_envelope_bound": manifest.input_upper_bound,
        "account_entitlement": "user-provided project permission screenshot; API not yet observed",
        "project_limits": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000,
                           "basis": "2026-10-10 user-provided project Limits screenshot",
                           "available_capacity": None},
        "region": None, "region_provenance": "inference region not verified",
        "data_handling": "Groq inference over this fixed synthetic payload only; no real sources",
        "restart_redispatch": False,
        "supersedes_candidate_sha256": "eefc1f62747028c2909d750e7525924d1247acd2304072823e31c16c7686b9a7",
        "live_result_location": "var/stage5e-2026-10-10/; results are separate from this proposal",
    }
    return packet


if __name__ == "__main__":
    raise SystemExit("Original 5E proposal is frozen; use build_corrected_candidate.py")
