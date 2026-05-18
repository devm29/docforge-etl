from __future__ import annotations

import pytest
from fpdf import FPDF
from fpdf.enums import EncryptionMethod

from docforge.domain.documents import BlockKind, DocumentFormat, GeometryKind
from docforge.errors import ParseError, UnsupportedFormatError
from docforge.parsing.base import detect_format
from docforge.parsing.pdf import PdfParser
from docforge.parsing.spreadsheet import CsvParser
from tests.conftest import ParseFn


def test_detect_format_sniffs_magic_bytes_not_extension() -> None:
    assert detect_format("report.bin", b"%PDF-1.7 ...") is DocumentFormat.PDF
    assert detect_format("ledger.csv", b"a,b\n1,2\n") is DocumentFormat.CSV
    with pytest.raises(UnsupportedFormatError):
        detect_format("notes.txt", b"hello")


def test_pdf_invoice_has_headings_tables_and_word_boxes(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    blocks = list(model.iter_blocks())

    assert model.format is DocumentFormat.PDF
    assert blocks[0].kind is BlockKind.HEADING
    assert blocks[0].text == "Northwind Office Supply"
    table = next(b for b in blocks if b.kind is BlockKind.TABLE)
    assert table.rows is not None and table.rows[0] == ["Description", "Qty", "Unit Price", "Amount"]
    assert table.row_boxes is not None and len(table.row_boxes) == len(table.rows)

    page = model.page(1)
    for block in blocks:
        assert block.geometry is GeometryKind.LAYOUT
        assert 0 <= block.bbox.x0 < block.bbox.x1 <= page.width
        assert 0 <= block.bbox.top < block.bbox.bottom <= page.height
        for word in block.words:
            assert block.bbox.contains_center_of(word.bbox)


def test_pdf_table_split_across_pages_keeps_heading_levels(parse: ParseFn) -> None:
    model = parse("invoices/2026-04/cedar-pine-legal-CP-3307.pdf")
    assert model.page_count == 2
    tables = [b for b in model.iter_blocks() if b.kind is BlockKind.TABLE]
    assert [t.page for t in tables] == [1, 2]
    body_rows = sum(len(t.rows or []) - 1 for t in tables)
    assert body_rows == 28
    assert not any(b.kind is BlockKind.HEADING and ":" in b.text for b in model.iter_blocks())


def test_docx_uses_heading_styles_and_flow_geometry(parse: ParseFn) -> None:
    model = parse("contracts/helios-master-services-agreement.docx")
    headings = [b for b in model.iter_blocks() if b.kind is BlockKind.HEADING]
    assert headings[0].text == "Master Services Agreement"
    assert headings[0].heading_level == 1
    assert {h.heading_level for h in headings[1:]} == {2}
    paragraph = next(b for b in model.iter_blocks() if b.kind is BlockKind.PARAGRAPH)
    assert paragraph.geometry is GeometryKind.FLOW
    assert " ".join(w.text for w in paragraph.words) == paragraph.text
    assert model.metadata["title"] == "Master Services Agreement"


def test_xlsx_maps_cells_to_grid_blocks(parse: ParseFn) -> None:
    model = parse("invoices/2026-04/sierra-components-SC-90021.xlsx")
    blocks = list(model.iter_blocks())
    assert model.pages[0].label == "Invoice"
    assert blocks[0].kind is BlockKind.HEADING and blocks[0].cell_range == "A1:A1"
    assert any(b.text == "Invoice Number: SC-90021" for b in blocks)
    table = next(b for b in blocks if b.kind is BlockKind.TABLE)
    assert table.cell_range == "A10:D13"
    assert table.rows is not None and table.rows[1] == ["Brushless DC motor, 48V", "40", "86.5", "3460"]


def test_csv_becomes_a_single_table(parse: ParseFn) -> None:
    model = parse("reference/vendor-master.csv")
    [block] = list(model.iter_blocks())
    assert block.kind is BlockKind.TABLE
    assert block.rows is not None and len(block.rows) == 10


def test_truncated_pdf_is_a_permanent_parse_error() -> None:
    with pytest.raises(ParseError):
        PdfParser().parse(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog")


def test_encrypted_pdfs_and_bad_csv_bytes_are_permanent_parse_errors() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(text="Invoice")
    pdf.set_encryption(owner_password="owner", user_password="user", encryption_method=EncryptionMethod.RC4)
    with pytest.raises(ParseError, match="encrypted"):
        PdfParser().parse(bytes(pdf.output()))

    csv = b"name,amount\n" + b"x,1\n" * 2000 + b"caf\xe9,2\n"
    with pytest.raises(ParseError, match="UTF-8") as caught:
        CsvParser().parse(csv)
    assert not caught.value.retryable
