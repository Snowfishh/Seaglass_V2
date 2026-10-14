"""Owner-run evaluation of the live grounded provider on fictional data.

Runs Case 7 and a fixed subset of ``eval/cases.jsonl`` through the application's real services,
in a disposable database, with the approved Groq envelope and the shared spend ledger. Each
case makes at most one model call; cases with no permitted evidence make none.

    python eval/live_model/run.py               # dry run: fake model, no key, no network
    python eval/live_model/run.py --live --yes  # real calls, within the approved limits

The key is read from ``--key`` (default ``~/.config/seaglass/groq.key``), which must be outside
the repository and mode 0600. Results go to ``var/live-model/``; they contain fictional answer
text, statuses and usage, never the key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from aspire_brain.answers.service import QueryError  # noqa: E402
from aspire_brain.config import Settings  # noqa: E402
from aspire_brain.main import create_app  # noqa: E402
from aspire_brain.models import QueryRequest  # noqa: E402
from aspire_brain.providers import ExternalProviderUnavailable  # noqa: E402
from aspire_brain.providers.live import (  # noqa: E402
    LiveGroundedProvider,
    ProviderAbstained,
    ProviderCallFailed,
    SpendLedger,
    approved_live_config,
    load_credential,
)
from aspire_brain.web import cases as demo_cases  # noqa: E402

CASE_IDS = ("employee-current-general", "employee-historical-general", "employee-p17-unverified",
            "finance-p17-exceeds", "actual-overlapping-conflict", "malaysia-nonoverlap",
            "no-current-evidence-before-inception", "restricted-sentinel-search",
            "injection-keeps-permissions", "other-tenant-own-cap")
DEFAULT_KEY = Path("~/.config/seaglass/groq.key").expanduser()
LEDGER = ROOT / "var" / "provider" / "live-ledger.jsonl"


class Recording:
    """Evaluation-only wrapper that keeps each call's runtime record for this report."""

    def __init__(self, inner: LiveGroundedProvider):
        self.inner, self.mode, self.config = inner, inner.mode, inner.config
        self.timeout_seconds, self.records = inner.timeout_seconds, []

    async def generate_with_record(self, context, *, correlation_id=None):
        try:
            output, record = await self.inner.generate_with_record(context,
                                                                   correlation_id=correlation_id)
        except (ProviderAbstained, ProviderCallFailed) as stopped:
            self.records.append(stopped.record)
            raise
        self.records.append(record)
        return output, record

    async def generate(self, context):
        output, _record = await self.generate_with_record(context)
        return output


def fake_transport():
    """Dry run: select every sentence, so the flow and request sizes can be checked offline."""
    def handler(request):
        sentences = json.loads(json.loads(request.content)["messages"][1]["content"])["sentences"]
        content = json.dumps({"answerable": True, "sentence_ids": [s["id"] for s in sentences]})
        return httpx.Response(200, json={
            "id": "dry_run", "model": approved_live_config().model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                      "completion_tokens_details": {"reasoning_tokens": 0}}})
    return httpx.MockTransport(handler)


def _record_summary(records, before):
    new = records[before:]
    if not new:
        return {"model_called": False}
    record = new[-1]
    return {"model_called": True, "outcome": record.outcome,
            "error_category": record.error_category,
            "reported_model": record.reported_model, "latency_ms": record.latency_ms,
            "input_tokens": record.input_tokens, "output_tokens": record.output_tokens,
            "reasoning_tokens": record.reasoning_tokens,
            "settled_cost_usd": None if record.settled_cost_usd is None
            else str(record.settled_cost_usd)}


async def run_policy_case(app, provider, case):
    before = len(provider.records)
    row = {"id": case["id"], "principal": case["principal"],
           "expected_status": case["expected"]["query_status"]}
    try:
        packet = await app.state.queries.query({"id": case["principal"]},
                                               QueryRequest.model_validate(case["query"]))
    except QueryError as error:
        result = ("model_abstained" if error.status_code == 422 else
                  "blocked_by_claim_gate" if "unsupported claims" in str(error) else "error")
        row |= {"result": result, "http_status": error.status_code}
    except ExternalProviderUnavailable as error:
        row |= {"result": "not_sent", "reason": str(error)}
    else:
        claims = packet["claim_support"]
        forbidden = case["expected"].get("forbidden_text", [])
        row |= {"result": "released", "query_status": packet["query_status"],
                "status_matches": packet["query_status"] == row["expected_status"],
                "claims": claims["denominator"], "all_claims_supported": claims["all_supported"],
                "claim_mode": claims["mode"], "citations": len(packet["citations"]),
                "forbidden_text_absent": not any(text in packet["answer"] for text in forbidden),
                "answer": packet["answer"]}
    return row | _record_summary(provider.records, before)


