from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from docforge.db.models import EmbeddingCacheRow, StageCacheEntry, StageRun
from docforge.db.session import SessionFactory
from docforge.pipeline.core import CachedOutput, StageMetrics, StageRecord


class DbStageCache:
    """Stage outputs memoized by idempotency key in Postgres (JSONB)."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def get(self, key: str) -> CachedOutput | None:
        async with self._sessions() as session, session.begin():
            entry = await session.scalar(
                update(StageCacheEntry)
                .where(StageCacheEntry.key == key)
                .values(hits=StageCacheEntry.hits + 1, last_hit_at=datetime.now(UTC))
                .returning(StageCacheEntry)
            )
            if entry is None:
                return None
            return CachedOutput(output=entry.output, metrics=StageMetrics.model_validate(entry.metrics))

    async def put(self, key: str, stage: str, output: BaseModel, metrics: StageMetrics) -> None:
        statement = insert(StageCacheEntry).values(
            key=key,
            stage=stage,
            output=output.model_dump(mode="json"),
            metrics=metrics.model_dump(mode="json"),
        )
        # Overwrite rather than ignore: an existing entry under this key is one the runner could
        # not load, otherwise it would not have recomputed the stage.
        async with self._sessions() as session, session.begin():
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[StageCacheEntry.key],
                    set_={"output": statement.excluded.output, "metrics": statement.excluded.metrics},
                )
            )


class DbLedger:
    """One row per stage execution. Committed immediately so the run timeline updates live."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def record(self, record: StageRecord) -> None:
        metrics = record.metrics
        async with self._sessions() as session, session.begin():
            session.add(
                StageRun(
                    run_id=record.run_id,
                    version_id=record.version_id,
                    stage=record.stage,
                    status=record.status,
                    idempotency_key=record.idempotency_key,
                    attempts=record.attempts,
                    items_in=metrics.items_in,
                    items_out=metrics.items_out,
                    input_tokens=metrics.input_tokens if record.status == "succeeded" else 0,
                    output_tokens=metrics.output_tokens if record.status == "succeeded" else 0,
                    cost_usd=Decimal(str(metrics.cost_usd)) if record.status == "succeeded" else Decimal(0),
                    cost_saved_usd=Decimal(str(record.cost_saved_usd)),
                    duration_ms=record.duration_ms,
                    detail={**metrics.detail, "cost_estimated": metrics.cost_estimated},
                    error=record.error,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                )
            )


class DbEmbeddingCache:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def get_many(self, model: str, text_hashes: list[str]) -> dict[str, list[float]]:
        if not text_hashes:
            return {}
        async with self._sessions() as session:
            rows = await session.execute(
                select(EmbeddingCacheRow.text_hash, EmbeddingCacheRow.embedding).where(
                    EmbeddingCacheRow.model == model, EmbeddingCacheRow.text_hash.in_(set(text_hashes))
                )
            )
            return {text_hash: [float(x) for x in vector] for text_hash, vector in rows.all()}

    async def put_many(self, model: str, vectors: dict[str, list[float]]) -> None:
        if not vectors:
            return
        async with self._sessions() as session, session.begin():
            await session.execute(
                insert(EmbeddingCacheRow)
                .values([{"model": model, "text_hash": h, "embedding": v} for h, v in vectors.items()])
                .on_conflict_do_nothing(index_elements=[EmbeddingCacheRow.model, EmbeddingCacheRow.text_hash])
            )
