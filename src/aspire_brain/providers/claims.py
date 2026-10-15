"""Claim-level support: is each asserted claim an exact span of the cited evidence? (G4)

Checking that a citation identifier exists is not enough — a provider can return a valid
identifier and still assert something the evidence never said. This module splits an answer
into claims and checks each claim against the cited evidence, so an unsupported claim fails
rather than passing on the strength of its citation.

The support contract is **bounded exact quotation**: a claim must equal a complete source
sentence, or the complete tail of that sentence after a colon followed by whitespace. Both
ends are therefore defined by source structure, rather than an arbitrary character substring.
Sentences follow the document's structure (paragraphs, headings, list items, hard line breaks
and table rows) as defined once in :mod:`aspire_brain.providers.segments`.
This deliberately refuses partial words, numbers, signed amounts, percentages, units and Unicode
sequences at quote edges, even when their characters occur inside the source. Complete quotations
keep their signs, currency, units and non-ASCII characters. The lexical token stream is diagnostic
only and never establishes support.

Exactly two normalisations are applied to both sides, and nothing else: runs of whitespace
collapse to a single space (trimmed), and case is folded with ``str.lower()``. No Unicode
compatibility folding is performed, so fullwidth and other look-alike characters stay distinct.

Two deliberate boundaries:

* Only the *source text* is compared. A locator or document identifier is not evidence for a
  factual assertion, so identifier tokens never make a claim supported.
* The service owns the citation label it prints in front of a quotation. A claim may carry one
  service-authored label — ``Evidence (<locator>): `` or ``From <locator>: `` — that names a
  cited source, and the remainder must still be an exact span of *that* source. A provider
  cannot use the label to smuggle content: the content after it is checked unchanged.

The method is bounded extractive support, not semantic entailment. A lexical-overlap figure is
still reported per claim, but only as a *diagnostic proxy* — it is never the release gate. Every
report carries a denominator and a ``simulated``/``live`` label, and a ``fake_grounded`` result
can never be labelled live.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from aspire_brain.models import StrictModel
from aspire_brain.providers.segments import comparable, source_sentences

#: Provider modes that run locally. A result from one of these is never a live-model result.
LOCAL_PROVIDER_MODES = frozenset({"offline_extractive", "fake_grounded"})

#: The support method this module implements. Reported so a reader never mistakes the result
#: for entailment.
SUPPORT_METHOD = "exact_cited_span"

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
#: Diagnostic token pattern. It is deliberately lossy and is **not** the support gate.
_TOKEN = re.compile(r"[a-z0-9]+")
#: A word character under Unicode rules. Used only to decide whether a claim has any checkable
#: content at all; a sentence with none fails closed rather than being waved through.
_WORD = re.compile(r"\w")

#: The service-owned citation labels a claim may carry in front of a quotation. The locator is
#: substituted at check time and must name a *cited* source for the label to be recognised.
CITATION_LABELS = ("evidence ({locator}): ", "from {locator}: ")

#: The provider contract caps an answer at 16,000 characters; a single claim can therefore be
#: that long, and this bound keeps validation from failing on a maximum-size answer.
MAX_CLAIM_CHARS = 20000

LIMITATION = (
    "Support is bounded exact quotation: a complete source sentence or its complete colon tail. "
    "That is bounded extractive support, not entailment, and it says nothing about an untested "
    "live model. The reported overlap ratio is a diagnostic proxy and is not the release gate."
)

ClaimReason = Literal["supported_by_exact_cited_span", "no_exact_cited_span",
                      "no_cited_evidence", "notice_excluded", "no_checkable_tokens"]


class ClaimSupport(StrictModel):
    claim: str = Field(min_length=1, max_length=MAX_CLAIM_CHARS)
    kind: Literal["claim", "notice"]
    supported: bool
    #: Diagnostic lexical overlap with the best-matching cited source. Reported for
    #: observability only; ``supported`` never depends on it.
    support_ratio: float = Field(ge=0.0, le=1.0)
    supporting_ids: list[str]
    reason: ClaimReason


class ClaimSupportReport(StrictModel):
    mode: Literal["simulated", "live"]
    provider_mode: str
    method: Literal["exact_cited_span"]
    denominator: int = Field(ge=0)
    supported_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    notices_excluded: int = Field(ge=0)
    all_supported: bool
    abstained: bool
    claims: list[ClaimSupport]
    limitation: str
    #: Always null here: only a live-model run could populate it, and none is implemented.
    live_model_claim_support: None = None


def split_claims(answer: str) -> list[str]:
    """Split an answer into sentences, deterministically and without a model."""
    if not isinstance(answer, str):
        raise ValueError("Answer must be text")
    return [part.strip() for part in _SENTENCE.split(answer) if part and part.strip()]



def _answer_claims(answer: str) -> list[str]:
    """Split each labelled block into the same structural units a source is split into.

    Labels still confer no support: each body must pass the same cited-source quotation check.
    A new labelled block is structural formatting, so unrelated evidence is never concatenated,
    and soft line wraps inside a block are whitespace, exactly as they are in a source.
    """
    blocks = re.split(r"\n+(?=(?:Evidence \(|From ))", answer, flags=re.IGNORECASE)
    return [claim for block in blocks for claim in source_sentences(block)]


def _tokens(text: str) -> list[str]:
    """Ordered word tokens.

    Stopwords are deliberately **kept**: removing them would erase negation ("not") and
    change an entity relationship, which is exactly what the support check must preserve.
    """
    return _TOKEN.findall(text.lower())


def _normalise(text: str) -> str:
    """The only normalisation applied before comparison: whitespace collapse and case folding.

    Runs of whitespace become a single space, leading/trailing whitespace is trimmed, and case is
    folded with ``str.lower()``. Nothing else is removed or folded, so every character that can
    affect meaning (signs, symbols, units, percent signs and non-ASCII text) survives intact.
    """
    return " ".join(text.split()).lower()


def _overlap(claim_tokens: list[str], source_tokens: list[str]) -> float:
    """Diagnostic proxy only: the share of a claim's tokens that appear anywhere in a source."""
    if not claim_tokens:
        return 0.0
    available = set(source_tokens)
    return sum(1 for token in claim_tokens if token in available) / len(claim_tokens)


