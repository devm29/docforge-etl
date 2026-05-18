from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from docforge.extraction.schemas.common import CurrencyCode, Money, close_enough


class InvoiceLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0, description="Billed quantity or hours")
    unit_price: Money
    amount: Money

    @field_validator("amount")
    @classmethod
    def amount_is_quantity_times_price(cls, amount: Decimal, info: ValidationInfo) -> Decimal:
        quantity, price = info.data.get("quantity"), info.data.get("unit_price")
        if quantity is not None and price is not None:
            expected = (quantity * price).quantize(Decimal("0.01"))
            if not close_enough(amount, expected):
                raise ValueError(
                    f"amount {amount} does not equal quantity {quantity} x unit_price {price} = {expected}"
                )
        return amount


class Invoice(BaseModel):
    """A vendor invoice billed to the company."""

    model_config = ConfigDict(extra="forbid")

    invoice_number: str = Field(min_length=1, description="Identifier printed by the vendor, e.g. INV-1042")
    vendor_name: str = Field(min_length=1, description="Company that issued the invoice")
    customer_name: str | None = Field(default=None, description="Billed party from the Bill To section")
    issue_date: date
    due_date: date | None = Field(default=None, description="Null when payment is due on receipt")
    currency: CurrencyCode
    purchase_order: str | None = None
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    subtotal: Money
    tax: Money = Decimal("0.00")
    total: Money = Field(description="Total amount due as printed on the invoice")

    @field_validator("due_date")
    @classmethod
    def due_after_issue(cls, due: date | None, info: ValidationInfo) -> date | None:
        issued = info.data.get("issue_date")
        if due is not None and issued is not None and due < issued:
            raise ValueError(f"due_date {due} is before issue_date {issued}")
        return due

    @field_validator("subtotal")
    @classmethod
    def subtotal_matches_lines(cls, subtotal: Decimal, info: ValidationInfo) -> Decimal:
        items: list[InvoiceLineItem] | None = info.data.get("line_items")
        if items:
            lines = sum((item.amount for item in items), Decimal("0.00"))
            if not close_enough(subtotal, lines):
                raise ValueError(f"subtotal {subtotal} does not equal the sum of line item amounts {lines}")
        return subtotal

    @field_validator("total")
    @classmethod
    def total_is_subtotal_plus_tax(cls, total: Decimal, info: ValidationInfo) -> Decimal:
        subtotal, tax = info.data.get("subtotal"), info.data.get("tax")
        if subtotal is not None and tax is not None and not close_enough(total, subtotal + tax):
            raise ValueError(
                f"total {total} does not equal subtotal {subtotal} + tax {tax} = {subtotal + tax}"
            )
        return total
