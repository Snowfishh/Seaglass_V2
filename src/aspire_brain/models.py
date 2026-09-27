"""Strict public and provider contracts; money is decimal, never binary float."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ScopeText = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


class CaseContext(StrictModel):
    workflow_id: Literal["general", "contractor_travel"] = "general"
    case_date: date | None = None
    jurisdiction: Annotated[str, Field(pattern=r"^[A-Z]{2}$")] | None = None
    worker_type: Literal["contractor", "employee"] | None = None
    project: ScopeText | None = None
    cost_centre: ScopeText | None = None
    expense_amount: Annotated[Decimal, Field(ge=0, le=Decimal("999999999.99"),
                                           max_digits=11, decimal_places=2)] | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None

    @field_validator("expense_amount", mode="before")
    @classmethod
    def exact_money(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, Decimal))):
            raise ValueError("Money must be an exact decimal string or integer")
        return value

    @field_validator("case_date", mode="before")
    @classmethod
    def business_date(cls, value):
        if value is not None and not isinstance(value, (str, date)):
            raise ValueError("Use an ISO business date")
        if isinstance(value, str) and (len(value) != 10 or value[4] != "-" or value[7] != "-"):
            raise ValueError("Use YYYY-MM-DD")
        return value


class QueryRequest(StrictModel):
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    context: CaseContext = Field(default_factory=CaseContext)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Enter a question")
        return value.strip()


class Evidence(StrictModel):
    version_id: str
    chunk_id: str
    text: str
    source_locator: str
    content_hash: str
    document_id: str


class Citation(StrictModel):
    document_version_id: str
    chunk_id: str
    source_locator: str
    safe_excerpt: str
    source_url: str


class EvidencePacket(StrictModel):
    request_id: str
    query_status: Literal["answered", "needs_review", "insufficient_evidence"]
    case_outcome: Literal["within_documented_limits", "exceeds_documented_limits",
                          "undetermined", "not_applicable"]
    answer: str
    case_date: date | None
    citations: list[Citation]
    applied_rules: list[dict]
    conflicts: list[dict]
    missing_evidence_categories: list[str]
    review_route: str
    provider_mode: str
    retrieval_mode: str
    configuration: dict
    #: The source-derived claim-support report that gated this release. It carries a
    #: denominator and a ``simulated``/``live`` label; ``exact_cited_span`` is bounded
    #: extractive support, not entailment or truth verification.
    claim_support: dict
    scope_notice: str
    audit_event_id: str
