"""Credential-free runtime metadata and pure, offline budget calculations.

Readiness is a configuration check, never permission to dispatch. Reservations and
settlements are immutable calculations, not an atomic budget ledger or vendor bills.
"""

from __future__ import annotations

from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BeforeValidator, Field

from aspire_brain.models import StrictModel

RuntimeMode = Literal["simulated", "live"]
RequestOutcome = Literal["not_run", "succeeded", "failed", "timeout", "cancelled", "refused_not_entitled"]
Entitlement = Literal["unknown", "entitled", "not_entitled"]
DispatchState = Literal["not_sent", "intent", "possibly_sent", "response_received", "released"]
ReasoningEffort = Literal["low", "medium", "high"]
#: Outcome of an injected offline fake client. Never a live request outcome.
SimulatedOutcome = Literal["succeeded", "failed", "timeout", "cancelled"]

#: The single reviewed target identity. ``openai/`` is model provenance, not an API destination.
SUPPORTED_TARGET_SERVICE = "groq"
SUPPORTED_TARGET_MODEL = "openai/gpt-oss-20b"
SUPPORTED_TARGET_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def _exact_usd(value):
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValueError("USD must be an exact decimal string, integer or Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("USD must be a finite nonnegative decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("USD must be a finite nonnegative decimal")
    return result


def _timeout(value):
    if isinstance(value, bool):
        raise ValueError("Timeout must be an explicit positive number")
    return value


def _bare_https(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or "?" in value or "#" in value
            or any(character.isspace() or ord(character) < 32 for character in value)):
        raise ValueError("Provider endpoint must be a bare HTTPS URL without credentials")
    return value


ExactUSD = Annotated[Decimal, BeforeValidator(_exact_usd)]
TokenCount = Annotated[int, Field(strict=True, ge=0)]


class ProviderRuntimeConfig(StrictModel):
    """Generic non-secret configuration; unset and zero budgets deny target readiness."""

    service: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    endpoint: Annotated[str, BeforeValidator(_bare_https)] = Field(min_length=1, max_length=512)
    region: str | None = Field(default=None, min_length=1, max_length=64)
    region_provenance: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool = False
    entitlement: Entitlement = "unknown"
    max_cost_usd: ExactUSD = Field(default=Decimal("0"), le=Decimal("1000"))
    timeout_seconds: Annotated[float, BeforeValidator(_timeout)] | None = Field(
        default=None, gt=0, le=60, allow_inf_nan=False)
    request_cap: TokenCount | None = None
    input_token_cap: TokenCount | None = None
    output_token_cap: TokenCount | None = None
    reasoning_token_cap: TokenCount | None = None
    total_token_cap: TokenCount | None = None
    reasoning_effort: ReasoningEffort | None = None

    @property
    def endpoint_host(self) -> str:
        return urlsplit(self.endpoint).hostname or ""

    def is_entitled(self) -> bool:
        """Legacy flag check only; not target readiness or dispatch authorization."""
        return bool(self.enabled and self.entitlement == "entitled")

    def require_target_envelope(self) -> None:
        """Require the exact target identity and a complete numeric envelope.

        This is a configuration-completeness check for the offline fake path. It authorizes
        nothing, and deliberately does not depend on ``enabled``/``entitlement``: those are
        live-readiness flags, and live dispatch still needs its own separate authorization.
        """
        if (self.service != SUPPORTED_TARGET_SERVICE or self.model != SUPPORTED_TARGET_MODEL
                or self.endpoint != SUPPORTED_TARGET_ENDPOINT):
            raise ValueError("Configuration does not identify the exact supported target")
        caps = (self.request_cap, self.input_token_cap, self.output_token_cap,
                self.reasoning_token_cap, self.total_token_cap)
        if any(value is None or value <= 0 for value in caps):
            raise ValueError("Every request and token cap must be explicitly positive")
        if self.timeout_seconds is None or self.max_cost_usd <= 0 or self.reasoning_effort is None:
            raise ValueError("Timeout, positive exact USD cap and reasoning effort must be explicit")
        if self.input_token_cap + self.output_token_cap + self.reasoning_token_cap > self.total_token_cap:
            raise ValueError("Total token cap cannot cover a full-cap request")

    def require_target_ready(self) -> None:
        """Live readiness: the complete envelope plus explicit enablement and entitlement.

        The flags remain necessary and are never sufficient; a bound dispatch authorization is
        still required before anything could be sent.
        """
        self.require_target_envelope()
        if not self.is_entitled():
            raise ValueError("Explicit enablement and entitlement are necessary, not authorization")


class ProviderTokenUsage(StrictModel):
    """Unknown usage is null, not a measured zero."""

    input_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None
    reasoning_tokens: TokenCount | None = None


class ProviderRuntimeRecord(ProviderTokenUsage):
    """Request-local metadata only: no prompt, response body or credentials."""

    mode: RuntimeMode
    provider_mode: str = Field(max_length=64)
    outcome: RequestOutcome
    live_request_made: bool
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    service: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    requested_model: str | None = Field(default=None, max_length=128)
    reported_model: str | None = Field(default=None, max_length=128)
    endpoint_host: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=64)
    region_provenance: str | None = Field(default=None, max_length=128)
    vendor_request_id: str | None = Field(default=None, max_length=128)
    attempt: TokenCount = 0
    dispatch_state: DispatchState = "not_sent"
    manifest_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    simulated_outcome: SimulatedOutcome | None = None
    reservation_usd: ExactUSD | None = None
    settled_cost_usd: ExactUSD | None = None
    uncertain_cost_usd: ExactUSD | None = None
    uncertainty_reason: str | None = Field(default=None, max_length=128)
    cost_usd: ExactUSD | None = None
    latency_ms: TokenCount | None = None
    error_category: str | None = Field(default=None, max_length=64)


