"""Minimised, non-secret runtime records for an answer provider (G4).

A local provider makes no outbound request, so its record is ``simulated`` with a
``not_run`` outcome and every external field null. A live runtime is only reachable through
:class:`ProviderRuntimeConfig` with explicit enablement *and* confirmed entitlement, and its
record names the service, model, endpoint **host**, region, cost and any failure — never a
credential, prompt or response body.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from aspire_brain.models import StrictModel

RuntimeMode = Literal["simulated", "live"]
RequestOutcome = Literal["not_run", "succeeded", "failed", "timeout", "refused_not_entitled"]
Entitlement = Literal["unknown", "entitled", "not_entitled"]


class ProviderRuntimeConfig(StrictModel):
    """Explicit, credential-free configuration for a live provider runtime.

    The endpoint is stored as a bare HTTPS URL. Credentials, query strings and fragments are
    rejected, so an API key cannot be smuggled into the configuration or a report.
    """

    service: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=512)
    region: str = Field(min_length=1, max_length=64)
    enabled: bool = False
    entitlement: Entitlement = "unknown"
    max_cost_usd: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1000"))
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @field_validator("endpoint")
    @classmethod
    def bare_https_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Provider endpoint must be a bare HTTPS URL without credentials")
        return value

    @property
    def endpoint_host(self) -> str:
        return urlsplit(self.endpoint).hostname or ""

    def is_entitled(self) -> bool:
        return bool(self.enabled and self.entitlement == "entitled")


class ProviderRuntimeRecord(StrictModel):
    """What a provider request actually used. Unmeasured fields stay null."""

    mode: RuntimeMode
    provider_mode: str = Field(max_length=64)
    outcome: RequestOutcome
    live_request_made: bool
    service: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    endpoint_host: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=64)
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    error_category: str | None = Field(default=None, max_length=64)


def local_runtime_record(provider_mode: str) -> ProviderRuntimeRecord:
    """A local provider never contacts a service, so nothing is measured."""
    return ProviderRuntimeRecord(mode="simulated", provider_mode=provider_mode,
                                 outcome="not_run", live_request_made=False)


def live_runtime_record(config: ProviderRuntimeConfig, *, outcome: RequestOutcome,
                        cost_usd: Decimal | None = None, latency_ms: int | None = None,
                        error_category: str | None = None) -> ProviderRuntimeRecord:
    return ProviderRuntimeRecord(
        mode="live", provider_mode="live_grounded", outcome=outcome,
        live_request_made=outcome in {"succeeded", "failed", "timeout"},
        service=config.service, model=config.model, endpoint_host=config.endpoint_host,
        region=config.region, cost_usd=cost_usd, latency_ms=latency_ms,
        error_category=error_category)


def runtime_record_for(provider) -> ProviderRuntimeRecord:
    """Return a provider's own record, or a conservative ``not_run`` record if it has none."""
    supplied = getattr(provider, "runtime_record", None)
    if callable(supplied):
        record = supplied()
        return record if isinstance(record, ProviderRuntimeRecord) else \
            ProviderRuntimeRecord.model_validate(record)
    return local_runtime_record(getattr(provider, "mode", "unknown"))
