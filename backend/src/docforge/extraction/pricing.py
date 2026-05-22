from __future__ import annotations

from decimal import Decimal

from docforge.domain.records import TokenUsage

# USD per million tokens (input, output), Anthropic first-party list prices.
MODEL_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-fable-5-1": (Decimal("10"), Decimal("50")),
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-opus-5": (Decimal("5"), Decimal("25")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10")),
    "claude-sonnet-4-6": (Decimal("3"), Decimal("15")),
    "claude-haiku-4-5": (Decimal("1"), Decimal("5")),
}

_MILLION = Decimal(1_000_000)


def price_usage(model: str, input_tokens: int, output_tokens: int, *, estimated: bool = False) -> TokenUsage:
    prices = MODEL_PRICES.get(model)
    if prices is None:
        return TokenUsage(
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=0.0, estimated=True
        )
    input_price, output_price = prices
    cost = (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price) / _MILLION
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=float(cost.quantize(Decimal("0.00000001"))),
        estimated=estimated,
    )
