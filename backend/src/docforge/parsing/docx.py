from __future__ import annotations

import io
import re
import zipfile

import docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from docforge.domain.documents import (
    BBox,
    Block,
    BlockKind,
    DocumentFormat,
    DocumentModel,
    GeometryKind,
    Word,
)
from docforge.errors import ParseError
from docforge.parsing.layout import FlowLayout

_HEADING_STYLE = re.compile(r"^(Heading|Title)\s*(\d*)$", re.IGNORECASE)
BODY_SIZE = 11.0
ROW_HEIGHT = 18.0


class DocxParser:
    formats = frozenset({DocumentFormat.DOCX})
    version = "docx-4"

    def parse(self, data: bytes) -> DocumentModel:
        try:
            document: DocxDocument = docx.Document(io.BytesIO(data))
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise ParseError(f"malformed DOCX: {exc}") from exc

        layout = FlowLayout()
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                self._paragraph(layout, item)
            elif isinstance(item, Table):
                self._table(layout, item)

        props = document.core_properties
        metadata = {
            key: value
            for key, value in {"title": props.title, "author": props.author, "subject": props.subject}.items()
            if value
        }
        pages = [page for page in layout.pages if page.blocks] or layout.pages[:1]
        if not any(page.blocks for page in pages):
            raise ParseError("DOCX contains no text")
        return DocumentModel(format=DocumentFormat.DOCX, pages=pages, metadata=metadata)

    @staticmethod
    def _heading_level(paragraph: Paragraph) -> int | None:
        style_name = paragraph.style.name if paragraph.style is not None else ""
        match = _HEADING_STYLE.match(style_name or "")
        if match is None:
            return None
        if match.group(1).lower() == "title":
            return 1
        return int(match.group(2) or 1) + 1

    def _paragraph(self, layout: FlowLayout, paragraph: Paragraph) -> None:
        text = " ".join(paragraph.text.split())
        if not text:
            return
        level = self._heading_level(paragraph)
        size = BODY_SIZE + (8 - 2 * min(level, 3) if level else 0)
        pieces = layout.place_text(text, size, spacing=10.0 if level else 6.0, bold=bool(level))
        for page, bbox, words in pieces:
            layout.add(
                Block(
                    id=f"p{page}-b{len(layout.pages[page - 1].blocks)}",
                    page=page,
                    kind=BlockKind.HEADING if level else BlockKind.PARAGRAPH,
                    text=text if len(pieces) == 1 else " ".join(word.text for word in words),
                    bbox=bbox,
                    geometry=GeometryKind.FLOW,
                    heading_level=level,
                    words=words,
                )
            )

    def _table(self, layout: FlowLayout, table: Table) -> None:
        rows: list[list[str]] = []
        for row in table.rows:
            cells: list[str] = []
            seen: set[int] = set()
            for cell in row.cells:
                # Merged cells are returned once per spanned grid column.
                if id(cell._tc) in seen:
                    continue
                seen.add(id(cell._tc))
                cells.append(" ".join(cell.text.split()))
            if any(cells):
                rows.append(cells)
        if not rows:
            return
        page, bbox = layout.place(ROW_HEIGHT * len(rows), spacing=10.0)
        columns = max(len(row) for row in rows)
        col_width = bbox.width / columns
        words = [
            Word(
                text=value,
                bbox=BBox(
                    x0=bbox.x0 + c * col_width,
                    top=bbox.top + r * ROW_HEIGHT,
                    x1=bbox.x0 + (c + 1) * col_width,
                    bottom=bbox.top + (r + 1) * ROW_HEIGHT,
                ),
            )
            for r, row in enumerate(rows)
            for c, value in enumerate(row)
            if value
        ]
        layout.add(
            Block(
                id=f"p{page}-b{len(layout.pages[page - 1].blocks)}",
                page=page,
                kind=BlockKind.TABLE,
                text="\n".join(" | ".join(row) for row in rows),
                bbox=bbox,
                geometry=GeometryKind.FLOW,
                rows=rows,
                row_boxes=[
                    BBox(
                        x0=bbox.x0,
                        top=bbox.top + r * ROW_HEIGHT,
                        x1=bbox.x1,
                        bottom=bbox.top + (r + 1) * ROW_HEIGHT,
                    )
                    for r in range(len(rows))
                ],
                words=words,
            )
        )
