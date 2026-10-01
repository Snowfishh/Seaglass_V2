"""Offline V1 contract tests. No SDK, transport, key, or live entitlement."""
import asyncio
import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from aspire_brain.models import Evidence
from aspire_brain.providers import ProviderInput, ProviderOutput
from aspire_brain.providers.claims import evaluate_claim_support

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "artifacts/prompt5a-amended-autonomous-2026-09-28/manifests/target-request.v1.json"
PARENT_FINGERPRINT = "56ff8ac945c293404af14a1b8f81f4d1a1c5e184f33720bb20c61c32dbc5b6dc"
QUOTE = "Singapore contractor travel cap: SGD 250 per claim."


def api():
    from aspire_brain.providers import target
    return target


def runtime(**updates):
    from aspire_brain.providers.runtime import ProviderRuntimeConfig
    values = dict(service="groq", model="openai/gpt-oss-20b",
                  endpoint="https://api.groq.com/openai/v1/chat/completions",
                  region=None, max_cost_usd="1", timeout_seconds=1,
                  request_cap=1, input_token_cap=12000, output_token_cap=128,
                  reasoning_token_cap=128, total_token_cap=12256, reasoning_effort="low")
    return ProviderRuntimeConfig(**(values | updates))


def provider_input():
    return ProviderInput(question="What is the travel cap?", context={
        "tenant_id": "DENIED-TENANT", "api_key": "SYNTHETIC-DO-NOT-SEND",
        "history": "UNRELATED-TRANSCRIPT", "expense_amount": "99.00"},
        evidence=[Evidence(chunk_id="allowed:1", text=QUOTE, version_id="version",
                           source_locator="PRIVATE-LOCATOR", content_hash="local-hash",
                           document_id="document")], decision_summary="SERVICE-ONLY-NOTICE")


def request(*, empty=False):
    t = api()
    source = provider_input()
    if empty:
        source = source.model_copy(update={"evidence": []})
    return t.TargetInput.from_authorized(source, authorization_ref="synthetic-authz-1",
                                         authorized_ids=frozenset({"allowed:1"}))


def template():
    return api().TargetTemplate.consume(PARENT.read_text(), expected_fingerprint=PARENT_FINGERPRINT)


def prepared(correlation="request-1"):
    t = api()
    config = runtime()
    manifest = t.build_manifest(request(), template(), config, correlation_id=correlation)
    grant = t.DispatchAuthorization(purpose="offline_fake", correlation_id=correlation,
        manifest_sha256=manifest.fingerprint_sha256, config_sha256=manifest.config_sha256,
        authorization_ref="synthetic-authz-1", approval_ref="synthetic-test-only", attempt=1)
    return config, manifest, grant


@pytest.mark.parametrize("patch", [
    {"answer": " "}, {"answer": 123}, {"answer": None}, {"answer": "x" * 16001},
    {"citation_ids": ["a", "a"]}, {"citation_ids": [""]},
    {"citation_ids": ["bad\nid"]}, {"citation_ids": [1]}, {"citation_ids": "a"},
    {"citation_ids": ["a" * 201]}, {"citation_ids": [f"c{i}" for i in range(51)]},
    {"abstain": False}, {"citation_ids": None},
])
def test_v1_output_rejects_wrong_shape_types_bounds_and_duplicates(patch):
    with pytest.raises((ValueError, ValidationError)):
        ProviderOutput.model_validate({"answer": QUOTE, "citation_ids": ["allowed:1"]} | patch)


@pytest.mark.parametrize("raw", ["", "{", "[]", "null", '"text"', '{}',
    '{"answer":"x"}', '{"citation_ids":[]}',
    '{"answer":"x","answer":"y","citation_ids":["allowed:1"]}',
    '{"answer":NaN,"citation_ids":[]}',
    '{"answer":"x","citation_ids":["unknown"]}',
    '{"answer":"x","citation_ids":[]}',
    '{"answer":"x","citation_ids":["allowed:1"],"extra":1}',
    '{"answer":"\\ud800","citation_ids":["allowed:1"]}', "x" * 100001,
])
def test_local_parser_fail_closed(raw):
    with pytest.raises(ValueError):
        api().parse_target_output(raw, allowed_ids=("allowed:1",), finish_reason="stop")


@pytest.mark.parametrize("finish,refusal", [("length", None), ("tool_calls", None),
                                           (None, None), ("stop", "refused")])
