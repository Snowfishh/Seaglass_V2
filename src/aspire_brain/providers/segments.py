"""Structure-aware source sentences, shared by the claim gate, the live provider and extraction.

A "complete source sentence" used to be whatever lay between two sentence-ending punctuation
marks once every line break had been collapsed. On a Markdown document that merged a heading,
a run of ``Field: value`` lines and the first paragraph sentence into one unit, so no useful
part of the document could be quoted on its own. These units follow the document's own
structure instead, and every consumer uses the same definition:

* A blank line ends a paragraph.
* A heading (``#``) is one unit. A list item (``-``, ``*``, ``1.``) starts a new unit and
  continues across soft-wrapped lines until the next item, blank line or hard break. A dash
  before a number is read as a sign, so ``-\\n250`` stays ``- 250``.
* A Markdown hard break (two trailing spaces) ends a unit, so ``Field: value`` lines stay apart.
* A single line break inside a paragraph is a soft wrap, so ``SGD\\n250`` is still ``SGD 250``.
* Rows of a delimited table (every line with the same number of commas, at least two) are
  one unit each.
* Within a unit, sentences end at ``.``, ``!`` or ``?`` followed by whitespace, except after a
  short list of abbreviations such as ``Pte.`` and ``e.g.``.

Leading Markdown markers are not part of a unit's text. Both edges of a unit are therefore set
by the source's structure, never by an arbitrary character offset.
"""

from __future__ import annotations

import re

#: A Markdown marker that starts a structural line: a heading, a bullet or a numbered item. A
#: dash or plus followed by a number is a sign, not a bullet ("- 250" stays "- 250"), and a
#: ``>`` is never treated as a quote marker because it can mean "greater than".
MARKER = re.compile(r"^(?:#{1,6}\s+|[-*+•]\s+(?=[^\s\d.,+\-])|\d{1,3}[.)]\s+(?=[^\s\d]))")
_HEADING = re.compile(r"^#{1,6}\s+")
_SENTENCE_END = re.compile(r"[.!?]\s+")
#: Words whose final period does not end a sentence. Lower case, including the period.
ABBREVIATIONS = frozenset({
    "pte.", "ltd.", "inc.", "co.", "corp.", "plc.", "llc.", "mr.", "mrs.", "ms.", "dr.",
    "st.", "no.", "vs.", "e.g.", "i.e.", "approx.", "dept.", "jan.", "feb.", "mar.", "apr.",
    "jun.", "jul.", "aug.", "sep.", "sept.", "oct.", "nov.", "dec.",
})


def strip_marker(text: str) -> str:
    """Remove one leading Markdown marker; the remainder is the unit's content."""
    return MARKER.sub("", text, count=1)


def split_sentences(text: str) -> list[str]:
    """Split one whitespace-collapsed unit into sentences, keeping known abbreviations whole."""
    sentences, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        end = match.start() + 1
        word = text[:end].rsplit(" ", 1)[-1].lower()
        if word in ABBREVIATIONS:
            continue
        piece = text[start:end].strip()
        if piece:
            sentences.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _tabular(lines: list[str]) -> bool:
    rows = [line for line in lines if line.strip()]
    if len(rows) < 2:
        return False
    counts = {row.count(",") for row in rows}
    return len(counts) == 1 and counts.pop() >= 2


def source_paragraphs(text: str) -> list[list[tuple[str, str]]]:
    """Return each paragraph as ``[(sentence, kind), ...]``.

    ``kind`` is ``heading``, ``item`` (a list item or hard-broken line), ``row`` (a table row)
    or ``text``. Sentences are whitespace collapsed and carry no leading Markdown marker.
    """
    if not isinstance(text, str):
        raise ValueError("Source text must be text")
    paragraphs: list[list[tuple[str, str]]] = []
    for block in re.split(r"\n[ \t]*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.split("\n")
        tabular = _tabular(lines)
        units: list[tuple[str, str]] = []
        current: list[str] = []
        kind = ["text"]

        def flush():
            joined = " ".join(" ".join(current).split())
            current.clear()
            if not joined:
                return
            if tabular:
                units.append((joined, "row"))
            else:
                units.extend((sentence, kind[0]) for sentence in split_sentences(strip_marker(joined)))
            kind[0] = "text"

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            marker = MARKER.match(stripped)
            if current and (tabular or marker):
                flush()
            if marker:
                kind[0] = "heading" if _HEADING.match(stripped) else "item"
            current.append(stripped)
            if tabular or _HEADING.match(stripped) or line.endswith("  "):
                if line.endswith("  ") and kind[0] == "text":
                    kind[0] = "item"
                flush()
        flush()
        if units:
            paragraphs.append(units)
    return paragraphs


def source_sentences(text: str) -> list[str]:
    """Return the complete, structure-delimited sentences of ``text``, whitespace collapsed."""
    return [sentence for paragraph in source_paragraphs(text) for sentence, _ in paragraph]


def comparable(text: str) -> str:
    """The form two units are compared in: marker removed, whitespace collapsed, case folded."""
    return " ".join(strip_marker(" ".join(text.split())).split()).lower()
