"""G3 routing, cross-platform ranking and the explicit overall context budget.

Three deterministic, dependency-free pieces that the simulated query service composes:

* :func:`route_question` decides which platforms a natural-language question touches. It is
  deliberately conservative — an ambiguous or broad question includes every plausible source,
  and a keyword miss is recorded as omitted coverage rather than treated as proof that a
  platform is irrelevant.
* :func:`rank_candidates` scores permitted candidates from every platform together, so the
  final evidence set is a cross-platform ranking rather than a per-platform concatenation.
  It only ever sees records that already passed the platform permission checks.
* :class:`ContextBudget` caps total items and characters. When it binds, degradation is
  deterministic (highest-ranked evidence survives) and the dropped evidence is recorded.
* :class:`TimeWindow` / :func:`detect_time_window` scope retrieval to an explicit, validated
  window using a record's declared event/creation time — never ``source_updated_at``.

No live platform is contacted and no external model is used here.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from pydantic import Field, model_validator

from aspire_brain.models import StrictModel

#: The four platforms, in a stable order used for deterministic tie-breaks.
PLATFORMS = ("confluence", "jira", "slack", "drive")

#: A question that names a platform outright.
PLATFORM_ALIASES: dict[str, frozenset[str]] = {
    "confluence": frozenset({"confluence", "wiki", "wikis"}),
    "jira": frozenset({"jira"}),
    "slack": frozenset({"slack"}),
    "drive": frozenset({"drive", "gdrive"}),
}

#: Source-kind and topic words that imply a platform.
PLATFORM_SIGNALS: dict[str, frozenset[str]] = {
    "confluence": frozenset({
        "runbook", "runbooks", "page", "pages", "doc", "docs", "document", "documents",
        "documentation", "guide", "guides", "handbook", "policy", "policies", "decision",
        "decisions", "spec", "specification", "space", "spaces", "writeup", "report",
        "reports", "notes",
    }),
    "jira": frozenset({
        "ticket", "tickets", "issue", "issues", "project", "projects", "sprint", "sprints",
        "epic", "epics", "bug", "bugs", "backlog", "assignee", "board", "story", "stories",
        "status", "milestone", "blocked",
    }),
    "slack": frozenset({
        "thread", "threads", "channel", "channels", "message", "messages", "dm", "dms",
        "chat", "discussion", "discussions", "conversation", "conversations", "standup",
        "blocker", "blockers", "raised", "huddle", "ping",
    }),
    "drive": frozenset({
        "file", "files", "folder", "folders", "postmortem", "post-mortem", "attachment",
        "attachments", "spreadsheet", "sheet", "sheets", "deck", "presentation", "pdf", "csv",
    }),
}

#: Cross-cutting wording that should widen routing to every platform.
BROAD_MARKERS = frozenset({
    "everything", "everywhere", "across", "anywhere", "summarize", "summarise", "summary",
    "overview",
})
BROAD_PHRASES = ("root cause", "all platforms", "across platforms")

#: Routing bases that queried every platform as a precaution rather than on a signal.
DEFAULT_ALL_BASES = frozenset({"broad_default_all", "no_signal_default_all"})

_TICKET_ID = re.compile(r"\b[A-Z]{2,}-\d+\b")
_WORD = re.compile(r"[a-z0-9][a-z0-9-]*")

#: Words that carry no retrieval signal; excluded from the ranking score so a common word
#: cannot outrank a topical one.
STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "from", "what",
    "when", "where", "which", "who", "whom", "why", "how", "does", "did", "has", "have",
    "had", "not", "but", "you", "your", "about", "into", "over", "under", "out", "all",
    "any", "can", "could", "should", "would", "will", "its", "they", "them", "their",
    "there", "here", "then", "than", "also", "just", "only", "get", "got", "use", "used",
    "say", "says", "said", "tell", "been", "being", "more", "most", "some", "such",
})

_KEYWORD_COVERAGE_NOTE = (
    "Routing used keyword signals only. Omitted platforms had no explicit signal and were "
    "not queried; their omission is not evidence of absence."
)


def _words(question: str) -> set[str]:
    return set(_WORD.findall(question.lower()))


def route_question(question: str, *, available: tuple[str, ...] = PLATFORMS) -> dict:
    """Decide which platforms a question touches, conservatively and deterministically."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Question must contain 1 to 2000 characters")
    words = _words(question)
    explicit = [platform for platform in available if PLATFORM_ALIASES[platform] & words]
    signals: dict[str, list[str]] = {}
    for platform in available:
        hits = sorted((PLATFORM_SIGNALS[platform] | PLATFORM_ALIASES[platform]) & words)
        if hits:
            signals[platform] = hits
    if _TICKET_ID.search(question):
        signals.setdefault("jira", []).append("ticket-id")

    selected = {platform for platform in explicit} | set(signals)
    broad = bool(words & BROAD_MARKERS) or any(phrase in question.lower() for phrase in BROAD_PHRASES)
    if broad:
        selected = set(available)
        basis = "broad_default_all"
    elif not selected:
        selected = set(available)
        basis = "no_signal_default_all"
    elif explicit and selected == set(explicit):
        basis = "explicit_platform_mention"
    else:
        basis = "keyword_signals"

    ordered = [platform for platform in available if platform in selected]
    omitted = [platform for platform in available if platform not in selected]
    if basis == "broad_default_all":
        note = "Broad question: every platform was queried to avoid inferring completeness."
    elif basis == "no_signal_default_all":
        note = "No platform signal was detected; every platform was queried conservatively."
    elif omitted:
        note = _KEYWORD_COVERAGE_NOTE
    else:
        note = "Every platform carried an explicit signal and was queried."
    return {
        "mode": "question_driven", "selected_platforms": ordered, "basis": basis,
        "signals": signals, "explicit_platforms": explicit, "omitted_platforms": omitted,
        "coverage_note": note,
    }


