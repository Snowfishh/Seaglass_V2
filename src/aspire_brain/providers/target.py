"""Offline V1 target contracts. No transport, SDK, credentials, or factory registration.

Only the authenticated service may construct the authorized projection. An authorization
reference is a local attestation contract, not a substitute for authentication or a signed
execution approval. All dispatch here is explicitly simulated; live dispatch is impossible.
Quotation support remains a separate service gate with the open D-DEF security prerequisite.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol

from aspire_brain.providers import ProviderInput, ProviderOutput
from aspire_brain.providers.runtime import (
    SUPPORTED_TARGET_MODEL,
    ProviderRuntimeConfig,
    ProviderRuntimeRecord,
    local_runtime_record,
)

NO_EVIDENCE_NOTICE = "I cannot answer from the available evidence."
MAX_RESPONSE_BYTES = 100000
#: Every field the reviewed outbound body may carry; anything else is unreviewed.
BODY_KEYS = frozenset({"model", "messages", "stream", "include_reasoning", "reasoning_effort",
                       "max_completion_tokens", "response_format"})


def canonical_json(body) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def canonical_fingerprint(body) -> str:
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Non-finite JSON value")


def _json(raw):
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def parse_target_output(raw: str, *, allowed_ids, finish_reason, refusal=None) -> ProviderOutput:
    """Strict local shape/membership check, NOT source truth or quotation support."""
    if finish_reason != "stop" or refusal is not None:
        raise ValueError("Refused or incomplete target result")
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("Invalid target response size")
    try:
        output = ProviderOutput.model_validate(_json(raw))
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid V1 target output") from exc
    if not output.citation_ids or set(output.citation_ids) - set(allowed_ids):
        raise ValueError("Unauthorized or absent citation")
    return output


def _bounded_text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Invalid bounded text")
    value.encode("utf-8")


@dataclass(frozen=True)
class TargetEvidence:
    citation_id: str
    text: str

    def __post_init__(self):
        ProviderOutput(answer=self.text, citation_ids=[self.citation_id])
        _bounded_text(self.text, 10000)


@dataclass(frozen=True)
class TargetInput:
    question: str
    evidence: tuple[TargetEvidence, ...]
    authorization_ref: str

    def __post_init__(self):
        _bounded_text(self.question, 2000)
        _bounded_text(self.authorization_ref, 200)
        if not isinstance(self.evidence, tuple) or any(
                not isinstance(item, TargetEvidence) for item in self.evidence):
            raise ValueError("Evidence must be an immutable typed tuple")
        ids = [item.citation_id for item in self.evidence]
        if len(ids) > 40 or len(ids) != len(set(ids)):
            raise ValueError("Oversized or duplicated evidence")
        if sum(len(item.text) for item in self.evidence) > 10000:
            raise ValueError("Evidence exceeds bounded context")

    @classmethod
    def from_authorized(cls, context: ProviderInput, *, authorization_ref: str,
                        authorized_ids: frozenset[str]) -> TargetInput:
        """Project only validated question and authorized evidence, not context/ACL metadata.

        The calling service owns authentication and the fresh permission check. This helper
        cannot authenticate a caller using its asserted reference; it is an internal boundary.
        """
        if not isinstance(authorized_ids, frozenset):
            raise ValueError("Authorization IDs must be frozen")
        if any(item.chunk_id not in authorized_ids for item in context.evidence):
            raise ValueError("Evidence lacks authorization")
        return cls(context.question, tuple(TargetEvidence(item.chunk_id, item.text)
                   for item in context.evidence), authorization_ref)


@dataclass(frozen=True)
class TargetTemplate:
    body_json: str
    fingerprint_sha256: str

    def __post_init__(self):
        body = _json(self.body_json)
        if canonical_fingerprint(body) != self.fingerprint_sha256:
            raise ValueError("Frozen template fingerprint mismatch")
        if (body.get("model") != SUPPORTED_TARGET_MODEL or body.get("stream") is not False
                or body.get("include_reasoning") is not False
                or set(body) != {"model", "messages", "response_format", "stream",
                                 "include_reasoning"}):
            raise ValueError("Unsupported frozen target template")
        schema = body["response_format"]
        if (schema.get("type") != "json_schema"
                or schema["json_schema"].get("strict") is not True
                or schema["json_schema"]["schema"].get("additionalProperties") is not False
                or set(schema["json_schema"]["schema"]["properties"]) != {"answer", "citation_ids"}
                or schema["json_schema"]["schema"].get("required") != ["answer", "citation_ids"]):
            raise ValueError("Unsupported target schema; no downgrade")
        if (len(body["messages"]) != 2 or body["messages"][0]["role"] != "system"
                or body["messages"][1]["role"] != "user"):
            raise ValueError("Invalid trusted prompt template")

    @classmethod
    def consume(cls, manifest_json: str, *, expected_fingerprint: str) -> TargetTemplate:
        """Consume reviewed bytes and independently recompute the saved request-body hash."""
        saved = _json(manifest_json)
        if saved["fingerprint_sha256"] != expected_fingerprint:
            raise ValueError("Reviewed fingerprint mismatch")
        return cls(canonical_json(saved["request_body"]), expected_fingerprint)


@dataclass(frozen=True)
class RequestManifest:
    correlation_id: str
    target_input: TargetInput
    body_json: str
    fingerprint_sha256: str
    config_sha256: str
    parent_fingerprint_sha256: str
    input_upper_bound: int
    system_message_sha256: str
    max_completion_tokens: int

    def __post_init__(self):
        """Re-derive the reviewed projection so a mutated body cannot be recorded as sent."""
        _bounded_text(self.correlation_id, 200)
        if len(self.system_message_sha256) != 64:
            raise ValueError("Invalid trusted-prompt digest")
        body = _json(self.body_json)
        if canonical_fingerprint(body) != self.fingerprint_sha256:
            raise ValueError("Request body fingerprint mismatch")
        if set(body) != BODY_KEYS:
            raise ValueError("Request body carries unreviewed fields")
        if body["model"] != SUPPORTED_TARGET_MODEL:
            raise ValueError("Request body names an unsupported target model")
        if body["stream"] is not False or body["include_reasoning"] is not False:
            raise ValueError("Request body must not stream or request reasoning")
        messages = body["messages"]
        if (not isinstance(messages, list) or len(messages) != 2
                or not isinstance(messages[0], dict) or set(messages[0]) != {"role", "content"}
                or messages[0]["role"] != "system"
                or messages[1] != {"role": "user", "content": _user_content(self.target_input)}):
            raise ValueError("Request body does not match the reviewed projection")
        if (hashlib.sha256(messages[0]["content"].encode("utf-8")).hexdigest()
                != self.system_message_sha256):
            raise ValueError("Request body uses an unreviewed system prompt")
        if body["max_completion_tokens"] != self.max_completion_tokens:
            raise ValueError("Request body completion bound mismatch")
        if body["response_format"] != _response_format():
            raise ValueError("Request body must keep the frozen strict V1 schema")
        if self.input_upper_bound != len(self.body_json.encode("utf-8")) + 1024:
            raise ValueError("Conservative byte bound mismatch")


def _response_schema():
    # Groq rejected uniqueItems in the observed 5E attempt. Keep the documented
    # wire subset; ProviderOutput and parse_target_output enforce local bounds,
    # unique identifiers and authorized citation membership before release.
    return {
        "type": "object", "additionalProperties": False, "required": ["answer", "citation_ids"],
        "properties": {
            "answer": {"type": "string"},
            "citation_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def _response_format():
    return {"type": "json_schema", "json_schema": {
        "name": "target_response_v1", "strict": True, "schema": _response_schema()}}


def _user_content(target_input):
    return canonical_json({"question": target_input.question, "evidence": [
        {"citation_id": item.citation_id, "text": item.text} for item in target_input.evidence]})


def _request_body(target_input, template_body, config):
    # This is a derived request, not mutation of the reviewed provisional manifest. Question
    # and evidence are explicit untrusted JSON data; all other input fields are omitted.
    return {"model": config.model, "messages": [template_body["messages"][0],
            {"role": "user", "content": _user_content(target_input)}], "stream": False,
            "include_reasoning": False, "reasoning_effort": config.reasoning_effort,
            "max_completion_tokens": config.output_token_cap + config.reasoning_token_cap,
            "response_format": _response_format()}


def build_manifest(target_input: TargetInput, template: TargetTemplate,
                   config: ProviderRuntimeConfig, *, correlation_id: str) -> RequestManifest:
    config.require_target_envelope()
    if not target_input.evidence:
        raise ValueError("No evidence means service abstention, not a request")
    template_body = _json(template.body_json)
    body = _request_body(target_input, template_body, config)
    encoded = canonical_json(body)
    # UTF-8 byte count + fixed envelope allowance is an offline conservative reservation
    # contract, not a vendor tokenizer measurement. Live preflight must verify token bounds.
    bound = len(encoded.encode("utf-8")) + 1024
    if bound > config.input_token_cap:
        raise ValueError("Request exceeds conservative input reservation")
    return RequestManifest(
        correlation_id=correlation_id, target_input=target_input, body_json=encoded,
        fingerprint_sha256=canonical_fingerprint(body),
        config_sha256=canonical_fingerprint(config.model_dump(mode="json")),
        parent_fingerprint_sha256=template.fingerprint_sha256, input_upper_bound=bound,
        system_message_sha256=hashlib.sha256(
            template_body["messages"][0]["content"].encode("utf-8")).hexdigest(),
        max_completion_tokens=body["max_completion_tokens"])


@dataclass(frozen=True)
class DispatchAuthorization:
    purpose: Literal["offline_fake"]
    correlation_id: str
    manifest_sha256: str
    config_sha256: str
    authorization_ref: str
    approval_ref: str
    attempt: int

    def validate(self, manifest, config):
        if self.purpose != "offline_fake":
            raise ValueError("Stage 5B cannot authorize live dispatch")
        _bounded_text(self.approval_ref, 200)
        if (self.correlation_id != manifest.correlation_id
                or self.manifest_sha256 != manifest.fingerprint_sha256
                or self.config_sha256 != manifest.config_sha256
                or self.config_sha256 != canonical_fingerprint(config.model_dump(mode="json"))
                or self.authorization_ref != manifest.target_input.authorization_ref
                or type(self.attempt) is not int or not 1 <= self.attempt <= config.request_cap):
            raise ValueError("Unbound dispatch authorization")


@dataclass(frozen=True)
class FakeReply:
    content: str
    finish_reason: str | None = "stop"
    refusal: str | None = None
    reported_model: str | None = None
    vendor_request_id: str | None = None


class FakeClient(Protocol):
    async def complete(self, manifest: RequestManifest) -> FakeReply: ...


@dataclass(frozen=True)
class FakeResult:
    output: ProviderOutput | None
    runtime: ProviderRuntimeRecord
    manifest: RequestManifest | None


class FakeCallCancelled(asyncio.CancelledError):
    """Cancellation propagates with its request-scoped conservative simulated record."""
    def __init__(self, runtime):
        super().__init__("Offline fake call cancelled")
        self.runtime = runtime


def _fake_record(manifest, config, grant, outcome, reply=None):
    return ProviderRuntimeRecord(
        mode="simulated", provider_mode="fake_grounded", outcome="not_run",
        live_request_made=False, correlation_id=manifest.correlation_id,
        requested_model=config.model, reported_model=reply.reported_model if reply else None,
        vendor_request_id=reply.vendor_request_id if reply else None,
        attempt=grant.attempt, dispatch_state="not_sent", manifest_sha256=manifest.fingerprint_sha256,
        simulated_outcome=outcome, reservation_usd=config.max_cost_usd,
        settled_cost_usd=None, uncertain_cost_usd=config.max_cost_usd,
        uncertainty_reason="simulated_full_envelope_reservation_not_vendor_bill")


async def dispatch_fake(manifest: RequestManifest, config: ProviderRuntimeConfig,
                        authorization: DispatchAuthorization | None, client: FakeClient) -> FakeResult:
    """Exercise a single injected in-process client; never installed in the live factory.

    Caller-supplied fake clients are trusted test code, not sandboxed third-party plugins.
    Authorization is data binding only, not the atomic 5D enforcement/approval verifier.
    """
    config.require_target_envelope()
    if not isinstance(authorization, DispatchAuthorization):
        raise ValueError("Separate dispatch authorization required")
    authorization.validate(manifest, config)
    # Recheck frozen bytes/bounds even if a caller bypassed a frozen dataclass constructor.
    manifest.__post_init__()
    if manifest.input_upper_bound > config.input_token_cap or not manifest.target_input.evidence:
        raise ValueError("Invalid request bounds")
    reply = None
    try:
        reply = await asyncio.wait_for(client.complete(manifest), config.timeout_seconds)
        if not isinstance(reply, FakeReply) or reply.reported_model != config.model:
            raise ValueError("Unreported or unsupported target model")
        output = parse_target_output(reply.content,
            allowed_ids=tuple(item.citation_id for item in manifest.target_input.evidence),
            finish_reason=reply.finish_reason, refusal=reply.refusal)
    except asyncio.CancelledError as exc:
        raise FakeCallCancelled(_fake_record(manifest, config, authorization, "cancelled")) from exc
    except TimeoutError:
        return FakeResult(None, _fake_record(manifest, config, authorization, "timeout"), manifest)
    except Exception:
        # No raw upstream error/payload is leaked into metadata.
        return FakeResult(None, _fake_record(manifest, config, authorization, "failed"), manifest)
    return FakeResult(output, _fake_record(manifest, config, authorization, "succeeded", reply), manifest)


async def execute_fake(target_input: TargetInput, *, correlation_id: str,
                       client: FakeClient, template: TargetTemplate | None = None,
                       config: ProviderRuntimeConfig | None = None,
                       authorization: DispatchAuthorization | None = None) -> FakeResult:
    if not target_input.evidence:
        return FakeResult(ProviderOutput(answer=NO_EVIDENCE_NOTICE, citation_ids=[]),
                          local_runtime_record("fake_grounded", correlation_id=correlation_id), None)
    if template is None or config is None:
        raise ValueError("Frozen template and runtime required")
    manifest = build_manifest(target_input, template, config, correlation_id=correlation_id)
    return await dispatch_fake(manifest, config, authorization, client)