def test_refused_or_incomplete_result_rejected(finish, refusal):
    with pytest.raises(ValueError):
        api().parse_target_output(json.dumps({"answer": QUOTE, "citation_ids": ["allowed:1"]}),
                                  allowed_ids=("allowed:1",), finish_reason=finish, refusal=refusal)


def test_shape_and_citation_membership_are_not_claim_support():
    raw = json.dumps({"answer": "The allowance is generous.", "citation_ids": ["allowed:1"]})
    output = api().parse_target_output(raw, allowed_ids=("allowed:1",), finish_reason="stop")
    report = evaluate_claim_support(answer=output.answer, citation_ids=output.citation_ids,
        evidence={"allowed:1": QUOTE}, provider_mode="fake_grounded")
    assert report["all_supported"] is False
    assert report["unsupported_claims"] == 1


def test_template_consumed_with_original_fingerprint_and_no_mutation():
    before = hashlib.sha256(PARENT.read_bytes()).hexdigest()
    value = template()
    assert value.fingerprint_sha256 == PARENT_FINGERPRINT
    modified = json.loads(PARENT.read_text())
    modified["request_body"]["model"] = "other"
    with pytest.raises(ValueError):
        api().TargetTemplate.consume(json.dumps(modified), expected_fingerprint=PARENT_FINGERPRINT)
    assert hashlib.sha256(PARENT.read_bytes()).hexdigest() == before


def test_manifest_is_minimized_frozen_and_reproducible():
    t = api()
    config, manifest, _ = prepared()
    body = json.loads(manifest.body_json)
    wire = manifest.body_json
    for denied in ("DENIED-TENANT", "SYNTHETIC-DO-NOT-SEND", "UNRELATED-TRANSCRIPT",
                   "PRIVATE-LOCATOR", "SERVICE-ONLY-NOTICE", "synthetic-authz-1", "request-1"):
        assert denied not in wire
    assert body["reasoning_effort"] == "low"
    assert body["stream"] is False and body["include_reasoning"] is False
    assert body["max_completion_tokens"] == config.output_token_cap + config.reasoning_token_cap
    assert set(body["response_format"]["json_schema"]["schema"]["properties"]) == {
        "answer", "citation_ids"}
    assert manifest.parent_fingerprint_sha256 == PARENT_FINGERPRINT
    assert manifest.fingerprint_sha256 == t.canonical_fingerprint(body)
    assert manifest.input_upper_bound >= len(wire.encode("utf-8"))
    assert manifest == t.build_manifest(request(), template(), config, correlation_id="request-1")
    with pytest.raises((FrozenInstanceError, ValidationError, AttributeError)):
        manifest.body_json = "changed"
    source = provider_input()
    frozen = t.TargetInput.from_authorized(source, authorization_ref="authz",
                                          authorized_ids=frozenset({"allowed:1"}))
    source.evidence.clear()
    assert frozen.evidence[0].text == QUOTE


def test_input_requires_authorized_bounded_evidence_and_question():
    t = api()
    with pytest.raises(ValueError):
        t.TargetInput.from_authorized(provider_input(), authorization_ref="authz",
                                      authorized_ids=frozenset())
    with pytest.raises(ValueError):
        t.TargetInput.from_authorized(provider_input(), authorization_ref="",
                                      authorized_ids=frozenset({"allowed:1"}))
    for patch in ({"question": " "}, {"question": "x" * 2001},
                  {"evidence": provider_input().evidence * 2}):
        with pytest.raises(ValueError):
            t.TargetInput.from_authorized(provider_input().model_copy(update=patch),
                authorization_ref="authz", authorized_ids=frozenset({"allowed:1"}))
    with pytest.raises(ValueError):
        t.build_manifest(request(), template(), runtime(input_token_cap=1), correlation_id="r")


class Client:
    def __init__(self, *, raw=None, finish="stop", reported_model="openai/gpt-oss-20b", delay=0):
        self.calls = []
        self.raw, self.finish, self.reported_model, self.delay = raw, finish, reported_model, delay

    async def complete(self, manifest):
        self.calls.append(manifest)
        await asyncio.sleep(self.delay)
        return api().FakeReply(content=self.raw or json.dumps({
            "answer": QUOTE, "citation_ids": ["allowed:1"]}), finish_reason=self.finish,
            reported_model=self.reported_model, vendor_request_id="fake-" + manifest.correlation_id)


