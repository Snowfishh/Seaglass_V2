"""Question-focused extraction over already-permitted evidence.

Quoting every permitted record in full answers nothing: a reader still has to find the part
that matters, and a question the evidence cannot answer comes back with unrelated text. This
module does the two things a local, model-free answerer can do honestly:

* **Answerability.** It extracts the question's content terms and measures how many of them the
  permitted evidence covers. Below :data:`ANSWERABLE_COVERAGE` the question is treated as
  unanswered and nothing is released. A term counts as covered when a source word equals it,
  shares a long common prefix with it (``approved``/``approvals``) or is a listed irregular form.
* **Selection.** It picks passages (a short paragraph, a list item, a field line or a table row;
  see :mod:`aspire_brain.providers.segments`) that cover the question's terms, greedily, so each
  covered term is represented, then gives every other relevant record its best passage, then
  adds passages that alone match most of the question. A heading is never selected for its own
  match; a quoted record shows its title heading and, for an issue, its ``Status:`` line.
  When a record's title alone covers the question, the record is the subject of the question
  ("the latest runbook") and its sentences are kept in order.

It is lexical, not semantic. A synonym the source does not share (``money`` against ``amount``)
is not covered. The selection only ever contains complete source sentences of records that have
already passed every permission and freshness check, so it cannot add or reveal anything.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from aspire_brain.platforms.routing import PLATFORM_ALIASES, STOPWORDS
from aspire_brain.providers.segments import source_paragraphs

#: The share of a question's content terms the permitted evidence must cover.
ANSWERABLE_COVERAGE = 0.75
#: Passages selected for one answer, across every record, besides a subject record.
MAX_PASSAGES = 6
#: Sentences kept from a record that is itself the subject of the question.
MAX_SUBJECT_SENTENCES = 12
#: Passages taken from each record that carries an identifier the question names.
MAX_ANCHORED_PASSAGES = 2

#: Words that shape a question but carry no topic: question words, time scope, platform names
#: and request verbs. Routing and time scoping already used them.
QUESTION_WORDS = STOPWORDS | frozenset({
    "is", "a", "an", "of", "to", "in", "on", "at", "by", "be", "or", "as", "it", "if", "so",
    "do", "we", "me", "my", "our", "us", "i", "am", "isn", "aren", "wasn", "don", "doesn",
    "many", "much", "there", "these", "those", "whose", "while", "were", "will", "please",
    "latest", "current", "currently", "recent", "recently", "newest", "new", "now", "today",
    "yesterday", "last", "past", "previous", "week", "weeks", "month", "months", "day", "days",
    "show", "give", "list", "find", "explain", "summarize", "summarise", "summary", "overview",
    "know", "happen", "happened", "anything", "everything", "something", "according", "per",
    "being", "done", "doing", "make", "made", "still", "yet", "ever", "since", "between",
    "within", "across", "regarding", "related", "relevant", "info", "information", "details",
    "detail", "say", "said", "says", "see", "look", "need", "needs", "needed",
    *{alias for aliases in PLATFORM_ALIASES.values() for alias in aliases},
})
#: Irregular forms folded onto one stem, so "lose" and "loss" meet.
IRREGULAR = {
    "lost": "lose", "loss": "lose", "losses": "lose", "held": "hold", "paid": "pay",
    "sent": "send", "took": "take", "taken": "take", "gave": "give", "given": "give",
    "wrote": "write", "written": "write", "broke": "break", "broken": "break", "ran": "run",
    "went": "go", "gone": "go", "kept": "keep", "found": "find", "began": "begin",
    "begun": "begin", "chose": "choose", "chosen": "choose", "rose": "rise", "risen": "rise",
}
_TOKEN = re.compile(r"[a-z0-9]+(?:['\-:][a-z0-9]+)*")


def _forms(text: str) -> set[str]:
    """Lower-case word forms. An identifier with a digit stays whole (``ops-demo-01``, ``09:30``)."""
    forms = set()
    for token in _TOKEN.findall(text.lower().replace("’", "'")):
        token = token.removesuffix("'s")
        if any(char.isdigit() for char in token) and any(char in token for char in "-:"):
            forms.add(token)
            continue
        for part in re.split(r"['\-:]", token):
            if part:
                forms.add(IRREGULAR.get(part, part))
    return forms


def question_terms(question: str) -> list[str]:
    """The content terms of a question, in a stable order."""
    return sorted(term for term in _forms(question)
                  if term not in QUESTION_WORDS
                  and (len(term) >= 3 or any(char.isdigit() for char in term)))


def _is_identifier(term: str) -> bool:
    """A record identifier (``ops-demo-01``), not a time or a number (``09:30``)."""
    return any(char.isdigit() for char in term) and any(char.isalpha() for char in term)


def _matches(term: str, word: str) -> bool:
    if term == word:
        return True
    if not (term.isalpha() and word.isalpha()):
        return False
    shared = len(next((term[:i] for i in range(min(len(term), len(word)), 0, -1)
                       if term[:i] == word[:i]), ""))
    return shared >= 4 and shared >= min(len(term), len(word)) - 2


def matched_terms(terms, text: str) -> frozenset[str]:
    words = _forms(text)
    return frozenset(term for term in terms if any(_matches(term, word) for word in words))


@dataclass(frozen=True)
class _Passage:
    rank: int
    order: int
    record: object
    sentences: tuple[str, ...]
    matched: frozenset[str]
    kind: str
    table_header: str | None = None


def _passages(rank: int, record, terms) -> list[_Passage]:
    """Split one record into selectable passages.

    A short prose paragraph (up to four sentences) is one passage, so a sentence keeps its
    lead-in ("Of these, 118 are completed ..."). Headings, list items, field lines, table rows
    and the sentences of a long paragraph are passages on their own. A table row remembers its
    header row so the columns can be read.
    """
    passages = []
    for paragraph in source_paragraphs(record.text):
        kinds = {kind for _, kind in paragraph}
        if kinds == {"text"} and len(paragraph) <= 4:
            groups = [(tuple(sentence for sentence, _ in paragraph), "text", None)]
        elif kinds == {"row"}:
            header = paragraph[0][0]
            groups = [((paragraph[0][0],), "header", None)] + [
                ((sentence,), "row", header) for sentence, _ in paragraph[1:]]
        else:
            groups = [((sentence,), kind, None) for sentence, kind in paragraph]
        for sentences, kind, header in groups:
            passages.append(_Passage(rank, len(passages), record, sentences,
                                     matched_terms(terms, " ".join(sentences)), kind, header))
    return passages


@dataclass
class FocusResult:
    terms: list[str]
    covered_terms: list[str]
    coverage: float
    answerable: bool
    #: ``(record, [sentence, ...])`` in output order; records with no selected sentence omitted.
    selections: list[tuple[object, list[str]]] = field(default_factory=list)
    subject_record_ids: list[str] = field(default_factory=list)
    #: ``(platform, source_id)`` of every record with at least one matching passage.
    matching_record_ids: list[tuple[str, str]] = field(default_factory=list)
    #: ``(platform, source_id) -> [sentence, ...]``: every passage that matches any term, in
    #: source order. A live model chooses among these instead of the local selection.
    matching_sentences: dict = field(default_factory=dict)

    def report(self, *, applied: bool) -> dict:
        return {
            "method": "lexical_term_coverage", "applied": applied,
            "terms": self.terms, "covered_terms": self.covered_terms,
            "coverage": round(self.coverage, 4), "threshold": ANSWERABLE_COVERAGE,
            "answerable": self.answerable,
            "selected_sentences": sum(len(units) for _, units in self.selections),
            "subject_record_ids": self.subject_record_ids,
            "note": ("Local answers quote only the passages that cover the question's terms. "
                     "Coverage is lexical: a synonym the source does not share is not counted."),
        }


def focus(question: str, records, *, max_passages: int = MAX_PASSAGES,
          required_platforms=()) -> FocusResult:
    """Select the passages of ``records`` (already ranked and permitted) that answer ``question``.

    ``required_platforms`` are platforms the question itself pointed at ("raised in Slack"). A
    record there contributes its best matching passage even when it matches only one term.
    """
    terms = question_terms(question)
    passages = [passage for rank, record in enumerate(records)
                for passage in _passages(rank, record, terms)]
    content = [passage for passage in passages if passage.kind not in {"heading", "header"}]
    covered = frozenset().union(*(passage.matched for passage in content))
    coverage = len(covered) / len(terms) if terms else 0.0
    answerable = bool(terms) and coverage + 1e-9 >= ANSWERABLE_COVERAGE
    result = FocusResult(terms=terms, covered_terms=sorted(covered), coverage=coverage,
                         answerable=answerable)
    if not terms:
        return result

    def key(passage):
        return passage.rank, passage.order

    chosen: dict[tuple[int, int], _Passage] = {}
    # A record whose title alone covers the question is what the question asks for. Only a real
    # title counts (a heading, or a table's header row): a record without one, such as a chat
    # message, would otherwise have its first paragraph treated as its title and every later,
    # unrelated passage quoted with it.
    subjects = []
    for rank, record in enumerate(records):
        own = [passage for passage in passages if passage.rank == rank]
        if (own and own[0].kind in {"heading", "header"}
                and len(own[0].matched) / len(terms) + 1e-9 >= ANSWERABLE_COVERAGE):
            subjects.append(record)
            used = 0
            for passage in own:
                if used + len(passage.sentences) > MAX_SUBJECT_SENTENCES:
                    break
                chosen[key(passage)] = passage
                used += len(passage.sentences)
    budget = len(chosen) + max_passages
    # Cover every term the evidence can cover, best passage first.
    remaining = set(terms) - set().union(*(passage.matched for passage in chosen.values()))
    while remaining and len(chosen) < budget:
        cited = {passage.rank for passage in chosen.values()}
        best = max((passage for passage in content
                    if key(passage) not in chosen and passage.matched & remaining),
                   key=lambda passage: (len(passage.matched & remaining), passage.rank in cited,
                                        len(passage.matched), -passage.rank, -passage.order),
                   default=None)
        if best is None:
            break
        chosen[key(best)] = best
        remaining -= best.matched
    # Give every other record that matches most of the question its best passage, so the
    # answer draws on each relevant source rather than only the first one.
    majority = len(terms) // 2 + 1
    for rank in range(len(records)):
        required = records[rank].platform in required_platforms
        if (len(chosen) >= budget and not required) or any(
                passage.rank == rank for passage in chosen.values()):
            continue
        best = max((passage for passage in content if passage.rank == rank),
                   key=lambda passage: (len(passage.matched), passage.kind == "text",
                                        len(passage.sentences), -passage.order), default=None)
        needed = 1 if records[rank].platform in required_platforms else majority
        if best is not None and len(best.matched) >= needed:
            chosen[key(best)] = best
    # A question that names an identifier ("OPS-DEMO-01") is about the records that carry it,
    # on whichever platform they sit, and about the replies in a thread whose root carries it.
    # Each such record contributes its best passages (up to :data:`MAX_ANCHORED_PASSAGES`) that
    # also match another question term, so a cross-platform question draws on every platform
    # that records the named work.
    identifiers = {term for term in terms if _is_identifier(term)}
    if identifiers:
        carrying = {(record.platform, record.source_id) for record in records
                    if matched_terms(identifiers, record.text)}
        added = 0
        for rank, record in enumerate(records):
            thread = getattr(record, "thread_id", None)
            anchored = ((record.platform, record.source_id) in carrying
                        or (thread is not None and (record.platform, thread) in carrying))
            if (not anchored or added >= max_passages
                    or any(passage.rank == rank for passage in chosen.values())):
                continue
            best = sorted((passage for passage in content
                           if passage.rank == rank and passage.kind != "field"
                           and passage.matched - identifiers),
                          key=lambda passage: (-len(passage.matched - identifiers),
                                               passage.kind != "text", passage.order))
            for passage in best[:MAX_ANCHORED_PASSAGES]:
                chosen[key(passage)] = passage
            added += bool(best)
    # Then any passage that matches most of the question on its own.
    strong = max(2, math.ceil(ANSWERABLE_COVERAGE * len(terms)))
    for passage in sorted(content, key=lambda passage: (-len(passage.matched), key(passage))):
        if len(chosen) >= budget or len(passage.matched) < strong:
            break
        chosen.setdefault(key(passage), passage)

    # A quoted record also shows what it is: its title heading and, for an issue, its status.
    for rank in sorted({passage.rank for passage in chosen.values()}):
        own = [passage for passage in passages if passage.rank == rank]
        if own[0].kind == "heading":
            chosen.setdefault(key(own[0]), own[0])
        if records[rank].platform == "jira":
            for passage in own:
                if passage.sentences[0].lower().startswith("status:"):
                    chosen.setdefault(key(passage), passage)
                    break

    for rank, record in enumerate(records):
        selected: list[str] = []
        for passage in sorted((p for p in chosen.values() if p.rank == rank), key=key):
            if passage.table_header and passage.table_header not in selected:
                selected.append(passage.table_header)
            selected.extend(sentence for sentence in passage.sentences if sentence not in selected)
        if selected:
            result.selections.append((record, selected))
    result.subject_record_ids = [record.source_id for record in subjects]
    result.matching_record_ids = sorted({(passage.record.platform, passage.record.source_id)
                                         for passage in content if passage.matched})
    for passage in content:
        if passage.matched:
            sentences = result.matching_sentences.setdefault(
                (passage.record.platform, passage.record.source_id), [])
            if passage.table_header and passage.table_header not in sentences:
                sentences.append(passage.table_header)
            sentences.extend(sentence for sentence in passage.sentences
                             if sentence not in sentences)
    return result
