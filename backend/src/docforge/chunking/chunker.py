from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from docforge.domain.documents import BBox, Block, BlockKind, DocumentModel, Word
from docforge.domain.records import ChunkRecord, ChunkSpan
from docforge.sources.hashing import stable_hash

_TOKEN = re.compile(r"\w+|[^\w\s]")


TOKENS_PER_PIECE = 1.1


def estimate_tokens(text: str) -> int:
    """Cheap, model-agnostic estimate: about 1.1 subword tokens per word or punctuation mark."""
    return math.ceil(len(_TOKEN.findall(text)) * TOKENS_PER_PIECE)


@dataclass
class _Draft:
    heading_path: list[str]
    blocks: list[Block] = field(default_factory=list)
    row_span: tuple[int, int] | None = None
    texts: list[str] = field(default_factory=list)
    tokens: int = 0
    is_table: bool = False


class StructureAwareChunker:
    """Chunks along the document's own structure.

    A chunk never crosses a heading boundary, so retrieval results stay inside one section.
    Tables are chunked on their own and split by rows with the header row repeated, so every
    table chunk is self-describing. A paragraph longer than the budget is cut into word windows,
    each with a box around its own words, so no chunk outgrows what the embedding model reads.
    Every chunk keeps the block ids, pages and boxes it came from.
    """

    def __init__(self, max_tokens: int = 320, overlap_blocks: int = 1) -> None:
        self.max_tokens = max_tokens
        self.overlap_blocks = overlap_blocks

    @property
    def version(self) -> str:
        return f"structure-v3:max={self.max_tokens}:overlap={self.overlap_blocks}"

    def chunk(self, document: DocumentModel) -> list[ChunkRecord]:
        drafts: list[_Draft] = []
        headings: list[tuple[int, str]] = []
        current: _Draft | None = None

        def flush() -> None:
            nonlocal current
            if current is not None and current.blocks:
                drafts.append(current)
            current = None

        for block in document.iter_blocks():
            if block.kind is BlockKind.HEADING:
                flush()
                level = block.heading_level or 1
                headings = [(lvl, text) for lvl, text in headings if lvl < level]
                headings.append((level, block.text))
                continue

            path = [text for _, text in headings]
            if block.kind is BlockKind.TABLE:
                flush()
                drafts.extend(self._table_drafts(block, path))
                continue

            for piece in self._fit(block):
                tokens = estimate_tokens(piece.text)
                if current is None:
                    current = _Draft(heading_path=path)
                elif current.tokens + tokens > self.max_tokens:
                    carried = current.blocks[-self.overlap_blocks :] if self.overlap_blocks else []
                    flush()
                    current = _Draft(heading_path=path)
                    for previous in carried:
                        if estimate_tokens(previous.text) + tokens <= self.max_tokens:
                            self._add(current, previous, previous.text)
                self._add(current, piece, piece.text)
        flush()

        return [self._record(index, draft) for index, draft in enumerate(drafts)]

    def _fit(self, block: Block) -> list[Block]:
        """The block itself, or word windows of it when it alone exceeds the token budget."""
        if estimate_tokens(block.text) <= self.max_tokens:
            return [block]
        words = block.words or [Word(text=token, bbox=block.bbox) for token in block.text.split()]
        pieces: list[Block] = []
        window: list[Word] = []
        used = 0
        for word in words:
            cost = len(_TOKEN.findall(word.text))
            if window and math.ceil((used + cost) * TOKENS_PER_PIECE) > self.max_tokens:
                pieces.append(self._piece(block, window))
                window, used = [], 0
            window.append(word)
            used += cost
        if window:
            pieces.append(self._piece(block, window))
        return pieces

    @staticmethod
    def _piece(block: Block, words: list[Word]) -> Block:
        return block.model_copy(
            update={
                "text": " ".join(word.text for word in words),
                "bbox": BBox.enclosing([word.bbox for word in words]),
                "words": words,
            }
        )

    @staticmethod
    def _add(draft: _Draft, block: Block, text: str) -> None:
        draft.blocks.append(block)
        draft.texts.append(text)
        draft.tokens += estimate_tokens(text)

    def _table_drafts(self, block: Block, path: list[str]) -> list[_Draft]:
        rows = block.rows or [[block.text]]
        header, body = rows[0], rows[1:]
        header_line = " | ".join(header)
        if not body:
            draft = _Draft(heading_path=path, is_table=True)
            self._add(draft, block, header_line)
            return [draft]

        drafts: list[_Draft] = []
        batch: list[str] = []
        first_row = 1
        budget = self.max_tokens - estimate_tokens(header_line)
        used = 0
        for row_index, row in enumerate(body, start=1):
            line = " | ".join(row)
            cost = estimate_tokens(line)
            if batch and used + cost > budget:
                drafts.append(self._table_draft(block, path, header_line, batch, first_row))
                batch, used, first_row = [], 0, row_index
            batch.append(line)
            used += cost
        if batch:
            drafts.append(self._table_draft(block, path, header_line, batch, first_row))
        return drafts

    def _table_draft(
        self, block: Block, path: list[str], header: str, lines: list[str], first_row: int
    ) -> _Draft:
        draft = _Draft(heading_path=path, is_table=True, row_span=(first_row, first_row + len(lines) - 1))
        self._add(draft, block, "\n".join([header, *lines]))
        return draft

    @staticmethod
    def _span_boxes(block: Block, row_span: tuple[int, int] | None) -> list[BBox]:
        """The header row and the chunk's own rows, as separate boxes when they are not adjacent."""
        if row_span is None or not block.row_boxes or row_span[1] >= len(block.row_boxes):
            return [block.bbox]
        rows = BBox.enclosing(block.row_boxes[row_span[0] : row_span[1] + 1])
        header = block.row_boxes[0]
        return [header.union(rows)] if row_span[0] == 1 else [header, rows]

    @staticmethod
    def _record(index: int, draft: _Draft) -> ChunkRecord:
        text = "\n\n".join(draft.texts)
        context = " > ".join(draft.heading_path)
        embed_text = f"{context}\n\n{text}" if context else text
        pages = [block.page for block in draft.blocks]
        return ChunkRecord(
            index=index,
            text=text,
            embed_text=embed_text,
            token_count=estimate_tokens(text),
            heading_path=draft.heading_path,
            page_start=min(pages),
            page_end=max(pages),
            spans=[
                ChunkSpan(block_id=b.id, page=b.page, bbox=box)
                for b in draft.blocks
                for box in StructureAwareChunker._span_boxes(b, draft.row_span)
            ],
            content_hash=stable_hash(embed_text),
            is_table=draft.is_table,
        )
