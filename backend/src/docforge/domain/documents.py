from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"


class GeometryKind(StrEnum):
    """How trustworthy a bounding box is.

    ``layout`` boxes come from a real rendered page (PDF). ``flow`` boxes are synthesized from
    reading order for formats without a fixed layout, and ``grid`` boxes map spreadsheet cells
    onto a uniform grid.
    """

    LAYOUT = "layout"
    FLOW = "flow"
    GRID = "grid"


class BBox(BaseModel):
    """Axis-aligned box in page points with a top-left origin, matching pdfplumber and the viewer."""

    model_config = ConfigDict(frozen=True)

    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def union(self, other: BBox) -> BBox:
        return BBox(
            x0=min(self.x0, other.x0),
            top=min(self.top, other.top),
            x1=max(self.x1, other.x1),
            bottom=max(self.bottom, other.bottom),
        )

    def contains_center_of(self, other: BBox) -> bool:
        cx = (other.x0 + other.x1) / 2
        cy = (other.top + other.bottom) / 2
        return self.x0 <= cx <= self.x1 and self.top <= cy <= self.bottom

    @classmethod
    def enclosing(cls, boxes: list[BBox]) -> BBox:
        if not boxes:
            raise ValueError("cannot enclose an empty list of boxes")
        result = boxes[0]
        for box in boxes[1:]:
            result = result.union(box)
        return result


class Word(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    bbox: BBox


class Block(BaseModel):
    id: str
    page: int = Field(ge=1)
    kind: BlockKind
    text: str
    bbox: BBox
    geometry: GeometryKind
    heading_level: int | None = None
    rows: list[list[str]] | None = None
    row_boxes: list[BBox] | None = None
    cell_range: str | None = None
    words: list[Word] = Field(default_factory=list)


class Page(BaseModel):
    number: int = Field(ge=1)
    width: float
    height: float
    label: str | None = None
    blocks: list[Block] = Field(default_factory=list)


class DocumentModel(BaseModel):
    format: DocumentFormat
    pages: list[Page]
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def iter_blocks(self) -> Iterator[Block]:
        for page in self.pages:
            yield from page.blocks

    def block_count(self) -> int:
        return sum(len(page.blocks) for page in self.pages)

    def text(self) -> str:
        return "\n\n".join(block.text for block in self.iter_blocks() if block.text)

    def page(self, number: int) -> Page:
        for page in self.pages:
            if page.number == number:
                return page
        raise KeyError(number)
