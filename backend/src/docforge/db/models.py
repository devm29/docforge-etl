from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from docforge.domain.records import ExtractionStatus, FieldStatus, MatchKind
from docforge.domain.statuses import (
    DeadLetterStatus,
    DocumentStatus,
    ReviewStatus,
    RunStatus,
    RunTrigger,
    StageStatus,
    VersionStatus,
    check_in,
    values_of,
)
from docforge.embedding.base import EMBEDDING_DIM


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={"ck": "ck_%(table_name)s_%(constraint_name)s"})
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _check(column: str, values: tuple[str, ...]) -> CheckConstraint:
    return CheckConstraint(check_in(column, values), name=column)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        _check("status", values_of(RunStatus)),
        _check("trigger", values_of(RunTrigger)),
    )

    id: Mapped[uuid.UUID] = _uuid()
    trigger: Mapped[RunTrigger] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))
    prefix: Mapped[str] = mapped_column(String(512), default="")
    force: Mapped[bool] = mapped_column(Boolean, default=False)
    bypass_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[RunStatus] = mapped_column(String(16), index=True)
    pipeline_version: Mapped[str] = mapped_column(String(64))
    docs_seen: Mapped[int] = mapped_column(Integer, default=0)
    docs_changed: Mapped[int] = mapped_column(Integer, default=0)
    docs_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    docs_removed: Mapped[int] = mapped_column(Integer, default=0)
    docs_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    docs_failed: Mapped[int] = mapped_column(Integer, default=0)
    docs_deduplicated: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal(0))
    cost_saved_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal(0))
    cost_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    export_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("source", "uri", name="uq_documents_source_uri"),
        _check("status", values_of(DocumentStatus)),
    )

    id: Mapped[uuid.UUID] = _uuid()
    source: Mapped[str] = mapped_column(String(32))
    uri: Mapped[str] = mapped_column(String(1024))
    filename: Mapped[str] = mapped_column(String(512))
    format: Mapped[str | None] = mapped_column(String(8))
    kind: Mapped[str | None] = mapped_column(String(32), index=True)
    fingerprint: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_versions.id", use_alter=True, ondelete="SET NULL", name="fk_documents_current_version"
        ),
    )
    status: Mapped[DocumentStatus] = mapped_column(String(16), default="pending")
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
        order_by="DocumentVersion.version_no",
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_versions_doc_no"),
        _check("status", values_of(VersionStatus)),
    )

    id: Mapped[uuid.UUID] = _uuid()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    blob_key: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    format: Mapped[str | None] = mapped_column(String(8))
    page_count: Mapped[int | None] = mapped_column(Integer)
    page_sizes: Mapped[list[Any] | None] = mapped_column(JSONB)
    status: Mapped[VersionStatus] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions", foreign_keys=[document_id])


class BlockRow(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("version_id", "block_key", name="uq_blocks_version_key"),)

    id: Mapped[uuid.UUID] = _uuid()
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    block_key: Mapped[str] = mapped_column(String(32))
    page: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    geometry: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    x0: Mapped[float] = mapped_column(Float)
    top: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    bottom: Mapped[float] = mapped_column(Float)
    heading_level: Mapped[int | None] = mapped_column(Integer)
    rows: Mapped[list[Any] | None] = mapped_column(JSONB)
    words: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    cell_range: Mapped[str | None] = mapped_column(String(32))


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_chunks_version_ordinal"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("is_current"),
        ),
        Index("ix_chunks_current", "document_id", postgresql_where=text("is_current")),
    )

    id: Mapped[uuid.UUID] = _uuid()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    token_count: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    spans: Mapped[list[Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_table: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created()


class EmbeddingCacheRow(Base):
    __tablename__ = "embedding_cache"

    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = _created()


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (
        UniqueConstraint("version_id", "schema_name", name="uq_extractions_version_schema"),
        _check("status", tuple(s.value for s in ExtractionStatus)),
    )

    id: Mapped[uuid.UUID] = _uuid()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"))
    schema_name: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer)
    repaired: Mapped[bool] = mapped_column(Boolean)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    attempt_log: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal(0))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    fields: Mapped[list[ExtractionField]] = relationship(
        back_populates="extraction", order_by="ExtractionField.ordinal", cascade="all, delete-orphan"
    )


class ExtractionField(Base):
    __tablename__ = "extraction_fields"
    __table_args__ = (
        UniqueConstraint("extraction_id", "path", name="uq_fields_extraction_path"),
        _check("status", tuple(s.value for s in FieldStatus)),
        _check("match", values_of(MatchKind)),
    )

    id: Mapped[uuid.UUID] = _uuid()
    extraction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extractions.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(128))
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    model_confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))
    repaired: Mapped[bool] = mapped_column(Boolean, default=False)
    issues: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    evidence: Mapped[str | None] = mapped_column(Text)
    match: Mapped[MatchKind] = mapped_column(String(8))
    block_key: Mapped[str | None] = mapped_column(String(32))
    page: Mapped[int | None] = mapped_column(Integer)
    x0: Mapped[float | None] = mapped_column(Float)
    top: Mapped[float | None] = mapped_column(Float)
    x1: Mapped[float | None] = mapped_column(Float)
    bottom: Mapped[float | None] = mapped_column(Float)

    extraction: Mapped[Extraction] = relationship(back_populates="fields")


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        Index("ix_review_items_pending", "created_at", postgresql_where=text("status = 'pending'")),
        _check("status", values_of(ReviewStatus)),
    )

    id: Mapped[uuid.UUID] = _uuid()
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_fields.id", ondelete="CASCADE"), unique=True
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(32))
    status: Mapped[ReviewStatus] = mapped_column(String(16), default="pending")
    original_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    resolved_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceRecord(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = _uuid()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(128), index=True)
    vendor_name: Mapped[str] = mapped_column(String(256), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(256))
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    purchase_order: Mapped[str | None] = mapped_column(String(128))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    line_items: Mapped[list[InvoiceLineItemRecord]] = relationship(
        cascade="all, delete-orphan", order_by="InvoiceLineItemRecord.ordinal"
    )


class InvoiceLineItemRecord(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = _uuid()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class ContractRecord(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = _uuid()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512))
    party_a: Mapped[str] = mapped_column(String(256))
    party_b: Mapped[str] = mapped_column(String(256))
    effective_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    term_months: Mapped[int | None] = mapped_column(Integer)
    governing_law: Mapped[str | None] = mapped_column(String(128))
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    auto_renews: Mapped[bool | None] = mapped_column(Boolean)
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StageRun(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (
        Index("ix_stage_runs_run_version", "run_id", "version_id"),
        _check("status", values_of(StageStatus)),
    )

    id: Mapped[uuid.UUID] = _uuid()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(16))
    status: Mapped[StageStatus] = mapped_column(String(16))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    items_in: Mapped[int] = mapped_column(Integer, default=0)
    items_out: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal(0))
    cost_saved_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal(0))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StageCacheEntry(Base):
    __tablename__ = "stage_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), index=True)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeadLetter(Base):
    __tablename__ = "dead_letters"
    __table_args__ = (_check("status", values_of(DeadLetterStatus)),)

    id: Mapped[uuid.UUID] = _uuid()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    error_type: Mapped[str] = mapped_column(String(64))
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    retryable: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[DeadLetterStatus] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = _created()
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replay_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class EntityRecord(Base):
    """Fallback typed sink for registered schemas that have no dedicated table."""

    __tablename__ = "entity_records"

    id: Mapped[uuid.UUID] = _uuid()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    schema_name: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
