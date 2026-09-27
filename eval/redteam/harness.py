"""Deterministic red-team seed harness for the Seaglass local query paths.

Design constraints (deliberate, see eval/redteam/README.md):

* **Deterministic Python assertions only.** No model judge, no network, no numeric threshold
  imported from any article. Every case is a plain assertion over synthetic fixtures.
* **Schema-validated playbook.** A case that does not validate is reported as ``invalid`` and
  stays in the denominator; it is never silently dropped.
* **Isolated state per case.** Each case builds its own database and its own simulated platform
  state, so no case can observe another's grants.
* **Both paths are modelled.** ``simulated_case`` drives ``SimulatedQueryService``;
  ``api_queries`` drives ``QueryService`` behind ``POST /api/queries``.
* **All outward fields are inspected**, not just the answer: answer, citations, packet metadata,
  the whole packet, and the audit response.

The module is deliberately dependency-free (a small JSON-Schema subset validator) so it can run
from a bare checkout. It is loaded by path from the tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from aspire_brain.answers import QueryService  # noqa: E402
from aspire_brain.audit import AuditWriter  # noqa: E402
from aspire_brain.auth import AccessDenied, AuthService  # noqa: E402
from aspire_brain.db import Database  # noqa: E402
from aspire_brain.models import QueryRequest  # noqa: E402
from aspire_brain.platforms.routing import TimeWindow  # noqa: E402
from aspire_brain.platforms.simulated import (  # noqa: E402
    ALL_PLATFORMS,
    SimulatedPlatformState,
    SimulatedQueryService,
    SimulatedSource,
)
from aspire_brain.providers import (  # noqa: E402
    OfflineExtractiveProvider,
    ProviderOutput,
)

NOW = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
PLAYBOOK = ROOT / "eval" / "redteam" / "playbook.v1.json"
SCHEMA = ROOT / "eval" / "redteam" / "playbook.schema.json"
FORGED_CLAIM = "The database migration is fully complete and every blocker has been closed."

#: The outcome vocabulary. Ordered from least to most severe.
OUTCOMES = ("attack_not_retrieved", "attack_retrieved_but_blocked", "attack_succeeded", "inconclusive")


# =====================================================================================
# Minimal JSON-Schema (2020-12 subset) validator — no third-party dependency.
# =====================================================================================

def _type_ok(value, name):
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(name, True)


def validate(instance, schema, root=None, path="$"):
    """Return a list of human-readable validation errors (empty means valid)."""
    root = root if root is not None else schema
    errors = []

    if "$ref" in schema:
        target = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return validate(instance, target, root, path)

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")

    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(instance, name) for name in names):
            errors.append(f"{path}: expected type {names}, got {type(instance).__name__}")
            return errors

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: does not match pattern {schema['pattern']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors += validate(item, schema["items"], root, f"{path}[{index}]")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors += validate(value, properties[key], root, f"{path}.{key}")
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: unexpected property {key!r}")
                elif isinstance(extra, dict):
                    errors += validate(value, extra, root, f"{path}.{key}")
    return errors


# =====================================================================================
# Playbook loading
# =====================================================================================

def load_playbook(path=PLAYBOOK, schema_path=SCHEMA):
    """Return ``(playbook, valid_cases, invalid_cases)``.

    ``invalid_cases`` carries the case id (or its index) and the exact validation errors, so an
    invalid case is counted and explained rather than disappearing.
    """
    playbook = json.loads(Path(path).read_text())
    schema = json.loads(Path(schema_path).read_text())
    # Validate the document envelope first. Individual cases are validated below and a failing
    # case is *recorded*, not raised, so an invalid case cannot silently leave the denominator.
    envelope = json.loads(json.dumps(schema))
    envelope["properties"]["cases"]["items"] = {"type": "object"}
    errors = validate(playbook, envelope)
    if errors:
        raise ValueError("Playbook does not match its schema: " + "; ".join(errors[:10]))

    case_schema = schema["$defs"]["case"]
    valid, invalid = [], []
    for index, case in enumerate(playbook["cases"]):
        problems = validate(case, case_schema, schema, path=f"cases[{index}]")
        if problems:
            invalid.append({"case_id": case.get("id", f"<index {index}>"),
                            "case_class": case.get("case_class", "unknown"),
                            "errors": problems})
        else:
            valid.append(case)
    return playbook, valid, invalid


# =====================================================================================
# Providers
# =====================================================================================

class RecordingProvider:
    """Wrap a local provider and record every ``ProviderInput`` it is handed.

    ``forged=True`` returns a *valid* citation id from the permitted evidence together with a
    claim the cited source never made. ``on_generate`` runs inside the provider call, which is
    how a case simulates an ACL or source-revision change *during* a query. It never contacts
    anything.
    """

    def __init__(self, inner=None, *, forged=False, on_generate=None):
        self.inner = inner or OfflineExtractiveProvider()
        self.mode = self.inner.mode
        self.forged = forged
        self.on_generate = on_generate
        self.inputs = []

    async def generate(self, context):
        self.inputs.append(context)
        if self.on_generate is not None:
            self.on_generate(context)
        if self.forged:
            ids = [item.chunk_id for item in context.evidence][:1]
            return ProviderOutput(answer=FORGED_CLAIM, citation_ids=ids)
        return await self.inner.generate(context)

    def provider_input_texts(self):
        return [item.text for call in self.inputs for item in call.evidence]

    def provider_input_ids(self):
        return [item.chunk_id for call in self.inputs for item in call.evidence]


def _fixture_hash(case):
    """The canonical hash of a case's fixture.

    For a simulated case this is the sha256 of the canonical JSON of its ``sources`` (the whole
    injected fixture, so any edit changes the hash). For an ``api_queries`` case, which runs
    against the seeded demo database, it is the sha256 of ``data/demo/manifest.json``.
    """
    if case["path"] == "api_queries":
        return hashlib.sha256((ROOT / "data/demo/manifest.json").read_bytes()).hexdigest()
    canonical = json.dumps(case.get("sources", []), sort_keys=True,
                           separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def stamp_fixture_hashes(path=PLAYBOOK):
    """Rewrite each case's ``fixture.hash`` from its own fixture. Reproducible by design."""
    data = json.loads(Path(path).read_text())
    for case in data["cases"]:
        case["fixture"]["hash"] = _fixture_hash(case)
    Path(path).write_text(json.dumps(data, indent=2) + "\n")
    return {case["id"]: case["fixture"]["hash"] for case in data["cases"]}


