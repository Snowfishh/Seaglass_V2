"""Fixed synthetic 5E request with a guarded, pinned SDK and one durable attempt.

This adapter is explicitly injected by the synthetic service runner. It does not
register a live provider or load credentials. A mock transport always stays mock.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Callable

import httpx

from aspire_brain.providers.runtime import (
    SUPPORTED_TARGET_ENDPOINT,
    SUPPORTED_TARGET_MODEL,
    ProviderRateCard,
    ProviderRuntimeConfig,
    reserve_budget,
)
from aspire_brain.providers.target import _json, canonical_json, parse_target_output

SDK_VERSION = "1.7.0"
BODY_SHA256 = "cfacdf3f9bf655f4180b9625221a9d42bd12e609edc36fe2bfed4e3a71c15f49"
BODY_BYTES = 1181
ANSWER = "Fictional Singapore contractor travel cap: SGD 250 per claim."
CITATION = "synthetic:5e-control:v1"
QUESTION = "What is the fictional Singapore contractor travel cap?"
MAX_WIRE_RESPONSE_BYTES = 102048
SAFE_ERROR_TYPES = frozenset({"invalid_request_error", "rate_limit_error",
                              "authentication_error", "permission_error", "server_error"})
SAFE_ERROR_PARAMS = frozenset({"response_format", "model", "messages",
                               "reasoning_effort", "include_reasoning",
                               "max_completion_tokens"})
SAFE_SCHEMA_REASONS = ("unsupported_uniqueItems", "unsupported_pattern",
                       "unsupported_minLength", "unsupported_maxLength",
                       "unsupported_minItems", "unsupported_maxItems")


def approved_config() -> ProviderRuntimeConfig:
    return ProviderRuntimeConfig(
        service="groq", model=SUPPORTED_TARGET_MODEL, endpoint=SUPPORTED_TARGET_ENDPOINT,
        enabled=True, entitlement="entitled", max_cost_usd="0.01", timeout_seconds=10,
        request_cap=1, input_token_cap=3072, output_token_cap=128,
        reasoning_token_cap=128, total_token_cap=3328, reasoning_effort="low",
    )


def approved_rates() -> ProviderRateCard:
    return ProviderRateCard(input_usd_per_million="0.075", output_usd_per_million="0.30",
                            reasoning_usd_per_million="0.30")


@dataclass(frozen=True)
class Candidate:
    body_json: str
    fingerprint_sha256: str
    config: ProviderRuntimeConfig
    rates: ProviderRateCard

    def __post_init__(self):
        raw = self.body_json.encode("utf-8")
        if (hashlib.sha256(raw).hexdigest() != BODY_SHA256
                or self.fingerprint_sha256 != BODY_SHA256 or len(raw) != BODY_BYTES
                or canonical_json(_json(self.body_json)) != self.body_json):
            raise ValueError("Unreviewed request bytes")
        if self.config != approved_config() or self.rates != approved_rates():
            raise ValueError("Unreviewed price or request envelope")
        self.config.require_target_ready()
        reserve_budget(self.config, self.rates)


def load_candidate(path: Path) -> Candidate:
    packet = _json(Path(path).read_text())
    return Candidate(packet["exact_candidate_body_json"], packet["manifest_sha256"],
                     ProviderRuntimeConfig.model_validate(packet["runtime_config"]),
                     ProviderRateCard.model_validate(packet["rate_card"]))


class _BoundedStream(httpx.SyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    def __iter__(self):
        size = 0
        for part in self.stream:
            size += len(part)
            if size > MAX_WIRE_RESPONSE_BYTES:
                raise ValueError("Provider response exceeds the frozen bound")
            yield part

    def close(self):
        self.stream.close()


class GuardedTransport(httpx.BaseTransport):
    def __init__(self, candidate: Candidate, ledger_path: Path, inner: httpx.BaseTransport,
                 before_send: Callable[[], None] | None = None, request_id: str | None = None):
        candidate.__post_init__()
        self.candidate, self.ledger_path, self.inner = candidate, Path(ledger_path), inner
        self.before_send = before_send
        self.request_id = request_id
        self.claimed = False
        self.network_attempted = False

    def _claim(self):
        reservation = reserve_budget(self.candidate.config, self.candidate.rates)
        record = {"attempt": 1, "state": "possibly_sent", "restart_redispatch": False,
                  "request_id": self.request_id,
                  "manifest_sha256": BODY_SHA256,
                  "config_sha256": hashlib.sha256(canonical_json(
                      self.candidate.config.model_dump(mode="json")).encode()).hexdigest(),
                  "reservation_usd": str(reservation.reservation_usd),
                  "uncertain_cost_usd": str(reservation.reservation_usd),
                  "timestamp": datetime.now(UTC).isoformat()}
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise ValueError("Sole attempt already consumed; no redispatch") from None
        with os.fdopen(descriptor, "w") as handle:
            handle.write(canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(self.ledger_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.claimed = True

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # Compare raw serialized bytes at the final boundary, not just a parsed JSON object.
        self.candidate.__post_init__()
        if (request.method != "POST" or str(request.url) != SUPPORTED_TARGET_ENDPOINT
                or request.headers.get("host") != "api.groq.com"
                or hashlib.sha256(request.content).hexdigest() != BODY_SHA256
                or request.content != self.candidate.body_json.encode("utf-8")):
            raise ValueError("Outbound method, destination or bytes are not allowlisted")
        if self.ledger_path.exists():
            raise ValueError("Sole attempt already consumed; no redispatch")
        if self.before_send is not None:
            self.before_send()
        self._claim()
        if self.before_send is not None:
            self.before_send()
        self.network_attempted = True
        response = self.inner.handle_request(request)
        if response.headers.get("content-encoding", "identity") != "identity":
            response.close()
            raise ValueError("Compressed response is outside the frozen wire contract")
        if response.is_stream_consumed and len(response.content) > MAX_WIRE_RESPONSE_BYTES:
            response.close()
            raise ValueError("Provider response exceeds the frozen bound")
        response.stream = _BoundedStream(response.stream)
        return response

    def close(self):
        self.inner.close()


def create_client(*, api_key: str, transport: GuardedTransport):
    if importlib.metadata.version("groq") != SDK_VERSION:
        raise ValueError("Pinned SDK version required")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("Provider credential unavailable")
    from groq import Groq

    timeout = httpx.Timeout(10)
    client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False,
                          trust_env=False, headers={"Accept-Encoding": "identity"})
    return Groq(api_key=api_key, base_url="https://api.groq.com/openai/v1/",
                max_retries=0, timeout=timeout, http_client=client)


def _postflight(response: httpx.Response) -> dict:
    body = _json(response.text)
    if body.get("model") != SUPPORTED_TARGET_MODEL or len(body.get("choices", [])) != 1:
        raise ValueError("Unreviewed response identity")
    choice = body["choices"][0]
    message = choice["message"]
    if message.get("tool_calls") or message.get("function_call") or message.get("reasoning"):
        raise ValueError("Unreviewed response fields")
    output = parse_target_output(message["content"], allowed_ids=(CITATION,),
                                 finish_reason=choice["finish_reason"],
                                 refusal=message.get("refusal"))
    if output.answer != ANSWER or output.citation_ids != [CITATION]:
        raise ValueError("The fixed control requires the exact full quotation")
    return output.model_dump()


def _accounting(response: httpx.Response, candidate: Candidate) -> dict:
    usage = _json(response.text).get("usage") or {}
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens")
    if any(value is not None and (type(value) is not int or value < 0)
           for value in (prompt, completion, reasoning)):
        raise ValueError("Malformed usage counters")
    result = {"input_tokens": prompt, "completion_tokens": completion,
              "reasoning_tokens": reasoning, "cost_provenance": "reservation_not_vendor_bill"}
    config = candidate.config
    # Missing counters cannot hide a violation decidable from the known counters.
    if ((prompt is not None and prompt > config.input_token_cap)
            or (completion is not None
                and completion > config.output_token_cap + config.reasoning_token_cap)
            or (reasoning is not None and reasoning > config.reasoning_token_cap)
            or (completion is not None and reasoning is not None
                and not 0 <= completion - reasoning <= config.output_token_cap)):
        raise ValueError("Reported usage exceeds the approved token envelope")
    if any(value is None for value in (prompt, completion, reasoning)):
        return result
    # Groq completion_tokens includes reasoning; charge that inclusive count once.
    cost = (Decimal(prompt) * candidate.rates.input_usd_per_million
            + Decimal(completion) * candidate.rates.output_usd_per_million) / 1000000
    return result | {"settled_cost_usd": str(cost), "uncertain_cost_usd": "0",
                     "cost_provenance": "usage_rate_calculation_not_vendor_bill"}


def _safe_provider_error(response: httpx.Response) -> dict:
    """Keep only fixed diagnostic labels; provider messages remain untrusted and unsaved."""
    try:
        body = _json(response.text)
    except (ValueError, TypeError, RecursionError):
        return {}
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    if not isinstance(error, dict):
        return {}
    details = {}
    error_type, error_param = error.get("type"), error.get("param")
    if isinstance(error_type, str) and error_type in SAFE_ERROR_TYPES:
        details["provider_error_type"] = error_type
    if isinstance(error_param, str) and error_param in SAFE_ERROR_PARAMS:
        details["provider_error_param"] = error_param
    message = error.get("message")
    if isinstance(message, str):
        for reason in SAFE_SCHEMA_REASONS:
            if f"[{reason}]" in message:
                details["provider_error_reason"] = reason
                break
    return details


def run_preflight(candidate: Candidate, *, api_key: str, ledger_path: Path,
                  inner: httpx.BaseTransport | None = None,
                  before_send: Callable[[], None] | None = None,
                  request_id: str | None = None) -> dict:
    candidate.__post_init__()
    live = inner is None
    if live and before_send is None:
        raise ValueError("Live dispatch requires the service permission/audit guard")
    transport = GuardedTransport(candidate, ledger_path, inner if inner is not None else
                                 httpx.HTTPTransport(retries=0, trust_env=False), before_send,
                                 request_id)
    reservation = reserve_budget(candidate.config, candidate.rates)
    report = {"status": "not_run", "mode": "live" if live else "offline_mock",
              "attempt": 0, "live_request_made": False, "postflight_validated": False,
              "manifest_sha256": BODY_SHA256, "request_body_bytes": BODY_BYTES,
              "settled_cost_usd": None, "uncertain_cost_usd": "0", "output": None,
              "sdk_version": SDK_VERSION, "sdk_retries": 0, "application_retries": 0,
              "fallbacks": 0, "restart_redispatch": False}
    started = perf_counter()
    try:
        with create_client(api_key=api_key, transport=transport) as client:
            # SDK public low-level method preserves reviewed JSON key order on the wire.
            response = client.post("/chat/completions", cast_to=httpx.Response,
                                   body=_json(candidate.body_json))
            report = report | {"status": "response_received", "http_status": response.status_code,
                               "raw_response_sha256": hashlib.sha256(response.content).hexdigest()}
            usage = _accounting(response, candidate)
            report = report | usage
            output = _postflight(response)
            report = report | {"status": "validated", "postflight_validated": True,
                               "output": output}
            body = _json(response.text)
            report = report | {"requested_model": SUPPORTED_TARGET_MODEL,
                               "reported_model": SUPPORTED_TARGET_MODEL}
            vendor_id = response.headers.get("x-request-id") or body.get("id")
            # Do not copy arbitrary provider strings into reports.
            if (isinstance(vendor_id, str) and vendor_id and api_key not in vendor_id
                    and not vendor_id.startswith("gsk_") and len(vendor_id) <= 128 and all(
                        char.isalnum() or char in "_-" for char in vendor_id)):
                report = report | {"vendor_request_id": vendor_id}
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        failed_response = getattr(exc, "response", None)
        if isinstance(failed_response, httpx.Response) and failed_response.is_stream_consumed:
            report = report | {"raw_response_sha256": hashlib.sha256(
                failed_response.content).hexdigest()}
            report = report | _safe_provider_error(failed_response)
        report = report | {"status": "failed" if transport.network_attempted else "not_sent",
                           "error_category": "http_error" if type(status) is int else
                           "invalid_timeout_or_guard", "http_status": status if type(status) is int
                           else report.get("http_status")}
    made = transport.network_attempted
    unknown = made and report["settled_cost_usd"] is None
    return report | {"attempt": int(transport.claimed), "live_request_made": live and made,
                     "latency_ms": round((perf_counter() - started) * 1000),
                     "slot_consumed": transport.ledger_path.exists(),
                     "network_attempted": made,
                     "uncertain_cost_usd": str(reservation.reservation_usd) if unknown else
                     report["uncertain_cost_usd"]}
