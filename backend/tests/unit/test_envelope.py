from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from docforge.extraction.envelope import build_envelope_schema, parse_envelope, validation_errors
from docforge.extraction.schemas.contract import Contract
from docforge.extraction.schemas.invoice import Invoice


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk(value))
    return found


def test_envelope_schema_is_strict_for_structured_outputs() -> None:
    schema = build_envelope_schema(Invoice)
    assert schema["required"] == list(Invoice.model_fields)

    for node in _walk(schema):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        assert not {"pattern", "minLength", "maximum", "default", "title"} & node.keys()


def test_decimals_are_presented_as_strings_and_fields_are_nullable() -> None:
    schema = build_envelope_schema(Invoice)
    total = schema["properties"]["total"]["properties"]["value"]
    assert {"type": "null"} in total["anyOf"]
    assert {"type": "string"} in [{k: v for k, v in o.items() if k == "type"} for o in total["anyOf"]]
    contract_value = build_envelope_schema(Contract)["properties"]["contract_value"]["properties"]["value"]
    assert [o["type"] for o in contract_value["anyOf"]] == ["string", "null"]


def test_parse_envelope_tolerates_missing_and_malformed_fields() -> None:
    envelopes = parse_envelope(
        Invoice,
        {"invoice_number": {"value": "INV-1", "evidence": "INV-1", "confidence": 7}, "total": "oops"},
    )
    assert envelopes["invoice_number"].value == "INV-1"
    assert envelopes["invoice_number"].confidence == 1.0
    assert envelopes["total"].value is None and envelopes["total"].confidence == 0.0
    assert set(envelopes) == set(Invoice.model_fields)


def test_business_rules_report_the_field_that_broke_them() -> None:
    with pytest.raises(ValidationError) as caught:
        Invoice.model_validate(
            {
                "invoice_number": "X-1",
                "vendor_name": "Acme",
                "issue_date": "2026-03-01",
                "due_date": "2026-02-01",
                "currency": "USD",
                "line_items": [
                    {"description": "Widget", "quantity": "2", "unit_price": "5.00", "amount": "11.00"}
                ],
                "subtotal": "10.00",
                "tax": "0.00",
                "total": "12.00",
            }
        )
    paths = {error.path for error in validation_errors(caught.value)}
    assert paths == {"due_date", "line_items.0.amount", "total"}
