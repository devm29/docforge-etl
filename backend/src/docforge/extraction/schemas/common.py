from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import Field

Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2, description="Decimal amount, e.g. 1234.50")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code such as USD or EUR")]

CENT = Decimal("0.01")


def close_enough(a: Decimal, b: Decimal, tolerance: Decimal = CENT) -> bool:
    return abs(a - b) <= tolerance