def local_runtime_record(provider_mode: str, correlation_id: str | None = None) -> ProviderRuntimeRecord:
    """Construct a fresh local record, leaving every unmeasured external field null."""
    return ProviderRuntimeRecord(mode="simulated", provider_mode=provider_mode,
                                 outcome="not_run", live_request_made=False,
                                 correlation_id=correlation_id)


def live_runtime_record(config: ProviderRuntimeConfig, *, outcome: RequestOutcome,
                        cost_usd: Decimal | None = None, latency_ms: int | None = None,
                        error_category: str | None = None, correlation_id: str | None = None,
                        reported_model: str | None = None,
                        vendor_request_id: str | None = None) -> ProviderRuntimeRecord:
    """Compatibility metadata constructor; performs no transport or authorization."""
    made_request = outcome in {"succeeded", "failed", "timeout", "cancelled"}
    dispatch_state = ("response_received" if outcome == "succeeded" else
                      "possibly_sent" if made_request else "not_sent")
    return ProviderRuntimeRecord(
        mode="live", provider_mode="live_grounded", outcome=outcome,
        live_request_made=made_request, correlation_id=correlation_id,
        service=config.service, model=config.model, requested_model=config.model,
        reported_model=reported_model, endpoint_host=config.endpoint_host,
        region=config.region, region_provenance=config.region_provenance,
        vendor_request_id=vendor_request_id, attempt=1 if made_request else 0,
        dispatch_state=dispatch_state, cost_usd=cost_usd, latency_ms=latency_ms,
        error_category=error_category)


def runtime_record_for(provider, correlation_id: str | None = None) -> ProviderRuntimeRecord:
    """Never inspect provider-owned last-call callbacks or shared mutable records."""
    return local_runtime_record(getattr(provider, "mode", "unknown"), correlation_id)


class ProviderRateCard(StrictModel):
    """Explicit accounting inputs, not a claim about current vendor prices."""

    input_usd_per_million: ExactUSD
    output_usd_per_million: ExactUSD
    reasoning_usd_per_million: ExactUSD


class ProviderBudgetReservation(StrictModel):
    """Full input, output and reasoning caps reserved for a batch of requests."""

    request_count: Annotated[int, Field(strict=True, gt=0)]
    input_tokens: TokenCount
    output_tokens: TokenCount
    reasoning_tokens: TokenCount
    total_tokens: TokenCount
    reservation_usd: ExactUSD
    rates: ProviderRateCard


