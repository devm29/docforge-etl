from __future__ import annotations

import uuid
from typing import Any, ClassVar

from arq import Retry, cron
from arq.connections import RedisSettings

from docforge.config import get_settings
from docforge.container import build_container
from docforge.errors import ConflictError, is_retryable
from docforge.logs import configure_logging, get_logger
from docforge.pipeline.queue import ArqJobQueue, deserialize_job, serialize_job
from docforge.pipeline.service import PipelineService
from docforge.services.dto import CreateRunIn
from docforge.services.runs import RunService

log = get_logger(__name__)
settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(settings.log_level, json=settings.log_json)
    container = build_container(settings)
    queue = ArqJobQueue(ctx["redis"])
    pipeline = container.pipeline(queue)
    ctx["container"] = container
    ctx["pipeline"] = pipeline
    ctx["runs"] = RunService(
        container.sessions,
        queue,
        container.sources,
        container.exporter,
        pipeline.version,
        stale_after=container.stale_after,
    )
    log.info("worker.started", provider=container.provider.name, embedder=container.embedder.name)


async def shutdown(ctx: dict[str, Any]) -> None:
    container = ctx.get("container")
    if container is not None:
        await container.close()


def _pipeline(ctx: dict[str, Any]) -> PipelineService:
    pipeline: PipelineService = ctx["pipeline"]
    return pipeline


def _backoff(job_try: int) -> float:
    return float(min(60, 2**job_try))


def _should_retry(ctx: dict[str, Any], exc: BaseException) -> bool:
    return int(ctx["job_try"]) < settings.worker_job_tries and is_retryable(exc)


async def scan_source(ctx: dict[str, Any], run_id: str) -> None:
    pipeline = _pipeline(ctx)
    try:
        await pipeline.scan(uuid.UUID(run_id))
    except Exception as exc:
        if _should_retry(ctx, exc):
            log.warning("job.retry", job="scan_source", attempt=ctx["job_try"], error=str(exc))
            raise Retry(defer=_backoff(ctx["job_try"])) from exc
        log.error("scan.failed", run_id=run_id, error=str(exc))
        await pipeline.fail_run(uuid.UUID(run_id), f"scan failed: {exc}")


async def process_document(ctx: dict[str, Any], run_id: str, version_id: str) -> str:
    pipeline = _pipeline(ctx)
    try:
        return await pipeline.process(uuid.UUID(run_id), uuid.UUID(version_id))
    except Exception as exc:
        # Stage failures are dead-lettered inside the pipeline. Anything that reaches here broke
        # around it (database, blob store), so retry the whole job before giving up.
        if _should_retry(ctx, exc):
            log.warning("job.retry", job="process_document", attempt=ctx["job_try"], error=str(exc))
            raise Retry(defer=_backoff(ctx["job_try"])) from exc
        await pipeline.fail_unexpectedly(uuid.UUID(run_id), uuid.UUID(version_id), exc)
        return "failed"


async def finalize_run(ctx: dict[str, Any], run_id: str) -> None:
    try:
        await _pipeline(ctx).finalize(uuid.UUID(run_id))
    except Exception as exc:
        if _should_retry(ctx, exc):
            raise Retry(defer=_backoff(ctx["job_try"])) from exc
        raise


async def scheduled_scan(ctx: dict[str, Any]) -> None:
    if not settings.scheduled_scan_enabled:
        return
    runs: RunService = ctx["runs"]
    try:
        run = await runs.start(CreateRunIn(source="fs"), trigger="schedule")
    except ConflictError as exc:
        log.info("schedule.skipped", reason=exc.message)
        return
    log.info("schedule.run_started", run_id=str(run.id))


async def reap_stale_runs(ctx: dict[str, Any]) -> None:
    reaped = await _pipeline(ctx).reap_stale()
    if reaped:
        log.warning("reaper.requeued", runs=reaped)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [scan_source, process_document, finalize_run]
    cron_jobs: ClassVar[list[Any]] = [
        cron(
            scheduled_scan,
            minute=set(range(0, 60, settings.scheduled_scan_minute_interval)),
            run_at_startup=False,
            unique=True,
        ),
        cron(reap_stale_runs, minute=set(range(0, 60, 5)), run_at_startup=True, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_serializer = staticmethod(serialize_job)
    job_deserializer = staticmethod(deserialize_job)
    max_jobs = settings.worker_max_jobs
    max_tries = settings.worker_job_tries
    job_timeout = 600
    keep_result = 3600
