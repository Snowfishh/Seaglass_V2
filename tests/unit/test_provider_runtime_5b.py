"""Offline Stage 5B runtime metadata, configuration and pure accounting contracts."""

from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from aspire_brain import config as settings
from aspire_brain.providers import runtime

TARGET = {
    "service": "groq",
    "model": "openai/gpt-oss-20b",
    "endpoint": "https://api.groq.com/openai/v1/chat/completions",
}


def ready_config(**changes):
    values = dict(TARGET, enabled=True, entitlement="entitled", request_cap=2,
                  input_token_cap=100, output_token_cap=40, reasoning_token_cap=60,
                  total_token_cap=400, max_cost_usd="0.001", timeout_seconds=5,
                  reasoning_effort="low")
    values.update(changes)
    return runtime.ProviderRuntimeConfig(**values)


def rates(**changes):
    values = dict(input_usd_per_million="0.10", output_usd_per_million="0.30",
                  reasoning_usd_per_million="0.30")
    values.update(changes)
    return runtime.ProviderRateCard(**values)


def test_legacy_configuration_still_constructs_but_defaults_deny_readiness():
    config = runtime.ProviderRuntimeConfig(service="example", model="example-model",
                                          endpoint="https://host.invalid/v1", region="example")
    assert config.timeout_seconds is None
    assert config.max_cost_usd == Decimal("0")
    assert config.request_cap is None
    assert config.reasoning_effort is None
    with pytest.raises(ValueError):
        config.require_target_ready()


def test_flags_alone_are_never_sufficient_readiness_or_authorization():
    config = runtime.ProviderRuntimeConfig(**TARGET, enabled=True, entitlement="entitled")
    assert config.is_entitled()
    with pytest.raises(ValueError):
        config.require_target_ready()
    assert ready_config().require_target_ready() is None


@pytest.mark.parametrize("field", ["request_cap", "input_token_cap", "output_token_cap",
                                  "reasoning_token_cap", "total_token_cap"])
@pytest.mark.parametrize("value", [None, 0])
def test_unset_and_zero_caps_deny_readiness(field, value):
    with pytest.raises(ValueError):
        ready_config(**{field: value}).require_target_ready()


@pytest.mark.parametrize("value", [True, False, 1.0, "1", -1])
@pytest.mark.parametrize("field", ["request_cap", "input_token_cap", "output_token_cap",
                                  "reasoning_token_cap", "total_token_cap"])
def test_caps_are_strict_nonnegative_integers(field, value):
    with pytest.raises(ValidationError):
        ready_config(**{field: value})


@pytest.mark.parametrize("changes", [
    {"service": "Groq"}, {"model": "openai/gpt-oss-120b"},
    {"endpoint": "https://api.groq.com/openai/v1/chat/completions/"},
    {"endpoint": "https://api.groq.com:443/openai/v1/chat/completions"},
    {"endpoint": "https://other.invalid/openai/v1/chat/completions"},
    {"timeout_seconds": None}, {"max_cost_usd": "0"}, {"reasoning_effort": None},
    {"total_token_cap": 199}, {"enabled": False}, {"entitlement": "unknown"},
])
def test_target_readiness_requires_exact_target_and_complete_envelope(changes):
    with pytest.raises(ValueError):
        ready_config(**changes).require_target_ready()


@pytest.mark.parametrize("endpoint", ["http://host.invalid", "https://user:pass@host.invalid",
                                      "https://@host.invalid", "https://host.invalid?",
                                      "https://host.invalid#", "https://host.invalid?key=value",
                                      "https://host.invalid/#fragment", "https://host.invalid\n/path"])
def test_constructor_rejects_nonbare_or_credential_bearing_urls(endpoint):
    with pytest.raises(ValidationError):
        ready_config(endpoint=endpoint)


@pytest.mark.parametrize("value", [True, 0.1, float("inf"), "NaN", "Infinity", Decimal("-Infinity"), "-1"])
def test_cost_cap_requires_finite_exact_nonnegative_decimal(value):
    with pytest.raises(ValidationError):
        ready_config(max_cost_usd=value)


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf")])
def test_timeout_is_explicit_finite_and_positive(value):
    with pytest.raises(ValidationError):
        ready_config(timeout_seconds=value)


def test_nullable_region_and_explicit_provenance_are_not_inferred_from_host():
    config = ready_config()
    assert config.region is None and config.region_provenance is None
    record = runtime.live_runtime_record(config, outcome="not_run")
    assert record.region is None and record.region_provenance is None
    assert record.requested_model == TARGET["model"]
    assert record.reported_model is None and record.vendor_request_id is None
    assert record.live_request_made is False
    assert record.dispatch_state == "not_sent"
    configured = ready_config(region="declared-region", region_provenance="operator_configuration")
    record = runtime.live_runtime_record(configured, outcome="not_run")
    assert record.region == "declared-region"
    assert record.region_provenance == "operator_configuration"


