from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from docforge.extraction.schemas.common import CurrencyCode, Money


class Contract(BaseModel):
    """A commercial agreement between two parties."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, description="Agreement title as written at the top of the document")
    party_a: str = Field(min_length=1, description="First party named in the preamble")
    party_b: str = Field(min_length=1, description="Second party named in the preamble")
    effective_date: date
    end_date: date | None = Field(
        default=None, description="Date the initial term ends or the agreement expires"
    )
    term_months: int | None = Field(default=None, ge=1, le=600)
    governing_law: str | None = Field(default=None, description="Jurisdiction, e.g. State of California")
    contract_value: Money | None = Field(
        default=None, description="Total fees or estimated value for the term"
    )
    currency: CurrencyCode | None = None
    auto_renews: bool | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)

    @field_validator("end_date")
    @classmethod
    def ends_after_start(cls, end: date | None, info: ValidationInfo) -> date | None:
        start = info.data.get("effective_date")
        if end is not None and start is not None and end <= start:
            raise ValueError(f"end_date {end} must be after effective_date {start}")
        return end