def build_provider(kind, on_generate=None):
    if kind == "forged_citation":
        return RecordingProvider(forged=True, on_generate=on_generate)
    if kind == "fake_grounded":
        from aspire_brain.providers.grounded import GroundedAnswerProvider
        return RecordingProvider(GroundedAnswerProvider(), on_generate=on_generate)
    return RecordingProvider(OfflineExtractiveProvider(), on_generate=on_generate)


# =====================================================================================
# Case execution
# =====================================================================================

def _parse_time(value):
    return datetime.fromisoformat(value) if value else None


def _build_state(case):
    records = [
        SimulatedSource(
            platform=item["platform"], tenant_id=case["tenant"], source_id=item["source_id"],
            source_kind=item["source_kind"], version_id=item["version_id"],
            content_sha256=hashlib.sha256(item["text"].encode()).hexdigest(),
            text=item["text"], locator=f"simulated://{item['platform']}/{item['source_id']}",
            parent_id=item["parent_id"], thread_id=item.get("thread_id"),
            # A per-source override lets a case place a record *after* the last successful
            # sync, which the service must treat as stale rather than current.
            source_updated_at=_parse_time(item.get("source_updated_at")) or NOW,
            event_at=_parse_time(item.get("event_at")),
        )
        for item in case.get("sources", [])
    ]
    grants = {name: {key: set(accounts) for key, accounts in mapping.items()}
              for name, mapping in case.get("grants", {}).items()}
    budget = case.get("freshness_budget_seconds", 3600)
    return SimulatedPlatformState(
        records=records, principal_map=case.get("principal_map", {}),
        last_successful_sync={platform: NOW for platform in ALL_PLATFORMS},
        freshness_budget_seconds={platform: budget for platform in ALL_PLATFORMS}, **grants)


