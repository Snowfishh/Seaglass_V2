"""Providers explain permitted evidence; they cannot supply business decisions."""

from typing import Protocol

from pydantic import Field

from aspire_brain.models import Evidence, StrictModel


class ProviderInput(StrictModel):
    question: str
    context: dict
    evidence: list[Evidence]
    decision_summary: str


class ProviderOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=16000)
    citation_ids: list[str] = Field(max_length=50)


class AnswerProvider(Protocol):
    mode: str

    async def generate(self, context: ProviderInput) -> ProviderOutput: ...


class OfflineExtractiveProvider:
    mode = "offline_extractive"

    async def generate(self, context: ProviderInput) -> ProviderOutput:
        quotes = "\n\n".join(f"Evidence ({item.source_locator}): {item.text}"
                              for item in context.evidence)
        answer = context.decision_summary
        if quotes:
            answer += "\n\n" + quotes
        else:
            answer += " No relevant readable passages were found."
        return ProviderOutput(answer=answer, citation_ids=[e.chunk_id for e in context.evidence])


class ExternalProviderUnavailable(RuntimeError):
    pass


def configured_provider(mode: str) -> AnswerProvider:
    if mode == "offline_extractive":
        return OfflineExtractiveProvider()
    raise ExternalProviderUnavailable(
        "External provider is not implemented or live-verified in P0; select offline_extractive"
    )
