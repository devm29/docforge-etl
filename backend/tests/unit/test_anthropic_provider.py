from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from docforge.errors import ExtractionRefusedError, ProviderUnavailableError
from docforge.extraction.envelope import FieldError, build_envelope_schema
from docforge.extraction.providers.anthropic import FALLBACK_BETA, AnthropicProvider
from docforge.extraction.providers.base import ExtractionRequest, render_document
from docforge.extraction.schemas.invoice import Invoice
from tests.conftest import ParseFn


class FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response
        self._error = error

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _client(messages: FakeMessages) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


def _message(text: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=500
        ),
    )


@pytest.fixture
def request_for(parse: ParseFn) -> ExtractionRequest:
    model = parse("invoices/2026-03/northwind-INV-24017.pdf")
    return ExtractionRequest(
        schema_name="invoice",
        schema_description="Vendor invoice",
        instructions="Use ISO dates.",
        json_schema=build_envelope_schema(Invoice),
        document=model,
        document_text=render_document(model),
    )


async def test_sends_structured_output_request_and_prices_usage(request_for: ExtractionRequest) -> None:
    messages = FakeMessages(_message(json.dumps({"invoice_number": {"value": "INV-24017"}})))
    provider = AnthropicProvider(
        _client(messages), model="claude-opus-5-5", effort="low", refusal_fallback=True
    )

    response = await provider.extract(request_for)

    [call] = messages.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": request_for.json_schema}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert "[p1-b3] Invoice Number: INV-24017" in call["messages"][0]["content"]
    assert response.output["invoice_number"]["value"] == "INV-24017"
    assert response.usage.input_tokens == 1500
    assert response.usage.cost_usd == pytest.approx((1500 * 4 + 200 * 20) / 1_000_000)


async def test_repair_prompt_quotes_previous_answer_and_errors(request_for: ExtractionRequest) -> None:
    messages = FakeMessages(_message("{}"))
    provider = AnthropicProvider(
        _client(messages), model="claude-opus-5-5", effort="medium", refusal_fallback=False
    )
    repair = request_for.model_copy(
        update={
            "attempt": 2,
            "previous_output": {"total": {"value": "1.00"}},
            "errors": [
                FieldError(path="total", field="total", message="total does not add up", received="1.00")
            ],
        }
    )

    await provider.extract(repair)

    [call] = messages.calls
    prompt = call["messages"][0]["content"]
    assert len(call["messages"]) == 1
    assert "<validation_errors>" in prompt and "total: total does not add up" in prompt
    assert "fallbacks" not in call and call["betas"] == []


async def test_refusal_is_permanent(request_for: ExtractionRequest) -> None:
    provider = AnthropicProvider(
        _client(FakeMessages(_message("", stop_reason="refusal"))),
        model="claude-opus-5-5",
        effort="medium",
        refusal_fallback=True,
    )
    with pytest.raises(ExtractionRefusedError):
        await provider.extract(request_for)


async def test_rate_limits_are_transient(request_for: ExtractionRequest) -> None:
    response = httpx2.Response(429, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    error = anthropic.RateLimitError("slow down", response=response, body=None)
    provider = AnthropicProvider(
        _client(FakeMessages(error=error)), model="claude-opus-5-5", effort="medium", refusal_fallback=True
    )
    with pytest.raises(ProviderUnavailableError):
        await provider.extract(request_for)
