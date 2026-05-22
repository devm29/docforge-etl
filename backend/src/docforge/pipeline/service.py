from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docforge.db.models import DeadLetter, Document, DocumentVersion, Extraction, Run, StageRun
from docforge.db.session import SessionFactory, transaction
from docforge.domain.statuses import (
    ACTIVE_RUN_STATUSES,
    IN_FLIGHT_VERSION_STATUSES,
    TERMINAL_RUN_STATUSES,
    VersionOutcome,
)
from docforge.errors import NotFoundError
from docforge.logs import get_logger
from docforge.pipeline.core import DocumentRef, PipelineHalt, StageFailed
from docforge.pipeline.queue import JobQueue
from docforge.pipeline.runner import DagRunner
from docforge.sinks.entities import EntitySink
from docforge.sinks.parquet import ParquetExporter
from docforge.sinks.vectors import PgVectorSink
from docforge.sources.base import SourceRegistry

log = get_logger(__name__)


@dataclass(frozen=True)
class ScanSummary:
    seen: int
    changed: int
    unchanged: int
    removed: int

    @classmethod
    def of(cls, run: Run) -> ScanSummary:
        return cls(run.docs_seen, run.docs_changed, run.docs_unchanged, run.docs_removed)


@dataclass(frozen=True)
class _Failure:
    stage: str
    error_type: str
    error: str
    attempts: int
    retryable: bool