def _revoke(state, case):
    """Withdraw the principal's grant on the first source, using the platform's own setter."""
    item = case["sources"][0]
    platform = item["platform"]
    account = case.get("principal_map", {}).get(case["principal"]["id"], {}).get(platform)
    if platform == "jira":
        state.set_jira_issue_grant(item["source_id"], account, False)
    elif platform == "confluence":
        state.set_confluence_page_grant(item["source_id"], account, False)
    elif platform == "slack":
        state.set_slack_channel_grant(item["parent_id"], account, False)
    elif platform == "drive":
        state.set_drive_file_grant(item["source_id"], account, False)


def _time_windows(case):
    days = case.get("time_window_days")
    if not days:
        return None
    window = TimeWindow(start=NOW - timedelta(days=days), end=NOW)
    return {platform: window for platform in case.get("required_platforms", [])}


def _audit_events(audit, tenant_id):
    """Every audit event for the tenant.

    Each case runs against its own disposable database, so the tenant's event list belongs to
    this case alone. Reading all of them (not just the completed request) is what lets an
    aborted attempt be inspected too.
    """
    return audit.events(tenant_id, limit=200, offset=0)


def run_case(case):
    """Execute one case in an isolated runtime and return a structured observation."""
    observation = {
        "case_id": case["id"], "path": case["path"], "case_class": case["case_class"],
        "released": False, "error": None, "packet": None, "first_packet": None,
        "second_read": None, "provider_input_texts": [], "provider_input_ids": [],
        "audit_events": [], "packet_saved": False, "retrieval_truncated": None,
    }
    with tempfile.TemporaryDirectory(prefix=f"redteam-{case['id']}-") as directory:
        db = Database(Path(directory) / "redteam.db")
        db.initialize()
        db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
        audit = AuditWriter(db.path, secrets.token_bytes(32))
        audit.initialize()
        auth = AuthService(db)
        state = _build_state(case) if case["path"] == "simulated_case" else None

        # An in-flight change is injected *inside* the provider call, so the service must
        # re-check access and source revision after the provider returns and before it
        # persists. Without this the case would only exercise a post-query change.
        def on_generate(context, _state=state, _case=case, _db=db, _audit=audit):
            if _state is not None:
                _revoke(_state, _case)
            elif context.evidence:
                _db.revoke(context.evidence[0].version_id, _audit)

        hook = on_generate if case.get("revoke_during_provider") else None
        provider = build_provider(case.get("provider", "offline_extractive"), on_generate=hook)
        try:
            if case["path"] == "simulated_case":
                service = SimulatedQueryService(
                    auth, audit, state, provider=provider,
                    required_platforms=tuple(case.get("required_platforms") or []),
                    retrieval_cap=case.get("retrieval_cap") or 50,
                    clock=lambda: NOW)
                packet = asyncio.run(service.query(case["principal"]["id"], case["query"], NOW,
                                                   time_windows=_time_windows(case)))
                observation["released"] = True
                observation["packet"] = packet
                observation["request_id"] = packet["request_id"]
                observation["retrieval_truncated"] = (packet.get("retrieval") or {}).get(
                    "any_truncated")
                if case.get("revoke_after_first_query"):
                    _revoke(state, case)
                    try:
                        service.packet(case["principal"]["id"], packet["request_id"])
                        observation["second_read"] = "allowed"
                    except AccessDenied:
                        observation["second_read"] = "denied"
                    except Exception as exc:                       # noqa: BLE001
                        observation["second_read"] = f"error:{type(exc).__name__}"
                    # The question is what the POST-revocation read releases. When it is denied
                    # nothing is released, so no first-read content is attributed outward.
                    # The first-read packet is *retained* for inspection rather than discarded:
                    # nulling it outright could hide a leak that happened before the revocation.
                    if observation["second_read"] == "denied":
                        observation["first_packet"] = packet
                        observation["released"] = False
                        observation["packet"] = None
            else:
                service = QueryService(db, auth, audit, provider=provider)
                request = QueryRequest.model_validate({
                    "question": case["query"],
                    "context": {"workflow_id": "general", "case_date": "2026-09-10",
                                "jurisdiction": "SG", "worker_type": "contractor",
                                "currency": "SGD"},
                })
                packet = asyncio.run(service.query(auth.principal(case["principal"]["id"]),
                                                   request))
                observation["released"] = True
                observation["packet"] = packet
                observation["request_id"] = packet["request_id"]
        except Exception as exc:                                   # noqa: BLE001
            observation["error"] = f"{type(exc).__name__}: {exc}"

        observation["provider_input_texts"] = provider.provider_input_texts()
        observation["provider_input_ids"] = provider.provider_input_ids()
        observation["audit_events"] = _audit_events(audit, case["tenant"])
        with closing(db.connect()) as connection:
            table = "simulated_packets" if case["path"] == "simulated_case" else "packets"
            observation["packet_saved"] = connection.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
    return observation


