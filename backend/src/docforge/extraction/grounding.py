from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from pydantic import JsonValue

from docforge.domain.documents import BBox, Block, DocumentModel, Word
from docforge.domain.records import FieldProvenance

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
FUZZY_THRESHOLD = 0.86


def _norm(token: str) -> str:
    return _NON_ALNUM.sub("", token.lower())


def _tokens(text: str) -> list[str]:
    return [t for t in (_norm(part) for part in text.split()) if t]


def _search_words(words: list[Word], needle: list[str]) -> tuple[list[Word], bool] | None:
    """Finds ``needle`` in the word sequence: exact token match first, then a fuzzy window.

    A "word" can hold several tokens (a spreadsheet cell, for instance), so matching runs over
    tokens and maps the hit back to the words that own them.
    """
    owners: list[Word] = []
    hay: list[str] = []
    for word in words:
        for token in _tokens(word.text):
            hay.append(token)
            owners.append(word)
    n = len(needle)
    if n == 0 or not hay:
        return None

    def hit(start: int) -> list[Word]:
        unique: list[Word] = []
        for word in owners[start : start + n]:
            if not unique or unique[-1] is not word:
                unique.append(word)
        return unique

    for start in range(len(hay) - n + 1):
        if hay[start : start + n] == needle:
            return hit(start), True
    target = " ".join(needle)
    best: tuple[float, int] | None = None
    for start in range(len(hay) - n + 1):
        ratio = SequenceMatcher(None, " ".join(hay[start : start + n]), target).ratio()
        if ratio >= FUZZY_THRESHOLD and (best is None or ratio > best[0]):
            best = (ratio, start)
    if best is not None:
        return hit(best[1]), False
    return None


def _value_text(value: JsonValue) -> str | None:
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        return str(value) or None
    return None


def _distinctive(needle: list[str]) -> bool:
    """Whether a bare value is specific enough to search the whole document for.

    "USD", "30" or "1" appear all over an invoice; the first hit says nothing about where the
    value came from, so short values are only looked for near the evidence or the cited block.
    """
    return len(needle) >= 2 or len("".join(needle)) >= 4


def _ordered_blocks(document: DocumentModel, preferred: str | None) -> list[Block]:
    blocks = list(document.iter_blocks())
    if preferred:
        blocks.sort(key=lambda b: b.id != preferred)
    return blocks


def _near(blocks: list[Block], evidence: str | None, source_block: str | None) -> list[Block]:
    quote = " ".join(_tokens(evidence)) if evidence else ""
    return [b for b in blocks if b.id == source_block or (quote and quote in " ".join(_tokens(b.text)))]


def _word_hit(blocks: Iterable[Block], needle: list[str], evidence: str | None) -> FieldProvenance | None:
    for block in blocks:
        hit = _search_words(block.words, needle)
        if hit is not None:
            words, exact = hit
            return FieldProvenance(
                page=block.page,
                bbox=BBox.enclosing([w.bbox for w in words]),
                block_id=block.id,
                evidence=evidence,
                match="exact" if exact else "fuzzy",
            )
    return None


def _block_hit(blocks: Iterable[Block], needle: list[str], evidence: str | None) -> FieldProvenance | None:
    needle_text = " ".join(needle)
    for block in blocks:
        if needle_text in " ".join(_tokens(block.text)):
            return FieldProvenance(
                page=block.page, bbox=block.bbox, block_id=block.id, evidence=evidence, match="block"
            )
    return None


def locate(
    document: DocumentModel, value: JsonValue, evidence: str | None, source_block: str | None
) -> FieldProvenance:
    """Resolves a field to the tightest page region that supports it.

    The evidence quote is searched across the document. The bare value is the fallback, searched
    document-wide only when it is distinctive and otherwise only in the cited block or the blocks
    that contain the quote. Word-level matches give a box around exactly the matched words; a
    block-level match or the cited block is weaker, and the match kind records how strong it is.
    """
    blocks = _ordered_blocks(document, source_block)
    value_text = _value_text(value)
    value_needle = _tokens(value_text) if value_text else []
    if value_needle and not _distinctive(value_needle):
        value_scope = _near(blocks, evidence, source_block)
    else:
        value_scope = blocks

    searches: list[tuple[list[Block], list[str]]] = []
    if evidence and _tokens(evidence):
        searches.append((blocks, _tokens(evidence)))
    if value_needle and value_text != evidence:
        searches.append((value_scope, value_needle))

    for scope, needle in searches:
        found = _word_hit(scope, needle, evidence)
        if found is not None:
            return found
    for scope, needle in searches:
        found = _block_hit(scope, needle, evidence)
        if found is not None:
            return found
    if source_block:
        cited = next((b for b in blocks if b.id == source_block), None)
        if cited is not None:
            return FieldProvenance(
                page=cited.page, bbox=cited.bbox, block_id=cited.id, evidence=evidence, match="block"
            )
    return FieldProvenance(evidence=evidence, match="none")
