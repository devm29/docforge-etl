from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docforge.db.models import (
    ChunkRow,
    Document,
    DocumentVersion,
    Extraction,
    ExtractionField,
    StageRun,
)

CHUNK_SCHEMA = pa.schema(
    [
        ("chunk_id", pa.string()),
        ("document_id", pa.string()),
        ("version_id", pa.string()),
        ("uri", pa.string()),
        ("ordinal", pa.int32()),
        ("text", pa.string()),
        ("heading_path", pa.list_(pa.string())),
        ("page_start", pa.int32()),
        ("page_end", pa.int32()),
        ("spans_json", pa.string()),
        ("embedding_model", pa.string()),
        ("embedding", pa.list_(pa.float32())),
    ]
)

FIELD_SCHEMA = pa.schema(
    [
        ("extraction_id", pa.string()),
        ("document_id", pa.string()),
        ("uri", pa.string()),
        ("schema_name", pa.string()),
        ("extraction_status", pa.string()),
        ("path", pa.string()),
        ("value_json", pa.string()),
        ("confidence", pa.float64()),
        ("field_status", pa.string()),
        ("match", pa.string()),
        ("page", pa.int32()),
        ("x0", pa.float64()),
        ("top", pa.float64()),
        ("x1", pa.float64()),
        ("bottom", pa.float64()),
        ("evidence", pa.string()),
    ]
)

STAGE_SCHEMA = pa.schema(
    [
        ("stage_run_id", pa.string()),
        ("version_id", pa.string()),
        ("uri", pa.string()),
        ("stage", pa.string()),
        ("status", pa.string()),
        ("attempts", pa.int32()),
        ("items_in", pa.int32()),
        ("items_out", pa.int32()),
        ("input_tokens", pa.int64()),
        ("output_tokens", pa.int64()),
        ("cost_usd", pa.float64()),
        ("cost_saved_usd", pa.float64()),
        ("duration_ms", pa.int64()),
        ("started_at", pa.timestamp("us", tz="UTC")),
    ]
)


class ParquetExporter:
    """Snapshots what a run produced (chunks, extracted fields, stage ledger) as Parquet files."""

    TABLES = ("chunks", "fields", "stages")

    def __init__(self, export_dir: Path) -> None:
        self._export_dir = export_dir

    def path_for(self, run_id: uuid.UUID, table: str) -> Path:
        return self._export_dir / str(run_id) / f"{table}.parquet"

    async def export_run(self, session: AsyncSession, run_id: uuid.UUID) -> Path:
        # Versions this run loaded. Not document_versions.run_id: a dead-letter replay loads a
        # version that was created by an earlier run.
        loaded = select(StageRun.version_id).where(
            StageRun.run_id == run_id, StageRun.stage == "load", StageRun.status == "succeeded"
        )
        chunk_rows = await session.execute(
            select(ChunkRow, Document.uri)
            .join(Document, Document.id == ChunkRow.document_id)
            .where(ChunkRow.version_id.in_(loaded))
            .order_by(Document.uri, ChunkRow.ordinal)
        )
        chunks: list[dict[str, Any]] = [
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "version_id": str(chunk.version_id),
                "uri": uri,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "heading_path": [str(h) for h in chunk.heading_path],
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "spans_json": json.dumps(chunk.spans),
                "embedding_model": chunk.embedding_model,
                "embedding": [float(x) for x in chunk.embedding],
            }
            for chunk, uri in chunk_rows.all()
        ]

        field_rows = await session.execute(
            select(ExtractionField, Extraction, Document.uri)
            .join(Extraction, Extraction.id == ExtractionField.extraction_id)
            .join(Document, Document.id == Extraction.document_id)
            .where(Extraction.version_id.in_(loaded))
            .order_by(Document.uri, ExtractionField.ordinal)
        )
        fields: list[dict[str, Any]] = [
            {
                "extraction_id": str(extraction.id),
                "document_id": str(extraction.document_id),
                "uri": uri,
                "schema_name": extraction.schema_name,
                "extraction_status": extraction.status,
                "path": field.path,
                "value_json": json.dumps(field.value),
                "confidence": field.confidence,
                "field_status": field.status,
                "match": field.match,
                "page": field.page,
                "x0": field.x0,
                "top": field.top,
                "x1": field.x1,
                "bottom": field.bottom,
                "evidence": field.evidence,
            }
            for field, extraction, uri in field_rows.all()
        ]

        stage_rows = await session.execute(
            select(StageRun, Document.uri)
            .join(DocumentVersion, DocumentVersion.id == StageRun.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(StageRun.run_id == run_id)
            .order_by(StageRun.started_at)
        )
        stages: list[dict[str, Any]] = [
            {
                "stage_run_id": str(stage.id),
                "version_id": str(stage.version_id),
                "uri": uri,
                "stage": stage.stage,
                "status": stage.status,
                "attempts": stage.attempts,
                "items_in": stage.items_in,
                "items_out": stage.items_out,
                "input_tokens": stage.input_tokens,
                "output_tokens": stage.output_tokens,
                "cost_usd": float(stage.cost_usd),
                "cost_saved_usd": float(stage.cost_saved_usd),
                "duration_ms": stage.duration_ms,
                "started_at": stage.started_at,
            }
            for stage, uri in stage_rows.all()
        ]

        target = self._export_dir / str(run_id)
        await asyncio.to_thread(
            self._write,
            target,
            {
                "chunks": (chunks, CHUNK_SCHEMA),
                "fields": (fields, FIELD_SCHEMA),
                "stages": (stages, STAGE_SCHEMA),
            },
        )
        return target

    @staticmethod
    def _write(target: Path, tables: dict[str, tuple[list[dict[str, Any]], pa.Schema]]) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for name, (rows, schema) in tables.items():
            table = pa.Table.from_pylist(rows, schema=schema)
            tmp = target / f".{name}.parquet.{os.getpid()}.tmp"
            pq.write_table(table, tmp, compression="zstd")
            tmp.replace(target / f"{name}.parquet")
