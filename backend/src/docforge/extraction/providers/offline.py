"""Deterministic, network-free extraction provider.

It mimics what an LLM does with the same envelope contract: a first pass that reads values the way
they are printed, and a repair pass that normalizes the fields the validator complained about. It
cannot fix documents that are internally inconsistent, which is exactly when a human should look.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from docforge.chunking.chunker import estimate_tokens
from docforge.domain.documents import Block, BlockKind, DocumentModel
from docforge.extraction.envelope import FieldError
from docforge.extraction.pricing import price_usage
from docforge.extraction.providers.base import ExtractionRequest, ProviderResponse

Envelope = dict[str, Any]
RuleSet = Callable[[DocumentModel], dict[str, Envelope]]

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTH_DATE = rf"(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}}"
_DATE = rf"(\d{{4}}-\d{{2}}-\d{{2}}|{_MONTH_DATE}|\d{{1,2}}/\d{{1,2}}/\d{{4}})"
_MONEY = r"((?:[A-Z]{3}\s?)?\$?\s?-?[\d,]+(?:\.\d{1,2})?)"
_NUMBER_WORDS = {
    "thirty": 30,
    "sixty": 60,
    "ninety": 90,
    "twelve": 12,
    "twenty-four": 24,
    "thirty-six": 36,
}


@dataclass(frozen=True)
class _Line:
    text: str
    block: Block


def _lines(document: DocumentModel) -> list[_Line]:
    return [
        _Line(text=line.strip(), block=block)
        for block in document.iter_blocks()
        if block.kind is not BlockKind.TABLE
        for line in block.text.split("\n")
        if line.strip()
    ]


def _paragraphs(document: DocumentModel) -> list[_Line]:
    return [
        _Line(text=" ".join(block.text.split()), block=block)
        for block in document.iter_blocks()
        if block.kind is BlockKind.PARAGRAPH
    ]


def _clean(value: str) -> str:
    value = value.strip().rstrip(",;")
    if len(value) > 1 and value.endswith(".") and value[-2].isdigit():
        value = value[:-1]
    return value


def _envelope(value: Any, evidence: str | None, block: Block | None, confidence: float) -> Envelope:
    return {
        "value": value,
        "evidence": evidence,
        "source_block": block.id if block else None,
        "confidence": confidence,
    }


def _missing(confidence: float = 0.85) -> Envelope:
    return _envelope(None, None, None, confidence)


def _find(lines: list[_Line], pattern: str, confidence: float, group: int = 1) -> Envelope | None:
    regex = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        match = regex.search(line.text)
        if match:
            value = _clean(match.group(group))
            return _envelope(value, value, line.block, confidence)
    return None


def _first_heading(document: DocumentModel) -> Block | None:
    return next((b for b in document.iter_blocks() if b.kind is BlockKind.HEADING), None)


def _invoice_rules(document: DocumentModel) -> dict[str, Envelope]:
    lines = _lines(document)
    fields: dict[str, Envelope] = {}

    fields["invoice_number"] = _find(
        lines, r"invoice\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]+)", 0.97
    ) or _missing(0.3)

    vendor = _first_heading(document)
    fields["vendor_name"] = (
        _envelope(vendor.text.split("\n")[0], vendor.text.split("\n")[0], vendor, 0.82)
        if vendor
        else _missing(0.2)
    )

    customer = _find(lines, r"bill\s*to\s*:\s*(.+)", 0.9)
    if customer is None:
        blocks = list(document.iter_blocks())
        for index, block in enumerate(blocks[:-1]):
            if block.kind is BlockKind.HEADING and block.text.strip().lower() == "bill to":
                name = blocks[index + 1].text.split("\n")[0]
                customer = _envelope(name, name, blocks[index + 1], 0.88)
                break
    fields["customer_name"] = customer or _missing(0.5)

    fields["issue_date"] = _find(lines, rf"(?:invoice|issue)\s*date\s*:?\s*{_DATE}", 0.95) or _missing(0.2)
    due = _find(lines, rf"due\s*date\s*:?\s*{_DATE}", 0.94)
    if due is None:
        receipt = _find(lines, r"(due\s+(?:up)?on\s+receipt)", 0.55)
        due = _envelope(None, receipt["evidence"], None, 0.55) if receipt else _missing(0.6)
        if receipt:
            due["source_block"] = receipt["source_block"]
    fields["due_date"] = due

    currency = _find(lines, r"currency\s*:\s*([A-Z]{3})", 0.96)
    if currency is None and "$" in document.text():
        currency = _envelope("USD", "$", None, 0.6)
    fields["currency"] = currency or _missing(0.3)

    fields["purchase_order"] = _find(
        lines, r"(?:PO|purchase\s+order)\s*(?:number|no\.?|#)?\s*:\s*(\S+)", 0.93
    ) or (_missing(0.9))

    fields["line_items"] = _line_items(document)
    fields["subtotal"] = _find(lines, rf"sub\s*-?total\s*:?\s*{_MONEY}", 0.93) or _missing(0.3)
    fields["tax"] = _find(lines, rf"(?:tax|vat)(?:\s*\([^)]*\))?\s*:?\s*{_MONEY}", 0.9) or _envelope(
        "0.00", None, None, 0.6
    )
    fields["total"] = _find(
        lines, rf"(?<![a-z])(?:total\s+due|amount\s+due|balance\s+due|total)\s*:?\s*{_MONEY}", 0.93
    ) or _missing(0.2)
    return fields


_COLUMN_ALIASES = {
    "description": ("description", "item", "service"),
    "quantity": ("qty", "quantity", "hours", "units"),
    "unit_price": ("unit price", "rate", "price"),
    "amount": ("amount", "total", "line total"),
}


def _line_items(document: DocumentModel) -> Envelope:
    tables = [b for b in document.iter_blocks() if b.kind is BlockKind.TABLE and b.rows]
    items: list[dict[str, Any]] = []
    first_block: Block | None = None
    evidence: str | None = None
    columns: dict[str, int] | None = None
    for table in tables:
        assert table.rows is not None
        header = [cell.lower().strip() for cell in table.rows[0]]
        mapping = {
            key: next((i for i, cell in enumerate(header) if cell in aliases), -1)
            for key, aliases in _COLUMN_ALIASES.items()
        }
        if mapping["description"] < 0 or mapping["amount"] < 0:
            continue
        if columns is not None and mapping != columns:
            continue
        columns = mapping
        for row in table.rows[1:]:
            values = {key: row[index] if 0 <= index < len(row) else "" for key, index in mapping.items()}
            if not values["description"]:
                continue
            items.append(
                {
                    "description": values["description"],
                    "quantity": values["quantity"] or "1",
                    "unit_price": values["unit_price"] or values["amount"],
                    "amount": values["amount"],
                }
            )
            if first_block is None:
                first_block, evidence = table, values["description"]
    if not items:
        return _envelope([], None, None, 0.5)
    return _envelope(items, evidence, first_block, 0.9)


def _contract_rules(document: DocumentModel) -> dict[str, Envelope]:
    text_lines = _paragraphs(document)
    fields: dict[str, Envelope] = {}

    title = _first_heading(document)
    fields["title"] = _envelope(title.text, title.text, title, 0.9) if title else _missing(0.2)

    parties = re.compile(
        r"between\s+(.+?)\s+\(\s*[\"“]?([\w ]+?)[\"”]?\s*\)\s+and\s+(.+?)\s+\(\s*[\"“]?([\w ]+?)[\"”]?\s*\)",
        re.IGNORECASE,
    )
    fields["party_a"] = _missing(0.2)
    fields["party_b"] = _missing(0.2)
    for line in text_lines:
        match = parties.search(line.text)
        if match:
            fields["party_a"] = _envelope(match.group(1), match.group(1), line.block, 0.92)
            fields["party_b"] = _envelope(match.group(3), match.group(3), line.block, 0.92)
            break

    fields["effective_date"] = _find(
        text_lines, rf"(?:as of|effective date\s*:?)\s*{_DATE}", 0.93
    ) or _missing(0.2)
    fields["end_date"] = _find(
        text_lines, rf"(?:ends on|expire on|expires on|until|terminates on)\s+{_DATE}", 0.86
    ) or _missing(0.6)

    term = _find(
        text_lines,
        r"(?:initial term|term of [\w ]+?)\s+(?:of this agreement\s+)?(?:is|by)\s+"
        r"([\w-]+\s*\(\d+\))\s+months",
        0.85,
    )
    if term is not None:
        digits = re.search(r"\((\d+)\)", str(term["value"]))
        term["value"] = int(digits.group(1)) if digits else None
    fields["term_months"] = term or _missing(0.7)

    law = _find(
        text_lines,
        r"governed by the laws of (?:the )?((?:State|Commonwealth) of [A-Z][a-z]+(?: [A-Z][a-z]+)?)",
        0.95,
    )
    fields["governing_law"] = law or _missing(0.5)

    value = _find(
        text_lines,
        r"(?:total fees of|contract value for the initial term is|extended term totals|aggregate fees of)"
        r"\s+(\$[\d,]+(?:\.\d{2})?)",
        0.88,
    )
    fields["contract_value"] = value or _missing(0.9)
    if value is not None and str(value["value"]).startswith("$"):
        fields["currency"] = _envelope("USD", value["evidence"], None, 0.75)
        fields["currency"]["source_block"] = value["source_block"]
    else:
        fields["currency"] = _missing(0.9)

    if any(
        re.search(r"(?:shall|will) not automatically renew", line.text, re.IGNORECASE) for line in text_lines
    ):
        renew = _find(text_lines, r"((?:shall|will) not automatically renew)", 0.9)
        assert renew is not None
        renew["value"] = False
        fields["auto_renews"] = renew
    else:
        renew = _find(text_lines, r"(automatically renew)", 0.9)
        if renew is not None:
            renew["value"] = True
        fields["auto_renews"] = renew or _missing(0.5)

    notice = _find(
        text_lines, r"([\w -]+\s*\(\d+\)|\d+)\s+days[\u2019']?\s+(?:prior\s+)?written notice", 0.84
    )
    if notice is not None:
        raw = str(notice["value"])
        digits = re.search(r"\((\d+)\)", raw) or re.search(r"(\d+)", raw)
        notice["value"] = int(digits.group(1)) if digits else _NUMBER_WORDS.get(raw.strip().lower())
    fields["notice_period_days"] = notice or _missing(0.6)
    return fields


def _to_decimal_string(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    cleaned = re.sub(r"[^\d.\-]", "", raw)
    try:
        return str(Decimal(cleaned).quantize(Decimal("0.01")))
    except InvalidOperation:
        return raw


def _to_iso_date(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return raw


def _normalize_line_items(raw: Any) -> Any:
    if not isinstance(raw, list):
        return raw
    normalized: list[Any] = []
    for item in raw:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        fixed = dict(item)
        quantity = _to_decimal_string(fixed.get("quantity"))
        try:
            fixed["quantity"] = (
                format(Decimal(quantity).normalize(), "f") if isinstance(quantity, str) else quantity
            )
        except InvalidOperation:
            fixed["quantity"] = quantity
        for key in ("unit_price", "amount"):
            fixed[key] = _to_decimal_string(fixed.get(key))
        normalized.append(fixed)
    return normalized


_NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "issue_date": _to_iso_date,
    "due_date": _to_iso_date,
    "effective_date": _to_iso_date,
    "end_date": _to_iso_date,
    "subtotal": _to_decimal_string,
    "tax": _to_decimal_string,
    "total": _to_decimal_string,
    "contract_value": _to_decimal_string,
    "line_items": _normalize_line_items,
}

RULES: dict[str, RuleSet] = {"invoice": _invoice_rules, "contract": _contract_rules}


class OfflineProvider:
    """Rule-based provider with the same contract as the LLM providers.

    Token usage is estimated from the prompt that would have been sent, and priced as the model the
    pipeline is configured to use, so the run ledger shows realistic (flagged as estimated) costs.
    """

    name = "offline"

    def __init__(self, priced_as: str, rules: dict[str, RuleSet] | None = None) -> None:
        self.model = "offline-rules"
        self._priced_as = priced_as
        self._rules = rules or RULES

    async def extract(self, request: ExtractionRequest) -> ProviderResponse:
        rules = self._rules.get(request.schema_name)
        if rules is None:
            output: dict[str, Any] = {}
        elif request.previous_output is not None and request.errors:
            output = self._repair(request.previous_output, request.errors)
        else:
            output = rules(request.document)

        prompt_tokens = estimate_tokens(request.document_text) + estimate_tokens(
            json.dumps(request.json_schema)
        )
        if request.previous_output is not None:
            prompt_tokens += estimate_tokens(json.dumps(request.previous_output, default=str))
        usage = price_usage(
            self._priced_as,
            prompt_tokens + 180,
            estimate_tokens(json.dumps(output, default=str)),
            estimated=True,
        )
        return ProviderResponse(output=output, usage=usage, model=self.model)

    @staticmethod
    def _repair(previous: dict[str, Any], errors: list[FieldError]) -> dict[str, Any]:
        repaired: dict[str, Any] = json.loads(json.dumps(previous, default=str))
        for name in {error.field for error in errors}:
            normalizer = _NORMALIZERS.get(name)
            envelope = repaired.get(name)
            if normalizer is None or not isinstance(envelope, dict):
                continue
            before = envelope.get("value")
            after = normalizer(before)
            if after != before:
                envelope["value"] = after
            else:
                # The value was already well-formed, so the document itself disagrees with the rule.
                envelope["confidence"] = round(float(envelope.get("confidence", 0.5)) * 0.6, 3)
        return repaired
