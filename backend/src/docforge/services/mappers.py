from __future__ import annotations

import uuid
from typing import Any

from docforge.db.models import (
    ChunkRow,
    DeadLetter,
    Document,
    DocumentVersion,
    Extraction,
    ExtractionField,
    ReviewItem,
    Run,
    StageRun,
)
from docforge.domain.records import ExtractionStatus, FieldStatus
from docforge.services.dto import (
    BBoxOut,
    ChunkOut,
    ChunkSpanOut,
    DeadLetterOut,
    DocumentRefOut,
    FieldOut,
    PageSizeOut,
    ReviewItemOut,
    RunOut,
    StageRunOut,
    VersionOut,
)


def run_out(run: Run) -> RunOut:
    return RunOut.model_validate(
        {
            **{c: getattr(run, c) for c in RunOut.model_fields if hasattr(run, c) and c != "has_export"},
            "cost_usd": float(run.cost_usd),
            "cost_saved_usd": float(run.cost_saved_usd),
            "has_export": run.export_path is not None,
        }
    )


def version_out(version: DocumentVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        run_id=version.run_id,
        version_no=version.version_no,
        status=version.status,
        content_hash=version.content_hash,
        size_bytes=version.size_bytes,
        format=version.format,
        page_count=version.page_count,
        pages=[PageSizeOut.model_validate(page) for page in version.page_sizes or []],
        error=version.error,
        created_at=version.created_at,
        processed_at=version.processed_at,
    )


def bbox_out(x0: float | None, top: float | None, x1: float | None, bottom: float | None) -> BBoxOut | None:
    if x0 is None or top is None or x1 is None or bottom is None:
        return None
    return BBoxOut(x0=x0, top=top, x1=x1, bottom=bottom)


def field_out(field: ExtractionField, review_item_id: uuid.UUID | None = None) -> FieldOut:
    return FieldOut(
        id=field.id,
        path=field.path,
        value=field.value,
        confidence=field.confidence,
        model_confidence=field.model_confidence,
        status=FieldStatus(field.status),
        repaired=field.repaired,
        issues=[str(issue) for issue in field.issues],
        evidence=field.evidence,
        match=field.match,
        block_key=field.block_key,
        page=field.page,
        bbox=bbox_out(field.x0, field.top, field.x1, field.bottom),
        review_item_id=review_item_id,
    )


def chunk_out(chunk: ChunkRow) -> ChunkOut:
    return ChunkOut(
        id=chunk.id,
        ordinal=chunk.ordinal,
        text=chunk.text,
        heading_path=[str(h) for h in chunk.heading_path],
        token_count=chunk.token_count,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        spans=[ChunkSpanOut.model_validate(span) for span in chunk.spans],
        is_table=chunk.is_table,
    )


def stage_run_out(stage: StageRun) -> StageRunOut:
    return StageRunOut(
        id=stage.id,
        stage=stage.stage,
        status=stage.status,
        attempts=stage.attempts,
        items_in=stage.items_in,
        items_out=stage.items_out,
        input_tokens=stage.input_tokens,
        output_tokens=stage.output_tokens,
        cost_usd=float(stage.cost_usd),
        cost_saved_usd=float(stage.cost_saved_usd),
        duration_ms=stage.duration_ms,
        started_at=stage.started_at,
        finished_at=stage.finished_at,
        error=stage.error,
        detail=dict(stage.detail),
    )


def dead_letter_out(letter: DeadLetter, document: Document) -> DeadLetterOut:
    return DeadLetterOut(
        id=letter.id,
        run_id=letter.run_id,
        version_id=letter.version_id,
        document_id=letter.document_id,
        filename=document.filename,
        uri=document.uri,
        stage=letter.stage,
        error_type=letter.error_type,
        error=letter.error,
        attempts=letter.attempts,
        retryable=letter.retryable,
        status=letter.status,
        created_at=letter.created_at,
        replayed_at=letter.replayed_at,
        replay_run_id=letter.replay_run_id,
    )


def document_ref(document: Document) -> DocumentRefOut:
    return DocumentRefOut(id=document.id, filename=document.filename, uri=document.uri, kind=document.kind)


def review_out(
    item: ReviewItem, field: ExtractionField, extraction: Extraction, document: Document
) -> ReviewItemOut:
    resolved: Any = item.resolved_value
    return ReviewItemOut(
        id=item.id,
        status=item.status,
        reason=item.reason,
        created_at=item.created_at,
        resolved_at=item.resolved_at,
        reviewer=item.reviewer,
        note=item.note,
        original_value=item.original_value,
        resolved_value=resolved,
        schema_name=extraction.schema_name,
        extraction_id=extraction.id,
        extraction_status=ExtractionStatus(extraction.status),
        document=document_ref(document),
        version_id=extraction.version_id,
        field=field_out(field, item.id if item.status == "pending" else None),
    )