def test_legacy_call_signature_does_not_reuse_shared_runtime_state():
    provider = SimpleNamespace(mode="fake_grounded", runtime_record=lambda: pytest.fail(
        "Do not call a provider-owned mutable runtime callback"))
    assert runtime.runtime_record_for(provider).outcome == "not_run"


def test_runtime_record_never_reads_mutable_provider_last_call_callback():
    class Provider:
        mode = "fake_grounded"

        @property
        def runtime_record(self):
            raise AssertionError("Shared last-call state must not even be read")

    first = runtime.runtime_record_for(Provider(), "request-one")
    second = runtime.runtime_record_for(Provider(), "request-two")
    assert first is not second
    assert first.correlation_id == "request-one" and second.correlation_id == "request-two"
    for record in (first, second):
        assert record.mode == "simulated" and record.outcome == "not_run"
        assert record.live_request_made is False and record.dispatch_state == "not_sent"
        assert record.reservation_usd is None and record.settled_cost_usd is None
        assert record.uncertain_cost_usd is None and record.uncertainty_reason is None
        assert record.input_tokens is None and record.output_tokens is None
        assert record.reasoning_tokens is None and record.requested_model is None
        assert record.reported_model is None and record.vendor_request_id is None
        assert record.attempt == 0
    assert runtime.runtime_record_for(SimpleNamespace()).provider_mode == "unknown"
    assert runtime.local_runtime_record("offline_extractive").correlation_id is None


def test_runtime_record_json_keeps_exact_costs_and_nullable_unknowns():
    record = runtime.ProviderRuntimeRecord(
        mode="live", provider_mode="live_grounded", outcome="timeout", live_request_made=True,
        correlation_id="request-one", attempt=1, dispatch_state="possibly_sent",
        reservation_usd="0.000040", uncertain_cost_usd="0.000040",
        uncertainty_reason="timeout", requested_model=TARGET["model"],
    )
    data = record.model_dump(mode="json")
    assert data["reservation_usd"] == "0.000040"
    assert data["settled_cost_usd"] is None and data["input_tokens"] is None
    assert runtime.ProviderRuntimeRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("changes", [{"attempt": True}, {"attempt": -1}, {"input_tokens": True},
                                      {"output_tokens": -1}, {"reasoning_tokens": 1.5},
                                      {"settled_cost_usd": 0.01}, {"uncertain_cost_usd": "NaN"}])
def test_record_rejects_ambiguous_accounting_values(changes):
    with pytest.raises(ValidationError):
        runtime.ProviderRuntimeRecord(mode="simulated", provider_mode="local", outcome="not_run",
                                      live_request_made=False, **changes)


def test_runtime_values_roundtrip_uses_only_supplied_mapping(monkeypatch):
    monkeypatch.setenv("ASPIRE_PROVIDER_MAX_COST_USD", "999")
    monkeypatch.setattr(settings, "dotenv_values", lambda *_: pytest.fail("Must not read dotenv"))
    config = ready_config(region="declared-region", region_provenance="operator_configuration")
    values = settings.provider_runtime_values(config)
    assert all(isinstance(value, str) for value in values.values())
    assert values["ASPIRE_PROVIDER_MAX_COST_USD"] == "0.001"
    assert values["ASPIRE_PROVIDER_REQUEST_CAP"] == "2"
    assert settings._provider_runtime(values) == config
    assert settings._provider_runtime({}) is None
    minimal = runtime.ProviderRuntimeConfig(**TARGET)
    assert settings._provider_runtime(settings.provider_runtime_values(minimal)) == minimal


@pytest.mark.parametrize("field,value", [("ASPIRE_PROVIDER_REQUEST_CAP", "1.0"),
                                        ("ASPIRE_PROVIDER_REQUEST_CAP", True),
                                        ("ASPIRE_PROVIDER_REQUEST_CAP", "-1"),
                                        ("ASPIRE_PROVIDER_MAX_COST_USD", 0.1),
                                        ("ASPIRE_PROVIDER_TIMEOUT_SECONDS", True)])
def test_explicit_mapping_rejects_ambiguous_numeric_input(field, value):
    values = {"ASPIRE_PROVIDER_SERVICE": "groq", field: value}
    with pytest.raises((ValueError, settings.ConfigurationError)):
        settings._provider_runtime(values)


