from __future__ import annotations

from docforge.extraction.grounding import locate
from tests.conftest import ParseFn


def test_exact_quote_resolves_to_word_box(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    provenance = locate(model, "INV-24017", "INV-24017", "p1-b3")
    assert provenance.match == "exact"
    assert provenance.block_id == "p1-b3"
    assert provenance.bbox is not None and provenance.bbox.width < 80


def test_formatting_differences_still_ground(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/helios-cloud-HC-1180.pdf")
    provenance = locate(model, "22684.00", None, None)
    assert provenance.match == "exact"
    assert provenance.page == 1


def test_near_miss_quotes_ground_fuzzily(parse: ParseFn) -> None:
    model = parse("contracts/helios-master-services-agreement.docx")
    provenance = locate(model, "x", "governed by the laws of the State of Califomia", None)
    assert provenance.match == "fuzzy"


def test_cited_block_is_the_fallback_and_nothing_is_none(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    assert locate(model, "unrelated", "not on the page at all", "p1-b0").match == "block"
    assert locate(model, "unrelated", "not on the page at all", None).match == "none"


def test_short_values_are_not_grounded_anywhere_on_the_page(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    blocks = {b.id: b for b in model.iter_blocks()}
    usd = next(b for b in blocks.values() if "USD" in b.text.split())

    unsourced = locate(model, "USD", None, None)
    assert unsourced.match == "none"

    cited = locate(model, "USD", None, usd.id)
    assert cited.match == "exact" and cited.block_id == usd.id


def test_distinctive_values_are_still_searched_document_wide(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    provenance = locate(model, "INV-24017", "a quote the model made up", None)
    assert provenance.match == "exact"