def test_fake_dispatch_records_are_request_scoped_under_concurrency():
    t = api()
    client = Client(delay=0.001)

    async def run():
        async def one(correlation):
            config, manifest, grant = prepared(correlation)
            return await t.dispatch_fake(manifest, config, grant, client)
        return await asyncio.gather(one("r1"), one("r2"))

    results = asyncio.run(run())
    assert len(client.calls) == 2
    for correlation, result in zip(("r1", "r2"), results, strict=True):
        assert result.output.answer == QUOTE
        assert result.runtime.correlation_id == correlation
        assert result.runtime.vendor_request_id == "fake-" + correlation
        assert result.runtime.mode == "simulated" and result.runtime.outcome == "not_run"
        assert result.runtime.live_request_made is False
        assert result.runtime.simulated_outcome == "succeeded"
        assert result.runtime.settled_cost_usd is None
        assert result.runtime.uncertain_cost_usd > 0
    assert results[0].runtime is not results[1].runtime


def test_dispatch_requires_bound_external_authorization_not_enablement():
    t = api()
    config, manifest, grant = prepared()
    client = Client()
    with pytest.raises(ValueError):
        asyncio.run(t.dispatch_fake(manifest, config, None, client))
    for field, value in (("correlation_id", "other"), ("manifest_sha256", "0" * 64),
                         ("config_sha256", "0" * 64), ("authorization_ref", "other")):
        from dataclasses import replace
        with pytest.raises(ValueError):
            asyncio.run(t.dispatch_fake(manifest, config, replace(grant, **{field: value}), client))
    assert client.calls == []


def test_manifest_cannot_smuggle_unreviewed_context_or_mismatched_input():
    from dataclasses import replace
    t = api()
    _, manifest, _ = prepared()
    for mutate in (lambda body: body.update(tools=[{"name": "forbidden"}]),
                   lambda body: body["messages"][0].update(content="unreviewed prompt"),
                   lambda body: body["messages"][1].update(content="unrelated input")):
        body = json.loads(manifest.body_json)
        mutate(body)
        encoded = t.canonical_json(body)
        with pytest.raises(ValueError):
            replace(manifest, body_json=encoded, fingerprint_sha256=t.canonical_fingerprint(body),
                    input_upper_bound=len(encoded.encode("utf-8")) + 1024)


def test_no_evidence_service_abstention_has_no_send_or_manifest():
    t = api()
    client = Client()
    result = asyncio.run(t.execute_fake(request(empty=True), correlation_id="empty", client=client))
    assert result.output.answer == t.NO_EVIDENCE_NOTICE
    assert result.output.citation_ids == []
    assert result.runtime.dispatch_state == "not_sent"
    assert result.manifest is None and client.calls == []


@pytest.mark.parametrize("client", [Client(raw="broken"), Client(finish="length"),
                                     Client(reported_model="other")])
def test_invalid_fake_response_keeps_failed_record(client):
    t = api()
    config, manifest, grant = prepared()
    result = asyncio.run(t.dispatch_fake(manifest, config, grant, client))
    assert result.output is None
    assert result.runtime.simulated_outcome == "failed"
    assert result.runtime.settled_cost_usd is None
    assert result.runtime.uncertain_cost_usd > 0


def test_timeout_and_cancellation_keep_conservative_request_record():
    from dataclasses import replace
    t = api()
    config = runtime(timeout_seconds=0.001)
    manifest = t.build_manifest(request(), template(), config, correlation_id="timeout")
    _, _, grant = prepared()
    grant = replace(grant, correlation_id="timeout", manifest_sha256=manifest.fingerprint_sha256,
                    config_sha256=manifest.config_sha256)
    result = asyncio.run(t.dispatch_fake(manifest, config, grant, Client(delay=0.03)))
    assert result.runtime.simulated_outcome == "timeout"
    assert result.runtime.uncertain_cost_usd > 0 and result.output is None

    async def cancel():
        config, manifest, grant = prepared("cancel")
        task = asyncio.create_task(t.dispatch_fake(manifest, config, grant, Client(delay=1)))
        await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(t.FakeCallCancelled) as failure:
            await task
        assert failure.value.runtime.correlation_id == "cancel"
        assert failure.value.runtime.simulated_outcome == "cancelled"
        assert failure.value.runtime.uncertain_cost_usd > 0
    asyncio.run(cancel())
