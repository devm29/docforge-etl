from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from docforge.domain.records import ExtractionStatus, FieldStatus, MatchKind
from docforge.domain.statuses import (
    DeadLetterStatus,
    DocumentStatus,
    ReviewStatus,
    RunStatus,
    RunTrigger,
    StageStatus,
    VersionStatus,
)
from docforge.sources.base import normalize_prefix


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](ApiModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class BBoxOut(ApiModel):
    x0: float
    top: float
    x1: float
    bottom: float


class CreateRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(default="fs", min_length=1, max_length=32)
    prefix: str = Field(
        default="", max_length=512, description="Folder or file path, relative to the source root"
    )
    force: bool = Field(default=False, description="Reprocess every document, even unchanged ones")
    bypass_cache: bool = Field(default=False, description="Recompute every stage instead of reusing outputs")

    @field_validator("prefix")
    @classmethod
    def _valid_prefix(cls, value: str) -> str:
        return normalize_prefix(value)


class RunOut(ApiModel):
    id: uuid.UUID
    trigger: RunTrigger
    source: str
    prefix: str
    force: bool
    bypass_cache: bool
    status: RunStatus
    pipeline_version: str
    docs_seen: int
    docs_changed: int
    docs_unchanged: int
    docs_removed: int
    docs_succeeded: int
    docs_failed: int
    docs_deduplicated: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_saved_usd: float
    cost_estimated: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    has_export: bool = False


class StageSummaryOut(ApiModel):
    stage: str
    executed: int
    cached: int
    failed: int
    skipped: int
    items_in: int
    items_out: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_saved_usd: float
    duration_ms: int


class DeadLetterOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    version_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    uri: str
    stage: str
    error_type: str
    error: str
    attempts: int
    retryable: bool
    status: DeadLetterStatus
    created_at: datetime
    replayed_at: datetime | None
    replay_run_id: uuid.UUID | None


class RunDetailOut(ApiModel):
    run: RunOut
    stages: list[StageSummaryOut]
    dead_letters: list[DeadLetterOut]


class StageRunOut(ApiModel):
    id: uuid.UUID
    stage: str
    status: StageStatus
    attempts: int
    items_in: int
    items_out: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_saved_usd: float
    duration_ms: int
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    detail: dict[str, Any]


class TimelineDocumentOut(ApiModel):
    version_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    uri: str
    version_no: int
    version_status: VersionStatus
    stages: list[StageRunOut]


class TimelineOut(ApiModel):
    run_id: uuid.UUID
    documents: list[TimelineDocumentOut]
    total: int
    limit: int
    offset: int


class PageSizeOut(ApiModel):
    number: int
    width: float
    height: float
    label: str | None = None


class VersionOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    version_no: int
    status: VersionStatus
    content_hash: str | None
    size_bytes: int
    format: str | None
    page_count: int | None
    pages: list[PageSizeOut]
    error: str | None
    created_at: datetime
    processed_at: datetime | None


class DocumentOut(ApiModel):
    id: uuid.UUID
    source: str
    uri: str
    filename: str
    format: str | None
    kind: str | None
    status: DocumentStatus
    version_no: int | None
    page_count: int | None
    extraction_status: ExtractionStatus | None
    average_confidence: float | None
    pending_reviews: int
    updated_at: datetime


class DocumentDetailOut(DocumentOut):
    content_hash: str | None
    current_version: VersionOut | None
    versions: list[VersionOut]
    pages: list[PageSizeOut]


class FieldOut(ApiModel):
    id: uuid.UUID
    path: str
    value: JsonValue
    confidence: float
    model_confidence: float
    status: FieldStatus
    repaired: bool
    issues: list[str]
    evidence: str | None
    match: MatchKind
    block_key: str | None
    page: int | None
    bbox: BBoxOut | None
    review_item_id: uuid.UUID | None = None


class AttemptOut(ApiModel):
    attempt: int
    errors: list[str]


class ExtractionOut(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    schema_name: str
    schema_version: str
    status: ExtractionStatus
    data: dict[str, JsonValue]
    attempts: int
    repaired: bool
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    attempt_log: list[AttemptOut]
    created_at: datetime
    fields: list[FieldOut]


class WordOut(ApiModel):
    text: str
    bbox: BBoxOut


class BlockOut(ApiModel):
    id: str
    page: int
    kind: str
    geometry: str
    text: str
    bbox: BBoxOut
    heading_level: int | None
    rows: list[list[str]] | None
    cell_range: str | None
    words: list[WordOut]


class ChunkSpanOut(ApiModel):
    block_id: str
    page: int
    bbox: BBoxOut


class ChunkOut(ApiModel):
    id: uuid.UUID
    ordinal: int
    text: str
    heading_path: list[str]
    token_count: int
    page_start: int
    page_end: int
    spans: list[ChunkSpanOut]
    is_table: bool


class DocumentRefOut(ApiModel):
    id: uuid.UUID
    filename: str
    uri: str
    kind: str | None


class ReviewItemOut(ApiModel):
    id: uuid.UUID
    status: ReviewStatus
    reason: str
    created_at: datetime
    resolved_at: datetime | None
    reviewer: str | None
    note: str | None
    original_value: JsonValue
    resolved_value: JsonValue
    schema_name: str
    extraction_id: uuid.UUID
    extraction_status: ExtractionStatus
    document: DocumentRefOut
    version_id: uuid.UUID
    field: FieldOut


class ApproveReviewIn(BaseModel):
    """The reviewer is taken from the authenticated caller, never from the request body."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class EditReviewIn(ApproveReviewIn):
    value: JsonValue


class ReviewResultOut(ApiModel):
    item: ReviewItemOut
    extraction_status: ExtractionStatus


class SearchHitOut(ApiModel):
    chunk_id: uuid.UUID
    document: DocumentRefOut
    score: float
    text: str
    heading_path: list[str]
    page_start: int
    spans: list[ChunkSpanOut]


class SearchOut(ApiModel):
    query: str
    model: str
    hits: list[SearchHitOut]


class OverviewOut(ApiModel):
    documents_total: int
    documents_by_status: dict[str, int]
    documents_by_kind: dict[str, int]
    chunks_total: int
    runs_total: int
    tokens_total: int
    cost_total_usd: float
    cost_saved_usd: float
    cost_estimated: bool
    pending_reviews: int
    open_dead_letters: int
    cache_entries: int
    cache_hits: int
    recent_runs: list[RunOut]


class SchemaOut(ApiModel):
    name: str
    version: str
    description: str
    instructions: str
    fields: list[str]
    json_schema: dict[str, Any]


class HealthOut(ApiModel):
    status: Literal["ok", "degraded"]
    database: bool
    queue: bool
    provider: str
    model: str
    embedder: str
