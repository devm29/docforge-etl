from __future__ import annotations

from dataclasses import dataclass, field

from docforge.domain.documents import BBox, Block, Page, Word

LETTER_WIDTH = 612.0
LETTER_HEIGHT = 792.0
LINE_HEIGHT = 1.35

# Helvetica advance widths (1/1000 em) for printable ASCII, from the standard AFM metrics.
# The viewer renders reconstructed pages in Helvetica/Arial, so synthesized word boxes line up.
_HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)  # fmt: skip


BOLD_FACTOR = 1.08


def text_width(text: str, font_size: float, *, bold: bool = False) -> float:
    units = sum(_HELVETICA[ord(c) - 32] if 32 <= ord(c) < 127 else 556 for c in text)
    return units * font_size / 1000 * (BOLD_FACTOR if bold else 1.0)


@dataclass(frozen=True)
class _Placed:
    text: str
    x: float
    line: int
    width: float


def wrap(text: str, width: float, font_size: float, *, bold: bool = False) -> tuple[list[_Placed], int]:
    """Greedy word wrap with real glyph widths. Returns placed words and the line count."""
    space = text_width(" ", font_size, bold=bold)
    placed: list[_Placed] = []
    x, line = 0.0, 0
    for token in text.split():
        token_width = text_width(token, font_size, bold=bold)
        if x > 0 and x + token_width > width:
            x, line = 0.0, line + 1
        placed.append(_Placed(token, x, line, min(token_width, width)))
        x += token_width + space
    return placed, line + 1


@dataclass
class FlowLayout:
    """Synthesizes page geometry for formats that have reading order but no fixed layout.

    The boxes are approximate, but they keep provenance consistent: every block still has a page
    and a rectangle, so the viewer can highlight it on a rendered text page.
    """

    width: float = LETTER_WIDTH
    height: float = LETTER_HEIGHT
    margin: float = 72.0
    pages: list[Page] = field(default_factory=list)
    _cursor: float = 0.0

    def __post_init__(self) -> None:
        self._new_page()

    @property
    def content_width(self) -> float:
        return self.width - 2 * self.margin

    @property
    def page_number(self) -> int:
        return len(self.pages)

    def place(self, height: float, spacing: float = 6.0) -> tuple[int, BBox]:
        height = min(height, self.height - 2 * self.margin)
        if self._cursor + height > self.height - self.margin:
            self._new_page()
        top = self._cursor
        self._cursor += height + spacing
        box = BBox(x0=self.margin, top=top, x1=self.width - self.margin, bottom=top + height)
        return self.page_number, box

    def place_text(
        self, text: str, font_size: float, spacing: float, *, bold: bool = False
    ) -> list[tuple[int, BBox, list[Word]]]:
        """Places wrapped text, continuing on the next page when it runs past the bottom margin.

        Returns one (page, box, words) piece per page the text lands on. Text that fits on a page
        is never split; it moves to the next page whole, like a paragraph with widow control.
        """
        placed, lines = wrap(text, self.content_width, font_size, bold=bold)
        line_height = font_size * LINE_HEIGHT
        per_page = max(1, int((self.height - 2 * self.margin) // line_height))
        pieces: list[tuple[int, BBox, list[Word]]] = []
        first = 0
        while first < lines:
            remaining = lines - first
            available = int((self.height - self.margin - self._cursor) // line_height)
            if available < 1 or (remaining <= per_page and available < remaining):
                self._new_page()
                available = per_page
            count = min(available, remaining)
            last = first + count == lines
            page, bbox = self.place(count * line_height, spacing if last else 0.0)
            words = [
                Word(
                    text=item.text,
                    bbox=BBox(
                        x0=bbox.x0 + item.x,
                        top=bbox.top + (item.line - first) * line_height,
                        x1=bbox.x0 + item.x + item.width,
                        bottom=bbox.top + (item.line - first + 1) * line_height,
                    ),
                )
                for item in placed
                if first <= item.line < first + count
            ]
            pieces.append((page, bbox, words))
            first += count
        return pieces

    def add(self, block: Block) -> None:
        self.pages[block.page - 1].blocks.append(block)

    def _new_page(self) -> None:
        self.pages.append(Page(number=len(self.pages) + 1, width=self.width, height=self.height))
        self._cursor = self.margin
