"""A grounded answer provider that reasons only over the evidence it is handed (G4).

This provider exists to exercise the G4 provider interface and the claim-support evaluation
without contacting a network. It is **not** a language model and its mode is
``fake_grounded``: it composes one sentence per permitted evidence item, quoting only text it
received, and it can only cite the identifiers it was given. A result produced here is a
deterministic simulated result, never a live-model result.

A live runtime is deliberately unreachable in this checkout. :func:`require_entitled_runtime`
demands explicit enablement *and* confirmed entitlement, and even then the factory refuses
because no live transport is implemented, so no request and no spend can occur.
"""

from __future__ import annotations

from aspire_brain.providers import ANSWER_LIMIT, ProviderInput, ProviderOutput, fit_blocks
from aspire_brain.providers.runtime import ProviderRuntimeConfig
from aspire_brain.providers.segments import source_sentences

_QUOTE_LIMIT = 400


def _quote(text: str) -> str:
    """The leading complete sentences of the evidence text, about ``_QUOTE_LIMIT`` long.

    Whole structural sentences keep every emitted token inside the cited evidence and on a
    sentence boundary, so the grounding check can verify each claim instead of trusting it.
    The first sentence is always kept whole, even when it alone exceeds the limit.
    """
    kept, used = [], 0
    for sentence in source_sentences(text):
        if kept and used + len(sentence) > _QUOTE_LIMIT:
            break
        kept.append(sentence)
        used += len(sentence) + 2
    return "\n\n".join(kept)


class GroundedAnswerProvider:
    """Deterministic local provider over already-bounded, already-permitted evidence."""

    mode = "fake_grounded"

    async def generate(self, context: ProviderInput) -> ProviderOutput:
        answer = context.decision_summary
        blocks = [f"From {item.source_locator}: {_quote(item.text)}" for item in context.evidence]
        quoted = fit_blocks(blocks, ANSWER_LIMIT - len(answer) - 1)
        if quoted:
            answer = f"{answer}\n" + "\n".join(quoted)
        else:
            answer += " No relevant readable passages were found."
        # Only identifiers this call received; the service re-validates them before release.
        return ProviderOutput(answer=answer,
                              citation_ids=[item.chunk_id for item in context.evidence])


def require_entitled_runtime(runtime: ProviderRuntimeConfig | None) -> ProviderRuntimeConfig:
    """Refuse a live provider unless it was explicitly enabled and entitlement is confirmed."""
    from aspire_brain.providers import ProviderEntitlementError

    if runtime is None:
        raise ProviderEntitlementError(
            "A live provider needs explicit runtime configuration; none was supplied")
    if not runtime.enabled:
        raise ProviderEntitlementError("A live provider must be explicitly enabled")
    if runtime.entitlement != "entitled":
        raise ProviderEntitlementError("Live provider entitlement is not confirmed")
    return runtime
