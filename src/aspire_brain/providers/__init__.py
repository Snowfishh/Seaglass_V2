"""Providers explain permitted evidence; they cannot supply business decisions.

The default provider stays ``offline_extractive``. ``fake_grounded`` is a deterministic local
provider used to exercise the G4 grounding checks; it is not a language model. A live runtime
is only reachable through explicit enablement *and* confirmed entitlement, and this checkout
implements none, so no outbound request is ever made.
"""

from typing import Protocol

from pydantic import Field

from aspire_brain.models import Evidence, StrictModel
from aspire_brain.providers.runtime import (
    ProviderRuntimeConfig,
    ProviderRuntimeRecord,
    local_runtime_record,
    runtime_record_for,
)

#: Modes that run entirely on this machine and make no network request.
LOCAL_PROVIDER_MODES = frozenset({"offline_extractive", "fake_grounded"})
#: Modes that would contact a real runtime and therefore need entitlement.
LIVE_PROVIDER_MODES = frozenset({"live_grounded"})

#: The maximum answer length the provider contract accepts. Providers compose their answer
#: within this bound so a maximum-size evidence set cannot produce a validation error.
ANSWER_LIMIT = 16000


class ProviderInput(StrictModel):
    question: str
    context: dict
    evidence: list[Evidence]
    decision_summary: str


class ProviderOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=ANSWER_LIMIT)
    citation_ids: list[str] = Field(max_length=50)


def fit_blocks(blocks, limit: int = ANSWER_LIMIT) -> list[str]:
    """Keep whole blocks that fit inside ``limit``, never splitting one mid-line.

    A partial final block is dropped rather than truncated so every emitted quotation stays a
    complete, verifiable span of its cited source. If not even the first block fits, that one
    block is clipped on a word boundary and remains a leading span.
    """
    kept: list[str] = []
    used = 0
    for block in blocks:
        cost = len(block) + (2 if kept else 0)
        if used + cost > limit:
            if not kept:
                clipped = block[:max(limit, 0)]
                cut = clipped.rfind(" ")
                kept.append(clipped[:cut] if cut > 0 else clipped)
            break
        kept.append(block)
        used += cost
    return kept


class AnswerProvider(Protocol):
    mode: str

    async def generate(self, context: ProviderInput) -> ProviderOutput: ...


class OfflineExtractiveProvider:
    mode = "offline_extractive"

    async def generate(self, context: ProviderInput) -> ProviderOutput:
        answer = context.decision_summary
        blocks = [f"Evidence ({item.source_locator}): {item.text}" for item in context.evidence]
        quoted = fit_blocks(blocks, ANSWER_LIMIT - len(answer) - 2)
        if quoted:
            answer = f"{answer}\n\n" + "\n\n".join(quoted)
        else:
            answer += " No relevant readable passages were found."
        return ProviderOutput(answer=answer, citation_ids=[e.chunk_id for e in context.evidence])

    def runtime_record(self) -> ProviderRuntimeRecord:
        return local_runtime_record(self.mode)


class ExternalProviderUnavailable(RuntimeError):
    pass


class ProviderEntitlementError(ExternalProviderUnavailable):
    """A live provider was requested without explicit enablement or confirmed entitlement."""


def configured_provider(mode: str, *,
                        runtime: ProviderRuntimeConfig | None = None) -> AnswerProvider:
    """Build the configured provider, refusing anything that is not explicitly allowed."""
    if mode == "offline_extractive":
        return OfflineExtractiveProvider()
    if mode == "fake_grounded":
        from aspire_brain.providers.grounded import GroundedAnswerProvider

        return GroundedAnswerProvider()
    if mode in LIVE_PROVIDER_MODES:
        from aspire_brain.providers.grounded import require_entitled_runtime

        require_entitled_runtime(runtime)
        raise ExternalProviderUnavailable(
            "No entitled live runtime is implemented in this checkout; no request was made")
    raise ExternalProviderUnavailable(
        "External provider is not implemented or live-verified in this checkout; "
        "select offline_extractive or fake_grounded")


__all__ = [
    "ANSWER_LIMIT",
    "AnswerProvider",
    "ExternalProviderUnavailable",
    "LIVE_PROVIDER_MODES",
    "LOCAL_PROVIDER_MODES",
    "OfflineExtractiveProvider",
    "ProviderEntitlementError",
    "ProviderInput",
    "ProviderOutput",
    "ProviderRuntimeConfig",
    "ProviderRuntimeRecord",
    "configured_provider",
    "fit_blocks",
    "local_runtime_record",
    "runtime_record_for",
]
