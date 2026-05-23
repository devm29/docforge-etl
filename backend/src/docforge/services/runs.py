from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from docforge.db.models import Run
from docforge.db.repositories import DeadLetterRepository, RunRepository
from docforge.db.session import SessionFactory, transaction
from docforge.domain.statuses import RunTrigger
from docforge.errors import ConflictError, NotFoundError
from docforge.pipeline.queue import JobQueue
from docforge.services.dto import (
    CreateRunIn,
    Page,
    RunDetailOut,
    RunOut,
    StageSummaryOut,
    TimelineDocumentOut,
    TimelineOut,
)
from docforge.services.mappers import dead_letter_out, run_out, stage_run_out
from docforge.sinks.parquet import ParquetExporter
from docforge.sources.base import SourceRegistry

STAGE_ORDER = ("detect", "parse", "chunk", "embed", "extract", "load")


class RunService:
    def __init__(
        self,
        sessions: SessionFactory,
        queue: JobQueue,
        sources: SourceRegistry,
        exporter: ParquetExporter,
        pipeline_version: str,
        *,
        stale_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self._sessions = sessions
        self._queue = queue
        self._sources = sources
        self._exporter = exporter
        self._pipeline_version = pipeline_version
        self._stale_after = stale_after

    async def start(self, request: CreateRunIn, *, trigger: RunTrigger = "api") -> RunOut:
        """Queues a run. One run per source at a time: a second request gets 409 instead of
        spending money on a duplicate scan. A run stuck longer than the stale window no longer
        blocks (the worker's reaper takes care of it)."""
        self._sources.get(request.source)
        async with transaction(self._sessions) as session:
            since = datetime.now(UTC) - self._stale_after
            active = await RunRepository(session).active_for_source(request.source, since)
            if active is not None:
                raise ConflictError(
                    f"run {active.id} is already {active.status} for source '{request.source}'"
                )
            run = Run(
                trigger=trigger,
                source=request.source,
                prefix=request.prefix,
                force=request.force,
                bypass_cache=request.bypass_cache,
                status="queued",
                pipeline_version=self._pipeline_version,
            )
            session.add(run)
            await session.flush()
            result = run_out(run)
        await self._queue.enqueue_scan(result.id)
        return result

    async def page(self, limit: int, offset: int) -> Page[RunOut]:
        async with self._sessions() as session:
            runs, total = await RunRepository(session).page(limit, offset)
            return Page[RunOut](items=[run_out(r) for r in runs], total=total, limit=limit, offset=offset)

    async def detail(self, run_id: uuid.UUID) -> RunDetailOut:
        async with self._sessions() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run is None:
                raise NotFoundError(f"run {run_id} not found")
            summary = {
                row[0]: StageSummaryOut(
                    stage=row[0],
                    executed=row[1],
                    cached=row[2],
                    failed=row[3],
                    skipped=row[4],
                    items_in=int(row[5]),
                    items_out=int(row[6]),
                    input_tokens=int(row[7]),
                    output_tokens=int(row[8]),
                    cost_usd=float(row[9]),
                    cost_saved_usd=float(row[10]),
                    duration_ms=int(row[11]),
                )
                for row in await repo.stage_summary(run_id)
            }
            letters, _ = await DeadLetterRepository(session).page(
                status=None, run_id=run_id, limit=100, offset=0
            )
            return RunDetailOut(
                run=run_out(run),
                stages=[summary[name] for name in STAGE_ORDER if name in summary],
                dead_letters=[dead_letter_out(letter, document) for letter, document in letters],
            )

    async def timeline(self, run_id: uuid.UUID, *, limit: int, offset: int) -> TimelineOut:
        async with self._sessions() as session:
            repo = RunRepository(session)
            if await repo.get(run_id) is None:
                raise NotFoundError(f"run {run_id} not found")
            versions, total = await repo.timeline_versions(run_id, limit, offset)
            documents = {
                version.id: TimelineDocumentOut(
                    version_id=version.id,
                    document_id=document.id,
                    filename=document.filename,
                    uri=document.uri,
                    version_no=version.version_no,
                    version_status=version.status,
                    stages=[],
                )
                for version, document in versions
            }
            for stage in await repo.timeline_stages(run_id, list(documents)):
                documents[stage.version_id].stages.append(stage_run_out(stage))
            return TimelineOut(
                run_id=run_id, documents=list(documents.values()), total=total, limit=limit, offset=offset
            )

    async def export_file(self, run_id: uuid.UUID, table: str) -> Path:
        if table not in ParquetExporter.TABLES:
            raise NotFoundError(f"unknown export table '{table}'")
        async with self._sessions() as session:
            run = await RunRepository(session).get(run_id)
            if run is None:
                raise NotFoundError(f"run {run_id} not found")
        path = self._exporter.path_for(run_id, table)
        if not path.exists():
            async with transaction(self._sessions) as session:
                await self._exporter.export_run(session, run_id)
        return path