def test_full_cap_reservation_is_conservative_exact_and_immutable():
    reservation = runtime.reserve_budget(ready_config(), rates(), request_count=2)
    assert reservation.request_count == 2
    assert reservation.input_tokens == 200
    assert reservation.output_tokens == 80
    assert reservation.reasoning_tokens == 120
    assert reservation.total_tokens == 400
    assert reservation.reservation_usd == Decimal("0.000080")
    with pytest.raises(ValidationError):
        reservation.request_count = 9
    assert runtime.reserve_budget(ready_config(), rates(), request_count=2) == reservation


def test_decimal_calculation_does_not_depend_on_ambient_precision():
    with localcontext() as context:
        context.prec = 2
        reservation = runtime.reserve_budget(ready_config(), rates(input_usd_per_million="0.123456789"))
    assert reservation.reservation_usd == Decimal("0.0000423456789")


@pytest.mark.parametrize("changes,count", [({}, 0), ({}, True), ({}, 1.0), ({}, 3),
                                          ({"total_token_cap": 399}, 2),
                                          ({"max_cost_usd": "0.000079"}, 2)])
def test_reservation_rejects_request_total_and_cost_overflow(changes, count):
    with pytest.raises(ValueError):
        runtime.reserve_budget(ready_config(**changes), rates(), request_count=count)


@pytest.mark.parametrize("value", [0.1, True, "NaN", "Infinity", "-1"])
def test_rate_card_rejects_inexact_or_invalid_rates(value):
    with pytest.raises(ValidationError):
        rates(input_usd_per_million=value)


def test_settlement_keeps_known_usage_distinct_from_real_vendor_billing():
    reservation = runtime.reserve_budget(ready_config(), rates())
    usage = runtime.ProviderTokenUsage(input_tokens=50, output_tokens=10, reasoning_tokens=20)
    settlement = runtime.settle_budget(reservation, rates(), usage=usage, outcome="succeeded")
    assert settlement.reservation_usd == Decimal("0.000040")
    assert settlement.settled_cost_usd == Decimal("0.000014")
    assert settlement.uncertain_cost_usd == Decimal("0")
    assert settlement.uncertainty_reason is None
    assert settlement.cost_provenance == "usage_rate_calculation_not_vendor_bill"
    assert reservation.reservation_usd == Decimal("0.000040")


@pytest.mark.parametrize("outcome", ["unknown", "timeout", "cancelled", "failed"])
def test_uncertain_outcomes_retain_the_entire_reservation(outcome):
    reservation = runtime.reserve_budget(ready_config(), rates())
    usage = runtime.ProviderTokenUsage(input_tokens=0, output_tokens=0, reasoning_tokens=0)
    settlement = runtime.settle_budget(reservation, rates(), usage=usage, outcome=outcome)
    assert settlement.settled_cost_usd is None
    assert settlement.uncertain_cost_usd == reservation.reservation_usd
    assert settlement.uncertainty_reason == outcome
    assert settlement.cost_provenance == "reservation_not_vendor_bill"


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": 1, "output_tokens": 1},
                                   {"input_tokens": 101, "output_tokens": 1, "reasoning_tokens": 1}])
def test_unknown_or_out_of_envelope_usage_is_not_silently_zero_or_released(usage):
    reservation = runtime.reserve_budget(ready_config(), rates())
    parsed = runtime.ProviderTokenUsage(**usage) if usage is not None else None
    settlement = runtime.settle_budget(reservation, rates(), usage=parsed, outcome="succeeded")
    assert settlement.settled_cost_usd is None
    assert settlement.uncertain_cost_usd == reservation.reservation_usd
    assert settlement.uncertainty_reason in {"unknown_usage", "usage_exceeds_reservation"}


def test_explicit_zero_usage_is_calculated_but_never_called_free_or_a_bill():
    reservation = runtime.reserve_budget(ready_config(), rates())
    usage = runtime.ProviderTokenUsage(input_tokens=0, output_tokens=0, reasoning_tokens=0)
    settlement = runtime.settle_budget(reservation, rates(), usage=usage, outcome="succeeded")
    assert settlement.settled_cost_usd == Decimal("0")
    assert settlement.cost_provenance == "usage_rate_calculation_not_vendor_bill"


def test_settlement_cannot_substitute_a_different_rate_card():
    reservation = runtime.reserve_budget(ready_config(), rates())
    usage = runtime.ProviderTokenUsage(input_tokens=1, output_tokens=1, reasoning_tokens=1)
    with pytest.raises(ValueError):
        runtime.settle_budget(reservation, rates(input_usd_per_million="1"),
                              usage=usage, outcome="succeeded")