class ProviderBudgetSettlement(StrictModel):
    """Conservative cost accounting; never evidence of an actual vendor charge."""

    reservation_usd: ExactUSD
    settled_cost_usd: ExactUSD | None = None
    uncertain_cost_usd: ExactUSD
    uncertainty_reason: str | None = Field(default=None, max_length=128)
    cost_provenance: Literal["usage_rate_calculation_not_vendor_bill", "reservation_not_vendor_bill"]


def _usage_cost(input_tokens: int, output_tokens: int, reasoning_tokens: int,
                rates: ProviderRateCard) -> Decimal:
    counts = (input_tokens, output_tokens, reasoning_tokens)
    prices = (rates.input_usd_per_million, rates.output_usd_per_million,
              rates.reasoning_usd_per_million)
    # Include exponent span and integer multiplication to avoid ambient-context rounding.
    precision = max(28, max(price.adjusted() for price in prices)
                    - min(price.as_tuple().exponent for price in prices)
                    + max(len(str(count)) for count in counts) + 8)
    with localcontext(Context(prec=precision)):
        return sum((Decimal(count) * price for count, price in zip(counts, prices)),
                   Decimal("0")) / Decimal("1000000")


def reserve_budget(config: ProviderRuntimeConfig, rates: ProviderRateCard, *,
                   request_count: int = 1) -> ProviderBudgetReservation:
    """Calculate a full-cap reservation; no counters, dispatch or atomic enforcement."""
    config.require_target_ready()
    if type(request_count) is not int or request_count <= 0 or request_count > config.request_cap:
        raise ValueError("Request count must be a positive integer within its cap")
    input_tokens = config.input_token_cap * request_count
    output_tokens = config.output_token_cap * request_count
    reasoning_tokens = config.reasoning_token_cap * request_count
    total_tokens = input_tokens + output_tokens + reasoning_tokens
    if total_tokens > config.total_token_cap:
        raise ValueError("Full-cap reservation exceeds the total token cap")
    cost = _usage_cost(input_tokens, output_tokens, reasoning_tokens, rates)
    if cost > config.max_cost_usd:
        raise ValueError("Full-cap reservation exceeds the exact USD cap")
    return ProviderBudgetReservation(request_count=request_count, input_tokens=input_tokens,
                                     output_tokens=output_tokens, reasoning_tokens=reasoning_tokens,
                                     total_tokens=total_tokens, reservation_usd=cost, rates=rates)


def settle_budget(reservation: ProviderBudgetReservation, rates: ProviderRateCard, *,
                  usage: ProviderTokenUsage | None = None,
                  outcome: str = "unknown") -> ProviderBudgetSettlement:
    """Unknown usage or outcomes retain the full reservation as uncertain cost."""
    if rates != reservation.rates:
        raise ValueError("Settlement must use the reserved rate card")
    reason = None
    if outcome != "succeeded":
        reason = outcome
    elif usage is None or any(value is None for value in (
            usage.input_tokens, usage.output_tokens, usage.reasoning_tokens)):
        reason = "unknown_usage"
    elif (usage.input_tokens > reservation.input_tokens
          or usage.output_tokens > reservation.output_tokens
          or usage.reasoning_tokens > reservation.reasoning_tokens):
        reason = "usage_exceeds_reservation"
    if reason is not None:
        return ProviderBudgetSettlement(
            reservation_usd=reservation.reservation_usd,
            uncertain_cost_usd=reservation.reservation_usd, uncertainty_reason=reason,
            cost_provenance="reservation_not_vendor_bill")
    return ProviderBudgetSettlement(
        reservation_usd=reservation.reservation_usd,
        settled_cost_usd=_usage_cost(usage.input_tokens, usage.output_tokens,
                                    usage.reasoning_tokens, rates),
        uncertain_cost_usd=Decimal("0"), cost_provenance="usage_rate_calculation_not_vendor_bill")
