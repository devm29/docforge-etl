from __future__ import annotations

from typing import Any

from docforge.domain.records import ExtractionStatus, TokenUsage
from docforge.extraction.extractor import SchemaExtractor
from docforge.extraction.providers.base import ExtractionRequest, ProviderResponse
from docforge.extraction.providers.offline import OfflineProvider
from docforge.extraction.registry import default_registry
from tests.conftest import ParseFn


def _env(value: Any, evidence: str | None = None, confidence: float = 0.95) -> dict[str, Any]:
    return {"value": value, "evidence": evidence, "source_block": None, "confidence": confidence}


def _invoice(total: str) -> dict[str, Any]:
    return {
        "invoice_number": _env("INV-24017", "INV-24017"),
        "vendor_name": _env("Northwind Office Supply", "Northwind Office Supply"),
        "customer_name": _env("Acme Robotics, Inc.", "Acme Robotics, Inc."),
        "issue_date": _env("2026-03-03", "2026-03-03"),
        "due_date": _env("2026-04-02", "2026-04-02"),
        "currency": _env("USD", "USD"),
        "purchase_order": _env("PO-88213", "PO-88213"),
        "line_items": _env([]),
        "subtotal": _env("8028.00", "8028.00"),
        "tax": _env("702.45", "702.45"),
        "total": _env(total, total),
    }


class ScriptedProvider:
    name = "scripted"
    model = "scripted-1"

    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self._outputs = outputs
        self.requests: list[ExtractionRequest] = []

    async def extract(self, request: ExtractionRequest) -> ProviderResponse:
        self.requests.append(request)
        output = self._outputs[min(len(self.requests), len(self._outputs)) - 1]
        return ProviderResponse(
            output=output,
            usage=TokenUsage(input_tokens=100, output_tokens=20, cost_usd=0.001),
            model=self.model,
        )


async def test_repair_loop_feeds_validation_errors_back(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    provider = ScriptedProvider([_invoice("9999.99"), _invoice("8730.45")])
    extractor = SchemaExtractor(provider, max_repairs=2)

    result = await extractor.extract(model, default_registry().get("invoice"))

    assert result.status is ExtractionStatus.VALID
    assert result.attempts == 2 and result.repaired
    assert result.usage.input_tokens == 200
    repair = provider.requests[1]
    assert repair.previous_output is not None
    assert [e.field for e in repair.errors] == ["total"]
    total = next(f for f in result.fields if f.path == "total")
    assert total.repaired and total.provenance.match == "exact"


async def test_repairs_are_bounded_and_failures_flagged(parse: ParseFn) -> None:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    provider = ScriptedProvider([_invoice("1.00")])
    extractor = SchemaExtractor(provider, max_repairs=1)

    result = await extractor.extract(model, default_registry().get("invoice"))

    assert result.status is ExtractionStatus.INVALID
    assert len(provider.requests) == 2
    total = next(f for f in result.fields if f.path == "total")
    assert total.issues and total.confidence < 0.5
    others = [f for f in result.fields if f.path != "total"]
    assert all(not f.issues for f in others)


async def test_offline_provider_covers_the_whole_corpus(parse: ParseFn) -> None:
    registry = default_registry()
    extractor = SchemaExtractor(OfflineProvider("claude-opus-5-5"), max_repairs=2)

    async def run(path: str) -> tuple[str, int, dict[str, Any]]:
        document = parse(path)
        spec = registry.classify(document)
        assert spec is not None
        result = await extractor.extract(document, spec)
        return result.status.value, result.attempts, result.data

    status, attempts, data = await run("invoices/2026-03/northwind-INV-24017.pdf")
    assert (status, attempts) == ("valid", 1)
    assert data["total"] == "8730.45" and len(data["line_items"]) == 4

    status, attempts, data = await run("invoices/2026-03/helios-cloud-HC-1180.pdf")
    assert (status, attempts) == ("valid", 2)
    assert data["issue_date"] == "2026-03-01" and data["total"] == "22684.00"

    status, attempts, _ = await run("invoices/2026-03/brightline-BL-55302.pdf")
    assert (status, attempts) == ("invalid", 3)

    document = parse("invoices/2026-03/quantum-print-QP-0931.pdf")
    quantum = await extractor.extract(document, registry.get("invoice"))
    due = next(f for f in quantum.fields if f.path == "due_date")
    assert quantum.status is ExtractionStatus.VALID and quantum.data["due_date"] is None
    assert due.confidence < 0.8

    status, _, data = await run("contracts/helios-master-services-agreement.docx")
    assert status == "valid"
    assert data["party_a"] == "Helios Cloud Services, Inc."
    assert data["notice_period_days"] == 60 and data["auto_renews"] is True


def test_classifier_ignores_reference_data(parse: ParseFn) -> None:
    registry = default_registry()
    assert registry.classify(parse("reference/vendor-master.csv")) is None
    contract = registry.classify(parse("contracts/harbor-way-lease-amendment.pdf"))
    assert contract is not None and contract.name == "contract"


def test_schema_version_changes_with_instructions() -> None:
    from dataclasses import replace

    spec = default_registry().get("invoice")
    assert replace(spec, instructions="different").version != spec.version
