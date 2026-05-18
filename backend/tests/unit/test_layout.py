from __future__ import annotations

from decimal import Decimal

import pytest

from docforge.parsing.layout import FlowLayout
from docforge.parsing.spreadsheet import _format_number


def test_long_paragraphs_continue_on_the_next_page() -> None:
    layout = FlowLayout()
    layout.place_text("Opening paragraph.", 11.0, spacing=6.0)
    pieces = layout.place_text(" ".join(["clause"] * 2500), 11.0, spacing=6.0)

    assert len(pieces) > 2
    assert [page for page, _, _ in pieces] == list(range(1, len(pieces) + 1))
    for _, bbox, words in pieces:
        assert bbox.bottom <= layout.height - layout.margin + 0.01
        assert words and all(w.bbox.bottom <= bbox.bottom + 0.01 for w in words)
    assert sum(len(words) for _, _, words in pieces) == 2500


def test_text_that_fits_on_one_page_moves_rather_than_splits() -> None:
    layout = FlowLayout()
    layout.place(600.0)
    pieces = layout.place_text(" ".join(["short"] * 60), 11.0, spacing=6.0)
    assert len(pieces) == 1 and pieces[0][0] == 2


@pytest.mark.parametrize(
    ("value", "number_format", "expected"),
    [
        (12.5, "0.00", "12.50"),
        (1.375, "0.00", "1.375"),
        (0.0035, "General", "0.0035"),
        (1e-7, "General", "0.0000001"),
        (100.0, "General", "100"),
        (Decimal("3"), "#,##0.00", "3.00"),
        (float("nan"), "General", "nan"),
        (float("inf"), "General", "inf"),
    ],
)
def test_spreadsheet_numbers_keep_their_exact_digits(
    value: float | Decimal, number_format: str, expected: str
) -> None:
    assert _format_number(value, number_format) == expected
