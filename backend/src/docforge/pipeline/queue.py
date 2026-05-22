from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from arq.connections import ArqRedis

SCAN_JOB = "scan_source"
PROCESS_JOB = "process_document"
FINALIZE_JOB = "finalize_run"


def serialize_job(payload: dict[str, Any]) -> bytes:
    """JSON instead of arq's default pickle, so a write to Redis can never become code execution.

    Job arguments are plain strings; anything else arq stores (a failed job's exception) is kept
    as its repr.
    """
    return json.dumps(payload, default=repr).encode()


def deserialize_job(data: bytes) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(data)
    return payload


class JobQueue(Protocol):
    async def enqueue_scan(self, run_id: uuid.UUID, *, retry_token: str | None = None) -> None: ...

    async def enqueue_process(
        self, run_id: uuid.UUID, version_id: uuid.UUID, *, retry_token: str | None = None
    ) -> None: ...

    async def enqueue_finalize(self, run_id: uuid.UUID, *, retry_token: str | None = None) -> None: ...

    async def ping(self) -> None: ...


def _job_id(base: str, retry_token: str | None) -> str:
    return f"{base}:{retry_token}" if retry_token else base


class ArqJobQueue:
    """Enqueues onto Redis for the arq worker. Job ids make enqueueing idempotent."""

    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def enqueue_scan(self, run_id: uuid.UUID, *, retry_token: str | None = None) -> None:
        await self._redis.enqueue_job(SCAN_JOB, str(run_id), _job_id=_job_id(f"scan:{run_id}", retry_token))

    async def enqueue_process(
        self, run_id: uuid.UUID, version_id: uuid.UUID, *, retry_token: str | None = None
    ) -> None:
        await self._redis.enqueue_job(
            PROCESS_JOB,
            str(run_id),
            str(version_id),
            _job_id=_job_id(f"process:{run_id}:{version_id}", retry_token),
        )

    async def enqueue_finalize(self, run_id: uuid.UUID, *, retry_token: str | None = None) -> None:
        await self._redis.enqueue_job(
            FINALIZE_JOB, str(run_id), _job_id=_job_id(f"finalize:{run_id}", retry_token)
        )

    async def ping(self) -> None:
        await self._redis.ping()


class InlineJobQueue:
    """Runs jobs as local asyncio tasks. Used by tests and the CLI when no worker is running."""

    def __init__(self, concurrency: int = 4) -> None:
        self._handlers: dict[str, Callable[..., Awaitable[None]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(concurrency)
        self._errors: list[BaseException] = []

    def bind(
        self,
        *,
        scan: Callable[[uuid.UUID], Awaitable[None]],
        process: Callable[[uuid.UUID, uuid.UUID], Awaitable[None]],
        finalize: Callable[[uuid.UUID], Awaitable[None]],
    ) -> None:
        self._handlers = {SCAN_JOB: scan, PROCESS_JOB: process, FINALIZE_JOB: finalize}

    def _spawn(self, name: str, *args: uuid.UUID) -> None:
        handler = self._handlers[name]

        async def job() -> None:
            async with self._semaphore:
                try:
                    await handler(*args)
                except Exception as exc:
                    self._errors.append(exc)

        task = asyncio.create_task(job())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def enqueue_scan(self, run_id: uuid.UUID, *, retry_token: str | None = None) -> None:
        self._spawn(SCAN_JOB, run_id)

    async def enqueue_process(
        self, run_id: uuid.UUID, version_id: uuid.UUID, *, retry_token: str | None = None
    ) -> None:
        self._spawn(PROCESS_JOB, run_id, version_id)

    async def enqueue_finalize(self, run_id: uuid.UUID, *, retry_token: str | None = None) -> None:
        self._spawn(FINALIZE_JOB, run_id)

    async def ping(self) -> None:
        return None

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks))
        if self._errors:
            errors, self._errors = self._errors, []
            raise errors[0]
