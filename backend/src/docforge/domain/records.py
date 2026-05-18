from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from docforge.domain.documents import BBox


class ChunkSpan(BaseModel):
    block_id: str
    page: int
    bbox: BBox


class ChunkRecord(BaseModel):
    index: int
    text: str
    embed_text: str
    token_count: int
    heading_path: list[str] = Field(default_factory=list)
    page_start: int
    page_end: int
    spans: list[ChunkSpan]
    content_hash: str
    is_table: bool = False


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    estimated: bool = False

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 8),
            estimated=self.estimated or other.estimated,
        )


MatchKind = Literal["exact", "fuzzy", "block", "none"]


class FieldProvenance(BaseModel):
    page: int | None = None
    bbox: BBox | None = None
    block_id: str | None = None
    evidence: str | None = None
    match: MatchKind = "none"


class FieldStatus(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    EDITED = "edited"


class ExtractedField(BaseModel):
    path: str
    value: JsonValue
    confidence: float = Field(ge=0.0, le=1.0)
    model_confidence: float = Field(ge=0.0, le=1.0)
    provenance: FieldProvenance
    repaired: bool = False
    issues: list[str] = Field(default_factory=list)


class ExtractionStatus(StrEnum):
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    INVALID = "invalid"
    APPROVED = "approved"


class AttemptLog(BaseModel):
    attempt: int
    errors: list[str]


class ExtractionResult(BaseModel):
    schema_name: str
    schema_version: str
    status: ExtractionStatus
    data: dict[str, JsonValue]
    fields: list[ExtractedField]
    attempts: int
    repaired: bool
    model: str
    provider: str
    usage: TokenUsage
    attempt_log: list[AttemptLog] = Field(default_factory=list)
