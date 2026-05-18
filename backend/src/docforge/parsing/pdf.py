from __future__ import annotations

import io
import itertools
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSException
from pdfplumber.utils.exceptions import PdfminerException

from docforge.domain.documents import (
    BBox,
    Block,
    BlockKind,
    DocumentFormat,
    DocumentModel,
    GeometryKind,
    Page,
    Word,
)
from docforge.errors import ParseError

LINE_TOLERANCE = 2.5
COLUMN_GAP_FACTOR = 2.2
HEADING_SIZE_RATIO = 1.18


@dataclass
class _Segment:
    words: list[Word]
    size: float
    bold: bool

    @property
    def bbox(self) -> BBox:
        return BBox.enclosing([w.bbox for w in self.words])

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class _RawPage:
    number: int
    width: float
    height: float
    flow_words: list[tuple[Word, float, bool]]
    segments: list[_Segment]
    tables: list[tuple[BBox, list[tuple[list[str], BBox]], list[Word]]]


@dataclass
class _OpenBlock:
    segments: list[_Segment] = field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        return BBox.enclosing([s.bbox for s in self.segments])

    @property
    def size(self) -> float:
        return self.segments[0].size


class PdfParser:
    """Layout-aware PDF parser built on pdfplumber.

    Tables are detected first and their words are kept out of the text flow. Remaining words are
    grouped into lines, lines are split at wide horizontal gaps (label/value columns are common in
    invoices), and segments are merged into paragraphs by font size, alignment and vertical gap.
    """

    formats = frozenset({DocumentFormat.PDF})
    version = "pdf-2"

    def parse(self, data: bytes) -> DocumentModel:
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                raw_pages = [self._collect(page, number) for number, page in enumerate(pdf.pages, start=1)]
                raw_meta: dict[str, Any] = dict(pdf.metadata or {})
        except PDFEncryptionError as exc:
            raise ParseError("PDF is encrypted; remove the password and drop it in again") from exc
        except PdfminerException as exc:
            if isinstance(exc.__cause__ or exc.__context__, PDFEncryptionError):
                raise ParseError("PDF is encrypted; remove the password and drop it in again") from exc
            raise ParseError(f"malformed or truncated PDF: {exc}") from exc
        except (PDFSyntaxError, PSException) as exc:
            raise ParseError(f"malformed or truncated PDF: {exc}") from exc

        # Font statistics are document-wide so a heading keeps its level across pages.
        body_size = self._body_size([item for raw in raw_pages for item in raw.flow_words])
        heading_sizes = sorted(
            {s.size for raw in raw_pages for s in raw.segments if s.size >= body_size * HEADING_SIZE_RATIO},
            reverse=True,
        )
        pages = [self._build_page(raw, body_size, heading_sizes) for raw in raw_pages]
        metadata = {
            key.lower(): str(value)
            for key, value in raw_meta.items()
            if isinstance(value, str | int | float) and str(value).strip()
        }
        if not any(page.blocks for page in pages):
            raise ParseError("PDF has no extractable text layer (scanned documents need OCR)")
        return DocumentModel(format=DocumentFormat.PDF, pages=pages, metadata=metadata)

    def _collect(self, page: Any, number: int) -> _RawPage:
        raw_words: list[dict[str, Any]] = page.extract_words(
            extra_attrs=["size", "fontname"], keep_blank_chars=False, use_text_flow=False
        )
        tables = page.find_tables()
        table_boxes = [BBox(x0=t.bbox[0], top=t.bbox[1], x1=t.bbox[2], bottom=t.bbox[3]) for t in tables]

        flow_words: list[tuple[Word, float, bool]] = []
        table_words: list[list[Word]] = [[] for _ in tables]
        for raw in raw_words:
            word = Word(
                text=raw["text"],
                bbox=BBox(x0=raw["x0"], top=raw["top"], x1=raw["x1"], bottom=raw["bottom"]),
            )
            owner = next((i for i, box in enumerate(table_boxes) if box.contains_center_of(word.bbox)), None)
            if owner is None:
                flow_words.append(
                    (word, round(float(raw["size"]), 1), "bold" in str(raw["fontname"]).lower())
                )
            else:
                table_words[owner].append(word)

        table_rows: list[list[tuple[list[str], BBox]]] = []
        for table in tables:
            rows: list[tuple[list[str], BBox]] = []
            for cells, row in zip(table.extract(), table.rows, strict=False):
                values = [(cell or "").replace("\n", " ").strip() for cell in cells]
                if any(values):
                    x0, top, x1, bottom = row.bbox
                    rows.append((values, BBox(x0=x0, top=top, x1=x1, bottom=bottom)))
            table_rows.append(rows)
        return _RawPage(
            number=number,
            width=float(page.width),
            height=float(page.height),
            flow_words=flow_words,
            segments=self._segments(flow_words),
            tables=list(zip(table_boxes, table_rows, table_words, strict=True)),
        )

    def _build_page(self, raw: _RawPage, body_size: float, heading_sizes: list[float]) -> Page:
        pending: list[tuple[float, float, Block]] = []
        for block in self._merge(raw.segments, body_size):
            first = block.segments[0]
            text = self._block_text(block)
            looks_like_field = ":" in text
            by_size = first.size in heading_sizes
            by_weight = (
                first.bold and len(block.segments) == 1 and len(first.words) <= 8 and first.size >= body_size
            )
            is_heading = (by_size or by_weight) and not looks_like_field
            level = (heading_sizes.index(first.size) + 1) if by_size else len(heading_sizes) + 1
            bbox = block.bbox
            pending.append(
                (
                    bbox.top,
                    bbox.x0,
                    Block(
                        id="",
                        page=raw.number,
                        kind=BlockKind.HEADING if is_heading else BlockKind.PARAGRAPH,
                        text=text,
                        bbox=bbox,
                        geometry=GeometryKind.LAYOUT,
                        heading_level=level if is_heading else None,
                        words=[w for s in block.segments for w in s.words],
                    ),
                )
            )

        for box, table_rows, words in raw.tables:
            if not table_rows:
                continue
            rows = [values for values, _ in table_rows]
            pending.append(
                (
                    box.top,
                    box.x0,
                    Block(
                        id="",
                        page=raw.number,
                        kind=BlockKind.TABLE,
                        text="\n".join(" | ".join(row) for row in rows),
                        bbox=box,
                        geometry=GeometryKind.LAYOUT,
                        rows=rows,
                        row_boxes=[row_box for _, row_box in table_rows],
                        words=words,
                    ),
                )
            )

        pending.sort(key=lambda item: (round(item[0], 0), item[1]))
        blocks = [
            block.model_copy(update={"id": f"p{raw.number}-b{index}"})
            for index, (_, _, block) in enumerate(pending)
        ]
        return Page(number=raw.number, width=raw.width, height=raw.height, blocks=blocks)

    @staticmethod
    def _body_size(words: list[tuple[Word, float, bool]]) -> float:
        if not words:
            return 10.0
        counts: Counter[float] = Counter()
        for word, size, _ in words:
            counts[size] += len(word.text)
        return counts.most_common(1)[0][0]

    @staticmethod
    def _segments(words: list[tuple[Word, float, bool]]) -> list[_Segment]:
        ordered = sorted(words, key=lambda item: (item[0].bbox.top, item[0].bbox.x0))
        lines: list[list[tuple[Word, float, bool]]] = []
        for item in ordered:
            if lines and abs(lines[-1][0][0].bbox.top - item[0].bbox.top) <= LINE_TOLERANCE:
                lines[-1].append(item)
            else:
                lines.append([item])

        segments: list[_Segment] = []
        for line in lines:
            line.sort(key=lambda item: item[0].bbox.x0)
            current: list[tuple[Word, float, bool]] = [line[0]]
            for prev, item in itertools.pairwise(line):
                gap = item[0].bbox.x0 - prev[0].bbox.x1
                if gap > prev[1] * COLUMN_GAP_FACTOR or abs(item[1] - prev[1]) > 0.6:
                    segments.append(PdfParser._segment(current))
                    current = [item]
                else:
                    current.append(item)
            segments.append(PdfParser._segment(current))
        return segments

    @staticmethod
    def _segment(items: list[tuple[Word, float, bool]]) -> _Segment:
        return _Segment(
            words=[w for w, _, _ in items],
            size=max(size for _, size, _ in items),
            bold=all(bold for _, _, bold in items),
        )

    @staticmethod
    def _merge(segments: list[_Segment], body_size: float) -> list[_OpenBlock]:
        blocks: list[_OpenBlock] = []
        for segment in segments:
            target = None
            sbox = segment.bbox
            for block in reversed(blocks[-4:]):
                bbox = block.bbox
                last = block.segments[-1].bbox
                vertical_gap = sbox.top - last.bottom
                same_style = abs(block.size - segment.size) <= 0.6 and block.segments[-1].bold == segment.bold
                aligned = abs(sbox.x0 - bbox.x0) <= body_size * 1.5
                if same_style and aligned and -1.0 <= vertical_gap <= segment.size * 0.9:
                    target = block
                    break
            if target is None:
                blocks.append(_OpenBlock(segments=[segment]))
            else:
                target.segments.append(segment)
        return blocks

    @staticmethod
    def _block_text(block: _OpenBlock) -> str:
        lines: list[str] = []
        for segment in block.segments:
            text = segment.text
            if lines and lines[-1].endswith("-") and not lines[-1].endswith(" -"):
                lines[-1] = lines[-1][:-1] + text
            else:
                lines.append(text)
        return "\n".join(lines)
