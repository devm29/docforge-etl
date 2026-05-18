from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from docforge.domain.statuses import StageStatus
from docforge.errors import PipelineError
from docforge.logs import get_logger
from docforge.pipeline.core import (
    DocumentRef,
    Ledger,
    PipelineHalt,
    Stage,
    StageCache,
    StageFailed,
    StageInputs,
    StageMetrics,
    StageRecord,
    StageResult,
)
from docforge.sources.hashing import stable_hash

log = get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 20.0

    def delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter, so concurrent retries do not stampede a provider."""
        ceiling = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return random.uniform(0, ceiling)


@dataclass
class DagOutcome:
    outputs: dict[str, BaseModel]
    keys: dict[str, str]
    records: list[StageRecord]


def plan_levels(stages: Sequence[Stage]) -> list[list[Stage]]:
    """Groups stages into dependency levels (Kahn's algorithm); stages in a level run concurrently."""
    by_name = {stage.name: stage for stage in stages}
    if len(by_name) != len(stages):
        raise ValueError("stage names must be unique")
    for stage in stages:
        missing = [dep for dep in stage.depends_on if dep not in by_name]
        if missing:
            raise ValueError(f"stage '{stage.name}' depends on unknown stage(s) {missing}")

    remaining = {stage.name: set(stage.depends_on) for stage in stages}
    levels: list[list[Stage]] = []
    done: set[str] = set()
    while remaining:
        ready = sorted(name for name, deps in remaining.items() if deps <= done)
        if not ready:
            raise ValueError(f"stage graph has a cycle among {sorted(remaining)}")
        levels.append([by_name[name] for name in ready])
        done.update(ready)
        for name in ready:
            del remaining[name]
    return levels


class DagRunner:
    """Executes a document through the stage DAG with memoization, retries and a ledger entry per stage.

    The idempotency key of a stage is a hash of its name, its configuration version, the JSON
    schema of its output and the identities of its inputs. Root stages take the source
    fingerprint; the detect stage then exposes the content hash as its identity, so everything
    downstream is keyed by content rather than by where the bytes came from. Changing an output
    model changes the key, and a cached output that still fails to load is treated as a miss.
    """

    def __init__(
        self,
        stages: Sequence[Stage],
        *,
        cache: StageCache,
        ledger: Ledger,
        retry: RetryPolicy,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._levels = plan_levels(stages)
        self._output_schemas = {
            stage.name: stable_hash(json.dumps(stage.output_type.model_json_schema(), sort_keys=True))[:12]
            for stage in stages
        }
        self._cache = cache
        self._ledger = ledger
        self._retry = retry
        self._sleep = sleep

    @property
    def stage_names(self) -> list[str]:
        return [stage.name for level in self._levels for stage in level]

    @property
    def version(self) -> str:
        return stable_hash(
            *(
                f"{s.name}:{s.config_version()}:{self._output_schemas[s.name]}"
                for level in self._levels
                for s in level
            )
        )[:16]

    async def run(self, doc: DocumentRef, *, root_identity: str) -> DagOutcome:
        outputs: dict[str, BaseModel] = {}
        identities: dict[str, str] = {}
        keys: dict[str, str] = {}
        records: list[StageRecord] = []

        for index, level in enumerate(self._levels):
            results = await asyncio.gather(
                *(self._run_stage(doc, stage, outputs, identities, root_identity) for stage in level),
                return_exceptions=True,
            )
            failure: BaseException | None = None
            for stage, result in zip(level, results, strict=True):
                if isinstance(result, BaseException):
                    failure = failure or result
                    continue
                output, key, record = result
                outputs[stage.name] = output
                keys[stage.name] = key
                identities[stage.name] = stage.identity(output, key)
                records.append(record)
            if failure is not None:
                reason = (
                    failure.reason if isinstance(failure, PipelineHalt) else f"upstream failure: {failure}"
                )
                await self._skip_rest(doc, index + 1, reason)
                raise failure
        return DagOutcome(outputs=outputs, keys=keys, records=records)

    def _key(self, stage: Stage, identities: dict[str, str], root_identity: str) -> str:
        inputs = [f"{dep}={identities[dep]}" for dep in sorted(stage.depends_on)] or [f"root={root_identity}"]
        return stable_hash(stage.name, stage.config_version(), self._output_schemas[stage.name], *inputs)

    async def _run_stage(
        self,
        doc: DocumentRef,
        stage: Stage,
        outputs: dict[str, BaseModel],
        identities: dict[str, str],
        root_identity: str,
    ) -> tuple[BaseModel, str, StageRecord]:
        key = self._key(stage, identities, root_identity)
        started = datetime.now(UTC)
        clock = time.perf_counter()

        if stage.cacheable and not doc.bypass_cache:
            cached = await self._cache.get(key)
            output: BaseModel | None = None
            if cached is not None:
                try:
                    output = stage.output_type.model_validate(cached.output)
                except ValidationError as exc:
                    log.warning("stage.cache_unreadable", stage=stage.name, key=key, error=str(exc))
            if cached is not None and output is not None:
                record = self._record(
                    doc,
                    stage,
                    "cached",
                    key,
                    0,
                    cached.metrics,
                    started,
                    clock,
                    saved=cached.metrics.cost_usd,
                )
                await self._ledger.record(record)
                return output, key, record

        inputs = StageInputs({dep: outputs[dep] for dep in stage.depends_on})
        attempt = 0
        while True:
            attempt += 1
            try:
                result: StageResult[BaseModel] = await stage.run(doc, inputs)
                break
            except PipelineHalt as halt:
                record = self._record(
                    doc,
                    stage,
                    "skipped",
                    key,
                    attempt,
                    StageMetrics(detail={"reason": halt.reason}),
                    started,
                    clock,
                )
                await self._ledger.record(record)
                raise
            except Exception as exc:
                retryable = exc.retryable if isinstance(exc, PipelineError) else True
                if retryable and attempt < self._retry.max_attempts:
                    delay = self._retry.delay(attempt)
                    log.warning(
                        "stage.retry",
                        stage=stage.name,
                        attempt=attempt,
                        delay=round(delay, 2),
                        error=str(exc),
                    )
                    await self._sleep(delay)
                    continue
                record = self._record(
                    doc, stage, "failed", key, attempt, StageMetrics(), started, clock, error=f"{exc}"
                )
                await self._ledger.record(record)
                raise StageFailed(stage.name, attempt, exc, retryable=retryable) from exc

        if stage.cacheable:
            await self._cache.put(key, stage.name, result.output, result.metrics)
        record = self._record(doc, stage, "succeeded", key, attempt, result.metrics, started, clock)
        await self._ledger.record(record)
        return result.output, key, record

    async def _skip_rest(self, doc: DocumentRef, from_level: int, reason: str) -> None:
        now = datetime.now(UTC)
        for level in self._levels[from_level:]:
            for stage in level:
                await self._ledger.record(
                    StageRecord(
                        run_id=doc.run_id,
                        version_id=doc.version_id,
                        stage=stage.name,
                        status="skipped",
                        idempotency_key=None,
                        attempts=0,
                        metrics=StageMetrics(detail={"reason": reason}),
                        duration_ms=0,
                        started_at=now,
                        finished_at=now,
                    )
                )

    @staticmethod
    def _record(
        doc: DocumentRef,
        stage: Stage,
        status: StageStatus,
        key: str,
        attempts: int,
        metrics: StageMetrics,
        started: datetime,
        clock: float,
        *,
        saved: float = 0.0,
        error: str | None = None,
    ) -> StageRecord:
        return StageRecord.model_validate(
            {
                "run_id": doc.run_id,
                "version_id": doc.version_id,
                "stage": stage.name,
                "status": status,
                "idempotency_key": key,
                "attempts": attempts,
                "metrics": metrics,
                "cost_saved_usd": saved,
                "duration_ms": int((time.perf_counter() - clock) * 1000),
                "started_at": started,
                "finished_at": datetime.now(UTC),
                "error": error,
            }
        )