class PipelineService:
    """Coordinates a run: scan the source, fan out changed documents, account for every outcome.

    Every job is safe to run more than once, because the queue may deliver it twice (a worker
    crash after the work but before the ack) and the reaper re-enqueues anything that stalls.
    A version's terminal status and the run counters change in the same transaction, guarded by
    the version still being in flight, so each document is counted exactly once.
    """

    def __init__(
        self,
        *,
        sessions: SessionFactory,
        sources: SourceRegistry,
        runner: DagRunner,
        queue: JobQueue,
        exporter: ParquetExporter,
        vectors: PgVectorSink,
        entities: EntitySink,
        stale_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self._sessions = sessions
        self._sources = sources
        self._runner = runner
        self._queue = queue
        self._exporter = exporter
        self._vectors = vectors
        self._entities = entities
        self._stale_after = stale_after

    @property
    def version(self) -> str:
        return self._runner.version

    async def scan(self, run_id: uuid.UUID) -> ScanSummary:
        async with transaction(self._sessions) as session:
            run = await session.get(Run, run_id, with_for_update=True)
            if run is None:
                raise NotFoundError(f"run {run_id} not found")
            summary = ScanSummary.of(run)
            resume: list[uuid.UUID] | None = None
            if run.status == "running":
                # An earlier attempt committed the scan; it may have died before enqueueing everything.
                resume = list(await session.scalars(self._in_flight_versions(run_id)))
            elif run.status not in ("queued", "scanning"):
                log.info("scan.skipped", run_id=str(run_id), status=run.status)
                return summary
            else:
                run.status = "scanning"
                run.started_at = run.started_at or datetime.now(UTC)
                source_name, prefix, force = run.source, run.prefix, run.force
        if resume is not None:
            await self._enqueue_or_finalize(run_id, resume)
            return summary

        connector = self._sources.get(source_name)
        scope = connector.uri_scope(prefix)
        seen = unchanged = 0
        seen_uris: set[str] = set()
        queued: list[uuid.UUID] = []
        unchanged_ids: list[uuid.UUID] = []
        async with transaction(self._sessions) as session:
            # Runs over the same source take turns, so version numbers never collide.
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"scan:{source_name}"))))
            run = await session.get(Run, run_id, with_for_update=True, populate_existing=True)
            if run is None or run.status != "scanning":
                return ScanSummary.of(run) if run is not None else ScanSummary(0, 0, 0, 0)

            async for obj in connector.list_objects(prefix):
                seen += 1
                seen_uris.add(obj.uri)
                document = await session.scalar(
                    select(Document).where(Document.source == obj.source, Document.uri == obj.uri)
                )
                # A permanently failed fingerprint is not retried on every scan; it needs new
                # bytes or an explicit replay from the dead-letter queue.
                is_settled = (
                    document is not None
                    and document.fingerprint == obj.fingerprint
                    and document.status in ("ready", "failed")
                    and document.removed_at is None
                )
                if is_settled and not force:
                    assert document is not None
                    unchanged += 1
                    unchanged_ids.append(document.id)
                    continue
                if document is None:
                    document = Document(
                        source=obj.source, uri=obj.uri, filename=obj.filename, fingerprint=obj.fingerprint
                    )
                    session.add(document)
                    await session.flush()
                latest = await session.scalar(
                    select(func.max(DocumentVersion.version_no)).where(
                        DocumentVersion.document_id == document.id
                    )
                )
                version = DocumentVersion(
                    document_id=document.id,
                    run_id=run_id,
                    version_no=(latest or 0) + 1,
                    fingerprint=obj.fingerprint,
                    size_bytes=obj.size_bytes,
                    status="queued",
                )
                session.add(version)
                document.fingerprint = obj.fingerprint
                document.filename = obj.filename
                document.status = "processing"
                document.removed_at = None
                await session.flush()
                queued.append(version.id)

            if seen_uris:
                removed = await self._mark_removed(session, source_name, scope, seen_uris)
            else:
                # An empty listing is far more often a missing mount or a typo than a real mass
                # deletion, so it never retires anything.
                log.warning("scan.removal_skipped", run_id=str(run_id), scope=scope)
                removed = 0
            avoided, estimated = await self._avoided_cost(session, unchanged_ids)
            run.docs_seen, run.docs_changed = seen, len(queued)
            run.docs_unchanged, run.docs_removed = unchanged, removed
            run.cost_saved_usd = avoided
            run.cost_estimated = estimated
            run.status = "running"

        log.info("scan.done", run_id=str(run_id), seen=seen, changed=len(queued), unchanged=unchanged)
        await self._enqueue_or_finalize(run_id, queued)
        return ScanSummary(seen, len(queued), unchanged, removed)

    async def _enqueue_or_finalize(self, run_id: uuid.UUID, versions: list[uuid.UUID]) -> None:
        for version_id in versions:
            await self._queue.enqueue_process(run_id, version_id)
        if not versions:
            await self.finalize_if_done(run_id)

    @staticmethod
    def _in_flight_versions(run_id: uuid.UUID) -> Select[uuid.UUID]:
        replayed = select(DeadLetter.version_id).where(DeadLetter.replay_run_id == run_id)
        return select(DocumentVersion.id).where(
            or_(DocumentVersion.run_id == run_id, DocumentVersion.id.in_(replayed)),
            DocumentVersion.status.in_(IN_FLIGHT_VERSION_STATUSES),
        )

    @staticmethod
    async def _avoided_cost(session: AsyncSession, document_ids: list[uuid.UUID]) -> tuple[Decimal, bool]:
        """What re-extracting the unchanged documents would have cost, based on their last extraction."""
        if not document_ids:
            return Decimal(0), False
        total, estimated = (
            await session.execute(
                select(
                    func.coalesce(func.sum(Extraction.cost_usd), 0),
                    func.coalesce(func.bool_or(Extraction.provider == "offline"), False),
                ).where(Extraction.document_id.in_(document_ids), Extraction.is_current)
            )
        ).one()
        return Decimal(total), bool(estimated)

    async def _mark_removed(self, session: AsyncSession, source: str, scope: str, seen: set[str]) -> int:
        filters = [Document.source == source, Document.removed_at.is_(None)]
        if scope:
            filters.append(or_(Document.uri == scope, Document.uri.startswith(f"{scope}/", autoescape=True)))
        removed = 0
        for document in await session.scalars(select(Document).where(*filters)):
            if document.uri in seen:
                continue
            document.removed_at = datetime.now(UTC)
            document.status = "removed"
            await self._vectors.retire(session, document.id)
            await self._entities.retire(session, document.id)
            removed += 1
        return removed

    async def process(self, run_id: uuid.UUID, version_id: uuid.UUID) -> VersionOutcome | str:
        async with transaction(self._sessions) as session:
            version = await session.get(DocumentVersion, version_id, with_for_update=True)
            if version is None:
                raise NotFoundError(f"document version {version_id} not found")
            settled = version.status not in IN_FLIGHT_VERSION_STATUSES
            if not settled:
                run = await session.get(Run, run_id)
                document = await session.get(Document, version.document_id)
                if run is None or document is None:
                    raise NotFoundError(f"run {run_id} or its document is missing")
                version.status = "processing"
                # When this version is already current, an earlier attempt loaded it and crashed
                # before settling; comparing against itself would wrongly report a duplicate.
                is_current = document.current_version_id in (None, version.id)
                ref = DocumentRef(
                    run_id=run_id,
                    version_id=version.id,
                    document_id=document.id,
                    source=document.source,
                    uri=document.uri,
                    filename=document.filename,
                    fingerprint=version.fingerprint,
                    previous_content_hash=None if is_current else document.content_hash,
                    force=run.force,
                    bypass_cache=run.bypass_cache,
                )
        if settled:
            log.info("process.skipped", version_id=str(version_id), status=version.status)
            await self.finalize_if_done(run_id)
            return version.status

        try:
            await self._runner.run(ref, root_identity=ref.fingerprint)
        except PipelineHalt as halt:
            await self._settle(ref, "deduplicated", error=halt.reason)
            return "deduplicated"
        except StageFailed as failure:
            await self._settle(
                ref,
                "failed",
                failure=_Failure(
                    stage=failure.stage,
                    error_type=failure.error_type,
                    error=str(failure.cause),
                    attempts=failure.attempts,
                    retryable=failure.retryable,
                ),
            )
            return "failed"
        await self._settle(ref, "succeeded")
        return "succeeded"

    async def fail_unexpectedly(self, run_id: uuid.UUID, version_id: uuid.UUID, error: BaseException) -> None:
        """Called by the worker when a job keeps crashing outside the stage runner."""
        async with self._sessions() as session:
            version = await session.get(DocumentVersion, version_id)
            document = await session.get(Document, version.document_id) if version else None
        if version is None or document is None:
            return
        ref = DocumentRef(
            run_id=run_id,
            version_id=version_id,
            document_id=document.id,
            source=document.source,
            uri=document.uri,
            filename=document.filename,
            fingerprint=version.fingerprint,
        )
        failure = _Failure(
            stage="worker", error_type=type(error).__name__, error=str(error), attempts=0, retryable=True
        )
        await self._settle(ref, "failed", failure=failure)

    async def _settle(
        self,
        ref: DocumentRef,
        outcome: VersionOutcome,
        *,
        error: str | None = None,
        failure: _Failure | None = None,
    ) -> None:
        now = datetime.now(UTC)
        if failure is not None:
            error = f"{failure.stage}: {failure.error}"
            log.error(
                "process.dead_letter",
                uri=ref.uri,
                stage=failure.stage,
                error=failure.error,
                attempts=failure.attempts,
            )
        async with transaction(self._sessions) as session:
            claimed = await session.scalar(
                update(DocumentVersion)
                .where(
                    DocumentVersion.id == ref.version_id,
                    DocumentVersion.status.in_(IN_FLIGHT_VERSION_STATUSES),
                )
                .values(status=outcome, error=error[:4000] if error else None, processed_at=now)
                .returning(DocumentVersion.id)
            )
            if claimed is None:
                log.info("process.already_settled", version_id=str(ref.version_id))
                return
            if failure is not None:
                await session.execute(
                    update(DeadLetter)
                    .where(DeadLetter.document_id == ref.document_id, DeadLetter.status == "open")
                    .values(status="superseded")
                )
                session.add(
                    DeadLetter(
                        run_id=ref.run_id,
                        version_id=ref.version_id,
                        document_id=ref.document_id,
                        stage=failure.stage,
                        error_type=failure.error_type,
                        error=failure.error[:4000],
                        attempts=failure.attempts,
                        retryable=failure.retryable,
                    )
                )
                await session.execute(
                    update(Document).where(Document.id == ref.document_id).values(status="failed")
                )
            else:
                if outcome == "succeeded":
                    await session.execute(
                        update(DeadLetter)
                        .where(DeadLetter.document_id == ref.document_id, DeadLetter.status == "open")
                        .values(status="resolved")
                    )
                await session.execute(
                    update(Document)
                    .where(Document.id == ref.document_id, Document.status.in_(("processing", "failed")))
                    .values(status="ready")
                )
            column = {
                "succeeded": Run.docs_succeeded,
                "failed": Run.docs_failed,
                "deduplicated": Run.docs_deduplicated,
            }[outcome]
            done, expected, status = (
                await session.execute(
                    update(Run)
                    .where(Run.id == ref.run_id)
                    .values({column.key: column + 1})
                    .returning(
                        Run.docs_succeeded + Run.docs_failed + Run.docs_deduplicated,
                        Run.docs_changed,
                        Run.status,
                    )
                )
            ).one()
        if status == "running" and done >= expected:
            await self._queue.enqueue_finalize(ref.run_id)

    async def finalize_if_done(self, run_id: uuid.UUID) -> None:
        async with self._sessions() as session:
            run = await session.get(Run, run_id)
        if run is None:
            return
        done = run.docs_succeeded + run.docs_failed + run.docs_deduplicated
        if run.status == "finalizing" or (run.status == "running" and done >= run.docs_changed):
            await self._queue.enqueue_finalize(run_id)

    async def finalize(self, run_id: uuid.UUID) -> None:
        """Closes the books on a run, then writes its Parquet export.

        The terminal status and totals are set in one transaction, so a retry after a crash either
        finds the run still open (and redoes it) or finds it closed (and only redoes the export).
        """
        async with transaction(self._sessions) as session:
            run = await session.get(Run, run_id, with_for_update=True)
            if run is None:
                return
            done = run.docs_succeeded + run.docs_failed + run.docs_deduplicated
            if run.status == "running" and done < run.docs_changed:
                log.info("finalize.not_ready", run_id=str(run_id), done=done, expected=run.docs_changed)
                return
            if run.status in ("running", "finalizing"):
                await self._close(session, run)
            elif run.status not in TERMINAL_RUN_STATUSES:
                return
            needs_export = run.export_path is None

        if needs_export:
            async with transaction(self._sessions) as session:
                path = await self._exporter.export_run(session, run_id)
                await session.execute(update(Run).where(Run.id == run_id).values(export_path=str(path)))
        log.info("run.finalized", run_id=str(run_id))

    @staticmethod
    async def _close(session: AsyncSession, run: Run) -> None:
        totals = (
            await session.execute(
                select(
                    func.coalesce(func.sum(StageRun.input_tokens), 0),
                    func.coalesce(func.sum(StageRun.output_tokens), 0),
                    func.coalesce(func.sum(StageRun.cost_usd), 0),
                    func.coalesce(func.sum(StageRun.cost_saved_usd), 0),
                    func.bool_or(StageRun.detail["cost_estimated"].as_boolean()),
                ).where(StageRun.run_id == run.id)
            )
        ).one()
        run.input_tokens, run.output_tokens = int(totals[0]), int(totals[1])
        run.cost_usd = Decimal(totals[2])
        run.cost_saved_usd = (run.cost_saved_usd or Decimal(0)) + Decimal(totals[3])
        run.cost_estimated = run.cost_estimated or bool(totals[4])
        if run.docs_failed == 0:
            run.status = "succeeded"
        elif run.docs_succeeded + run.docs_deduplicated > 0:
            run.status = "partial"
        else:
            run.status = "failed"
        run.finished_at = datetime.now(UTC)

    async def fail_run(self, run_id: uuid.UUID, error: str) -> None:
        async with transaction(self._sessions) as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id, Run.status.in_(ACTIVE_RUN_STATUSES))
                .values(status="failed", error=error[:4000], finished_at=datetime.now(UTC))
            )

    async def reap_stale(self) -> int:
        """Re-enqueues the next step of any run that has stopped making progress.

        Jobs are idempotent, so a duplicate is harmless; fresh job ids are used because arq keeps
        the id of a finished (or exhausted) job and would otherwise ignore the re-enqueue.
        """
        cutoff = datetime.now(UTC) - self._stale_after
        token = f"reap-{int(time.time())}"
        async with self._sessions() as session:
            runs = list(
                await session.scalars(
                    select(Run).where(
                        Run.status.in_(ACTIVE_RUN_STATUSES),
                        func.coalesce(Run.started_at, Run.created_at) < cutoff,
                    )
                )
            )
            stuck: dict[uuid.UUID, list[uuid.UUID]] = {}
            for run in runs:
                if run.status == "running":
                    stuck[run.id] = list(
                        await session.scalars(
                            self._in_flight_versions(run.id).where(DocumentVersion.updated_at < cutoff)
                        )
                    )
        for run in runs:
            done = run.docs_succeeded + run.docs_failed + run.docs_deduplicated
            log.warning("reaper.run_stalled", run_id=str(run.id), status=run.status)
            if run.status in ("queued", "scanning"):
                await self._queue.enqueue_scan(run.id, retry_token=token)
            elif run.status == "finalizing" or done >= run.docs_changed:
                await self._queue.enqueue_finalize(run.id, retry_token=token)
            else:
                for version_id in stuck.get(run.id, []):
                    await self._queue.enqueue_process(run.id, version_id, retry_token=token)
        return len(runs)