def explicit_override_decision(platforms) -> dict:
    """Describe a caller-supplied platform set, used by tests and the deterministic demo."""
    ordered = [platform for platform in PLATFORMS if platform in tuple(platforms)]
    return {
        "mode": "explicit_override", "selected_platforms": ordered,
        "basis": "explicit_override", "signals": {}, "explicit_platforms": [],
        "omitted_platforms": [platform for platform in PLATFORMS if platform not in ordered],
        "coverage_note": "Platforms were supplied explicitly by the caller; routing was not applied.",
    }


def _terms(question: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", question.lower())
            if len(word) >= 3 and word not in STOPWORDS}


def rank_candidates(question: str, items, *, explicit_platforms=(), limit: int | None = None):
    """Score permitted ``(platform, record)`` candidates together.

    ``score = 10 * term_hits + 5 * source_id_hits + 3 if the platform was named outright``,
    counting question terms of three or more characters that are not stopwords. Ties break on
    ``(platform, source_id)`` so the order is reproducible. Only records that already passed
    the platform permission check should be passed in.
    """
    terms = _terms(question)
    named = set(explicit_platforms)
    scored = []
    for platform, record in items:
        text = record.text.lower()
        term_hits = sum(1 for term in terms if term in text)
        id_hits = sum(1 for term in terms if term in record.source_id.lower())
        score = 10 * term_hits + 5 * id_hits + (3 if platform in named else 0)
        scored.append((score, record))
    scored.sort(key=lambda pair: (-pair[0], pair[1].platform, pair[1].source_id))
    return scored[:limit] if limit is not None else scored


class ContextBudget(StrictModel):
    """An explicit overall cap across every platform."""

    max_items: int = Field(ge=1, le=50)
    max_chars: int = Field(ge=100, le=100000)


def apply_budget(ranked, budget: ContextBudget):
    """Keep the highest-ranked evidence that fits; return ``(included, dropped)``."""
    included, dropped = [], []
    used_items, used_chars = 0, 0
    for score, record in ranked:
        size = len(record.text)
        if used_items + 1 > budget.max_items or used_chars + size > budget.max_chars:
            dropped.append((score, record))
            continue
        included.append((score, record))
        used_items += 1
        used_chars += size
    return included, dropped


class TimeWindow(StrictModel):
    """A validated half-open ``[start, end)`` window over a record's event time."""

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered_aware_bounds(self):
        for value in (self.start, self.end):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Time window bounds need a timezone")
        if not self.start < self.end:
            raise ValueError("Time window start must precede its end")
        return self

    def contains(self, value: datetime) -> bool:
        return self.start <= value < self.end


def detect_time_window(question: str, now: datetime) -> TimeWindow | None:
    """Detect an explicit relative window such as "last week" or "past 3 days"."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Query time needs a timezone")
    text = question.lower()
    if "last week" in text or "past week" in text or "previous week" in text:
        return TimeWindow(start=now - timedelta(days=7), end=now)
    if "last month" in text or "past month" in text:
        return TimeWindow(start=now - timedelta(days=30), end=now)
    match = re.search(r"(?:last|past)\s+(\d{1,3})\s+days?", text)
    if match:
        days = int(match.group(1))
        if not 1 <= days <= 365:
            raise ValueError("Time window must be between 1 and 365 days")
        return TimeWindow(start=now - timedelta(days=days), end=now)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "today" in text:
        return TimeWindow(start=midnight, end=now)
    if "yesterday" in text:
        return TimeWindow(start=midnight - timedelta(days=1), end=midnight)
    return None