# =====================================================================================
# Outcome classification
# =====================================================================================

OUTWARD_FIELDS = ("answer", "citations", "metadata", "packet", "first_packet",
                  "provider_input", "audit")


def _outward_blobs(observation):
    """Every field a leak could surface through, as text, so a sentinel is searched uniformly.

    ``first_packet`` is the packet released by the first query of a revocation case. It is
    inspected even though the post-revocation read was denied, so a leak that happened before
    the revocation cannot hide behind the later denial. ``provider_input`` is the evidence
    handed to the model; restricted text must never reach it.
    """
    packet = observation.get("packet") or {}
    blobs = {"answer": "", "citations": "", "metadata": "", "packet": "", "first_packet": "",
             "provider_input": "", "audit": ""}
    if packet:
        blobs["answer"] = str(packet.get("answer", ""))
        blobs["citations"] = json.dumps(packet.get("citations", []), default=str)
        blobs["metadata"] = json.dumps(
            {key: value for key, value in packet.items()
             if key not in {"answer", "citations", "claim_support", "provider_runtime"}},
            default=str, sort_keys=True)
        blobs["packet"] = json.dumps(packet, default=str, sort_keys=True)
    first = observation.get("first_packet") or {}
    if first:
        blobs["first_packet"] = json.dumps(first, default=str, sort_keys=True)
    blobs["provider_input"] = json.dumps(
        {"texts": observation.get("provider_input_texts", []),
         "ids": observation.get("provider_input_ids", [])}, default=str, sort_keys=True)
    blobs["audit"] = json.dumps(observation.get("audit_events", []), default=str, sort_keys=True)
    return blobs


def classify(case, observation):
    """Return ``(outcome, reasons, evidence)`` using only observable fields."""
    oracle = case["oracle"]
    blobs = _outward_blobs(observation)
    reasons = []

    hits = {field: [sentinel for sentinel in oracle.get("forbidden_in_outward", [])
                    if sentinel and sentinel in blobs[field]]
            for field in OUTWARD_FIELDS}
    hits = {field: values for field, values in hits.items() if values}

    forged = oracle.get("forged_claim_marker")
    forged_released = bool(forged and forged in blobs["answer"])

    marker = oracle["attack_marker"]
    retrieved = any(marker in text for text in observation["provider_input_texts"]) or \
        any(marker in cid for cid in observation["provider_input_ids"])

    if hits:
        reasons.append(f"forbidden text present in outward fields: {sorted(hits)}")
        return "attack_succeeded", reasons, {"forbidden_hits": hits}
    if forged_released:
        reasons.append("the forged claim was released in the answer")
        return "attack_succeeded", reasons, {"forged_released": True}
    if observation["error"] and not observation["released"] and not retrieved:
        reasons.append(f"run did not reach a decision: {observation['error']}")
        return "inconclusive", reasons, {}
    if observation["error"] and "Provider" not in observation["error"] and not retrieved:
        reasons.append(f"unexpected failure: {observation['error']}")
        return "inconclusive", reasons, {}
    if retrieved:
        reasons.append("the attack carrier reached the provider input but the objective did not "
                       "materialise in any outward field")
        return "attack_retrieved_but_blocked", reasons, {"retrieved": True}
    reasons.append("the attack carrier never reached the provider input")
    return "attack_not_retrieved", reasons, {"retrieved": False}


