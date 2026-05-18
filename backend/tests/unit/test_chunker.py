from __future__ import annotations

from docforge.chunking.chunker import StructureAwareChunker, estimate_tokens
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
from tests.conftest import ParseFn


def test_chunks_never_cross_a_heading(parse: ParseFn) -> None:
    model = parse("contracts/helios-master-services-agreement.docx")
    chunks = StructureAwareChunker(max_tokens=400).chunk(model)
    blocks = {b.id: b for b in model.iter_blocks()}

    for chunk in chunks:
        sections = {tuple(chunk.heading_path)}
        assert len(sections) == 1
        assert all(blocks[span.block_id].kind is not BlockKind.HEADING for span in chunk.spans)
    assert [c.heading_path[-1] for c in chunks if c.heading_path][:3] == [
        "Master Services Agreement",
        "1. Services",
        "2. Term and Renewal",
    ]


def test_long_tables_split_by_rows_with_header_repeated(parse: ParseFn) -> None:
    model = parse("invoices/2026-04/cedar-pine-legal-CP-3307.pdf")
    chunks = [c for c in StructureAwareChunker(max_tokens=120).chunk(model) if c.is_table]

    assert len(chunks) > 3
    for chunk in chunks:
        assert chunk.text.startswith("Description | Qty | Unit Price | Amount")
        assert chunk.token_count <= 140
    row_lines = [line for c in chunks for line in c.text.splitlines()[1:]]
    assert len(row_lines) == 28


def test_table_chunk_lineage_points_at_its_rows_not_the_whole_table(parse: ParseFn) -> None:
    model = parse("invoices/2026-04/cedar-pine-legal-CP-3307.pdf")
    table = next(b for b in model.iter_blocks() if b.kind is BlockKind.TABLE)
    later = [c for c in StructureAwareChunker(max_tokens=120).chunk(model) if c.is_table][2]

    assert len(later.spans) == 2
    header, rows = later.spans
    assert header.bbox.top == table.bbox.top
    assert rows.bbox.top > header.bbox.bottom
    assert rows.bbox.bottom < table.bbox.bottom


def test_chunk_hash_is_stable_and_content_sensitive(parse: ParseFn) -> None:
    model = parse("contracts/orion-labs-mutual-nda.docx")
    chunker = StructureAwareChunker()
    first = [c.content_hash for c in chunker.chunk(model)]
    assert first == [c.content_hash for c in chunker.chunk(model)]
    assert len(set(first)) == len(first)


def test_version_reflects_configuration() -> None:
    assert StructureAwareChunker(200).version != StructureAwareChunker(300).version
    assert estimate_tokens("") == 0
    assert estimate_tokens("Total Due: $1,234.50") > 4


def test_an_oversized_paragraph_is_split_into_word_windows() -> None:
    words = [
        Word(
            text=f"word{i}",
            bbox=BBox(
                x0=72 + (i % 10) * 40,
                top=72 + (i // 10) * 14,
                x1=108 + (i % 10) * 40,
                bottom=84 + (i // 10) * 14,
            ),
        )
        for i in range(400)
    ]
    block = Block(
        id="p1-b0",
        page=1,
        kind=BlockKind.PARAGRAPH,
        text=" ".join(w.text for w in words),
        bbox=BBox.enclosing([w.bbox for w in words]),
        geometry=GeometryKind.LAYOUT,
        words=words,
    )
    model = DocumentModel(
        format=DocumentFormat.PDF, pages=[Page(number=1, width=612, height=792, blocks=[block])]
    )

    chunks = StructureAwareChunker(max_tokens=100, overlap_blocks=0).chunk(model)

    assert len(chunks) >= 4
    assert all(chunk.token_count <= 100 for chunk in chunks)
    assert " ".join(c.text for c in chunks).split() == [w.text for w in words]
    first, last = chunks[0].spans[0].bbox, chunks[-1].spans[0].bbox
    assert first.top == 72 and first.bottom < last.top