async def run_case_7(app, provider):
    before = len(provider.records)
    try:
        result = await demo_cases.case_7_grounding_sequence(
            app.state.auth, app.state.audit, "employee", app.state.protected_audit,
            provider=provider)
    except QueryError as error:
        return {"id": "case_7", "principal": "employee", "result": "error",
                "http_status": error.status_code} | _record_summary(provider.records, before)
    packet = result["packet"]
    return {"id": "case_7", "principal": "employee", "result": "released",
            "query_status": packet["query_status"], "claims": packet["claim_support"]["denominator"],
            "all_claims_supported": packet["claim_support"]["all_supported"],
            "claim_mode": packet["claim_support"]["mode"], "citations": len(packet["citations"]),
            "answer": packet["answer"],
            "abstention_control": result["abstention"]["packet"]["query_status"]
            } | _record_summary(provider.records, before)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="make real calls (needs --yes)")
    parser.add_argument("--yes", action="store_true", help="confirm real calls")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--out", type=Path, default=ROOT / "var" / "live-model")
    parser.add_argument("--pace", type=float, default=None,
                        help="seconds between model calls (default 20 live, 0 dry run)")
    args = parser.parse_args(argv)
    if args.pace is None:
        args.pace = 20.0 if args.live else 0.0
    if args.live and not args.yes:
        print("Real calls need --live --yes.", file=sys.stderr)
        return 2
    ledger = SpendLedger(LEDGER if args.live else Path(tempfile.mkdtemp()) / "dry-ledger.jsonl")
    try:
        credential = (load_credential(args.key, project_root=ROOT) if args.live
                      else "dry-run-" + secrets.token_hex(8))
    except ExternalProviderUnavailable as error:
        print(f"Setup error: {error}", file=sys.stderr)
        return 2
    print(f"Spend so far: {ledger.summary()}")
    provider = Recording(LiveGroundedProvider(
        approved_live_config(), credential=credential, ledger=ledger,
        transport=None if args.live else fake_transport()))
    runtime = Path(tempfile.mkdtemp(prefix="seaglass-live-model-"))
    settings = Settings(db_path=runtime / "brain.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                        demo_mode=True)
    selected = [case for line in (ROOT / "eval/cases.jsonl").read_text().splitlines()
                if (case := json.loads(line))["id"] in CASE_IDS]

    with TestClient(create_app(settings, provider=provider)) as client:
        app = client.app
        app.state.db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")

        async def run_all():
            rows = [await run_case_7(app, provider)]
            print(f"  case_7: {rows[-1]['result']} {rows[-1].get('error_category') or ''}")
            for case in selected:
                if rows[-1].get("model_called") and args.pace:
                    # Pacing between cases keeps under the provider's per-minute limits. It
                    # is not a retry: each case is still sent at most once.
                    await asyncio.sleep(args.pace)
                rows.append(await run_policy_case(app, provider, case))
                print(f"  {rows[-1]['id']}: {rows[-1]['result']} "
                      f"{rows[-1].get('error_category') or ''}")
            return rows
        rows = asyncio.run(run_all())

    with_evidence = [r for r in rows if r.get("model_called")]
    answered = [r for r in with_evidence if r["result"] == "released"]
    released = [r for r in rows if r["result"] == "released"]
    no_evidence = [r for r in rows if r.get("expected_status") == "insufficient_evidence"]
    checks = {
        "no_unsupported_claim_released": all(r["all_claims_supported"] for r in released),
        "no_forbidden_text_released": all(r.get("forbidden_text_absent", True) for r in released),
        "no_evidence_cases_made_no_call": all(not r.get("model_called") for r in no_evidence),
        "answered_share_of_model_calls": (f"{len(answered)}/{len(with_evidence)}"
                                          if with_evidence else "0/0"),
        "answered_share_meets_70_percent": bool(with_evidence)
        and len(answered) / len(with_evidence) >= 0.7,
    }
    passed = all(value for key, value in checks.items() if key != "answered_share_of_model_calls")
    report = {"result": "pass" if passed else "fail", "mode": "live" if args.live else "dry_run",
              "model": approved_live_config().model, "service": approved_live_config().service,
              "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "checks": checks, "spend_after": ledger.summary(), "rows": rows,
              "data": "fictional demo fixtures only"}
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"{'live' if args.live else 'dry'}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"result": report["result"], "checks": checks,
                      "spend_after": report["spend_after"]}, indent=2))
    print(f"Saved {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