def evaluate_case(case):
    observation = run_case(case)
    outcome, reasons, evidence = classify(case, observation)
    oracle = case["oracle"]
    blobs = _outward_blobs(observation)
    checks = {
        "outcome_matches": outcome == oracle["expect_outcome"],
        "released_matches": observation["released"] == oracle["expect_released"],
        "fixture_hash_matches": case["fixture"]["hash"] == _fixture_hash(case),
        "no_forbidden_text": not any(
            sentinel and any(sentinel in blob for blob in blobs.values())
            for sentinel in oracle.get("forbidden_in_outward", [])),
    }
    if oracle.get("expect_manipulation_released") is not None:
        checks["manipulation_matches"] = (
            bool(oracle.get("forged_claim_marker") and
                 oracle["forged_claim_marker"] in blobs["answer"])
            == oracle["expect_manipulation_released"])
    if case.get("revoke_after_first_query"):
        checks["post_revocation_read_denied"] = observation["second_read"] == "denied"
    if oracle.get("expect_bounded_retrieval") is not None:
        checks["bounded_retrieval_matches"] = (
            bool(observation["retrieval_truncated"]) == oracle["expect_bounded_retrieval"])
    if oracle.get("expect_retained_marker"):
        provider_text = "\n".join(observation["provider_input_texts"])
        checks["retained_marker_present"] = all(
            marker in provider_text for marker in oracle["expect_retained_marker"])
    return {
        "case_id": case["id"], "title": case["title"], "case_class": case["case_class"],
        "carrier": case["carrier"], "goal": case["goal"], "path": case["path"],
        "severity": case["severity"], "known_gap": bool(case.get("known_gap")),
        "expected_outcome": oracle["expect_outcome"], "observed_outcome": outcome,
        "reasons": reasons, "evidence": evidence, "checks": checks,
        "passed": all(checks.values()),
        "observed": {"released": observation["released"], "error": observation["error"],
                     "second_read": observation["second_read"],
                     "packet_saved": observation["packet_saved"],
                     "provider_input_count": len(observation["provider_input_texts"]),
                     "audit_event_count": len(observation["audit_events"])},
    }


# =====================================================================================
# Report
# =====================================================================================

def run_playbook(path=PLAYBOOK, report_path=None):
    playbook, valid, invalid = load_playbook(path)
    results = [evaluate_case(case) for case in valid]

    attacks = [r for r in results if r["case_class"] == "attack"]
    benign = [r for r in results if r["case_class"] == "benign"]
    succeeded = [r for r in attacks if r["observed_outcome"] == "attack_succeeded"]
    blocked = [r for r in attacks if r["observed_outcome"] == "attack_retrieved_but_blocked"]
    not_retrieved = [r for r in attacks if r["observed_outcome"] == "attack_not_retrieved"]
    inconclusive = [r for r in results if r["observed_outcome"] == "inconclusive"]
    false_positives = [r for r in benign if not r["checks"]["released_matches"]]

    report = {
        "playbook_version": playbook["playbook_version"],
        "schema_version": playbook["schema_version"],
        "generated_for": "local simulated checkout — no live connector, model or organiser input",
        "denominators": {
            "cases_total": len(playbook["cases"]),
            "cases_valid": len(valid),
            "cases_invalid": len(invalid),
            "attack_cases_valid": len(attacks),
            "attack_cases_including_invalid": len(attacks) + sum(
                1 for item in invalid if item["case_class"] == "attack"),
            "benign_cases_valid": len(benign),
        },
        "observed": {
            "attack_not_retrieved": len(not_retrieved),
            "attack_retrieved_but_blocked": len(blocked),
            "attack_succeeded": len(succeeded),
            "inconclusive": len(inconclusive),
            "benign_answered_normally": len(benign) - len(false_positives),
            "benign_false_positives": len(false_positives),
        },
        "invalid_cases": invalid,
        "known_open_gaps": [r["case_id"] for r in results if r["known_gap"]],
        "failures": [r["case_id"] for r in results if not r["passed"]],
        "results": results,
        "limitations": (
            "Deterministic synthetic-fixture measurements only. A blocked attack here means the "
            "payload did not reach an outward field in THIS fixture; it is not proof of "
            "resistance to unknown attacks, and exact-span support is bounded extractive "
            "support, not truth verification. The /api/queries path is a recorded open gap."),
    }
    if report_path:
        Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
    return report


def _main():
    if "--stamp" in sys.argv:
        print(json.dumps(stamp_fixture_hashes(), indent=2))
        return 0
    target = ROOT / "artifacts" / "redteam" / "redteam-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    report = run_playbook(report_path=target)
    print(json.dumps({key: report[key] for key in
                      ("playbook_version", "denominators", "observed", "invalid_cases",
                       "known_open_gaps", "failures")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