def _has_checkable_content(text: str) -> bool:
    """True when the text has at least one word character, so it asserts something checkable."""
    return bool(_WORD.search(text))


def _is_contiguous_span(claim_text: str, source_text: str) -> bool:
    """Compare complete sentence/colon-tail quotations, with case and whitespace normalisation.

    Source sentences are the structural units of :mod:`aspire_brain.providers.segments`; a
    leading Markdown marker is not part of a unit on either side. A tail starts only after a
    source colon plus whitespace and ends at the sentence end.
    No arbitrary word boundary is sufficient: whitespace can separate a sign, currency or unit
    from a number. Restricting both edges also rejects ``50`` cut from ``250`` or ``50%`` and
    ``需审批`` cut from ``无需审批``. This conservative extraction grammar is not entailment;
    omitted context outside a sentence or colon tail is not evaluated here.
    """
    claim = comparable(claim_text)
    if not claim:
        return False
    for sentence in source_sentences(source_text):
        unit = comparable(sentence)
        starts = (0, *(match.end() for match in re.finditer(r":\s+", unit)))
        if any(claim == comparable(unit[start:]) for start in starts):
            return True
    return False


def _strip_service_label(sentence: str, locator: str) -> str | None:
    """Remove a recognised service-authored citation label that names ``locator``.

    Returns the remainder, or ``None`` when the sentence carries no such label. The label is
    matched exactly, so an arbitrary prefix is not treated as service formatting.
    """
    normalised = _normalise(sentence)
    normalised_locator = _normalise(locator)
    for form in CITATION_LABELS:
        label = form.format(locator=normalised_locator)
        if normalised.startswith(label):
            return normalised[len(label):]
    return None


def _notice_sentences(notices) -> set[str]:
    """The exact service-authored notice sentences excluded from the denominator."""
    return {_normalise(part) for notice in notices for part in split_claims(_normalise(str(notice)))}


def evaluate_claim_support(*, answer: str, citation_ids, evidence, notices=(), locators=None,
                           provider_mode: str, mode: str = "simulated",
                           abstained: bool = False) -> dict:
    """Return a JSON-ready report with a denominator and a simulated/live label.

    ``evidence`` maps a citation identifier to the source text used to support it. ``locators``
    optionally maps the same identifier to the source locator, so a service-authored citation
    label can be recognised. ``notices`` are sentences the application itself authored (for
    example a mode summary); an exact match is excluded from the denominator and counted
    separately, so the denominator only covers assertions.
    """
    if not isinstance(answer, str):
        raise ValueError("Answer must be text")
    if mode not in {"simulated", "live"}:
        raise ValueError("Measurement mode must be simulated or live")
    if mode == "live" and provider_mode in LOCAL_PROVIDER_MODES:
        raise ValueError("A local provider result cannot be labelled a live result")
    ordered_ids = list(dict.fromkeys(citation_ids))
    locators = dict(locators or {})
    notice_set = _notice_sentences(notices)
    claims: list[ClaimSupport] = []
    notices_excluded = 0
    if not abstained:
        for sentence in _answer_claims(answer):
            if _normalise(sentence) in notice_set:
                notices_excluded += 1
                continue
            if not _has_checkable_content(sentence):
                # A sentence with no checkable content cannot be verified, so it fails closed
                # rather than being waved through as if it asserted nothing.
                claims.append(ClaimSupport(claim=sentence, kind="claim", supported=False,
                                           support_ratio=0.0, supporting_ids=[],
                                           reason="no_checkable_tokens"))
                continue
            claim_tokens = _tokens(sentence)  # diagnostic overlap only; never the gate
            best_ratio = 0.0
            supporting: list[str] = []
            for identifier in ordered_ids:
                source_text = str(evidence.get(identifier, ""))
                best_ratio = max(best_ratio, _overlap(claim_tokens, _tokens(source_text)))
                body = sentence
                locator = locators.get(identifier)
                if locator:
                    stripped = _strip_service_label(sentence, str(locator))
                    if stripped is not None:
                        body = stripped
                if _is_contiguous_span(body, source_text):
                    supporting.append(identifier)
            supported = bool(supporting)
            reason: ClaimReason = ("supported_by_exact_cited_span" if supported
                                   else ("no_cited_evidence" if not ordered_ids
                                         else "no_exact_cited_span"))
            claims.append(ClaimSupport(claim=sentence, kind="claim", supported=supported,
                                       support_ratio=round(best_ratio, 6),
                                       supporting_ids=supporting, reason=reason))
    evaluated = [claim for claim in claims if claim.kind == "claim"]
    report = ClaimSupportReport(
        mode=mode, provider_mode=provider_mode, method=SUPPORT_METHOD,
        denominator=len(evaluated),
        supported_claims=sum(claim.supported for claim in evaluated),
        unsupported_claims=sum(not claim.supported for claim in evaluated),
        notices_excluded=notices_excluded,
        all_supported=all(claim.supported for claim in evaluated),
        abstained=bool(abstained), claims=claims, limitation=LIMITATION)
    return report.model_dump(mode="json")
