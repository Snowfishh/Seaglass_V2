"""Explicit retention for protected audit payloads (G4).

Retention applies to the **encrypted payload** only. The HMAC chain is never truncated, so a
removed payload leaves a verifiable chain plus an explicit retention record — an officer can
tell an expired record from a tampered one, and the chain's unanchored tail still is not a
completeness proof.
"""

from pydantic import Field

from aspire_brain.models import StrictModel

DEFAULT_BASIS = (
    "Protected case payloads are kept for the declared window and entry count. Retention "
    "removes only the encrypted payload; the HMAC audit chain is never truncated."
)

RETENTION_NOTE = (
    "Retention removes only the encrypted payload and records why. The HMAC chain, including "
    "its unanchored tail, is unchanged, so retention does not make the chain a completeness "
    "proof and does not weaken tamper detection."
)


class RetentionPolicy(StrictModel):
    """A declared window and entry cap for protected audit payloads."""

    max_age_days: int = Field(ge=1, le=3650)
    max_entries: int = Field(ge=1, le=100000)
    basis: str = Field(default=DEFAULT_BASIS, min_length=1, max_length=300)
