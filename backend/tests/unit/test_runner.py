from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from docforge.errors import ParseError, TransientError
from docforge.pipeline.core import (
    CachedOutput,
    DocumentRef,
    PipelineHalt,
    StageFailed,
    StageInputs,
    StageMetrics,
    StageRecord,
    StageResult,
)
from docforge.pipeline.runner import DagRunner, RetryPolicy, plan_levels


class Value(BaseModel):
    text: str


class MemoryCache:
    def __init__(self) -> None:
        self.entries: dict[str, CachedOutput] = {}

    async def get(self, key: str) -> CachedOutput | None:
        return self.entries.get(key)

    async def put(self, key: str, stage: str, output: BaseModel, metrics: StageMetrics) -> None:
        self.entries[key] = CachedOutput(output=output.model_dump(), metrics=metrics)


class MemoryLedger:
    def __init__(self) -> None:
        self.records: list[StageRecord] = []

    async def record(self, record: StageRecord) -> None:
        self.records.append(record)

    def statuses(self) -> dict[str, str]:
        return {r.stage: r.status for r in self.records}


class FakeStage:
    output_type = Value

    def __init__(
        self,
        name: str,
        depends_on: tuple[str, ...] = (),
        *,
        version: str = "v1",
        failures: list[Exception] | None = None,
        cacheable: bool = True,
        cost: float = 0.0,
    ) -> None:
        self.name = name
        self.depends_on = depends_on
        self.version = version
        self.failures = list(failures or [])
        self.cacheable = cacheable
        self.cost = cost
        self.calls = 0

    def config_version(self) -> str:
        return self.version

    def identity(self, output: BaseModel, key: str) -> str:
        return key

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[Any]:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        upstream = "+".join(inputs.get(dep, Value).text for dep in self.depends_on)
        return StageResult(
            output=Value(text=f"{self.name}({upstream})"), metrics=StageMetrics(cost_usd=self.cost)
        )


def _doc(**overrides: Any) -> DocumentRef:
    values: dict[str, Any] = {
        "run_id": uuid.uuid4(),
        "version_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "source": "fs",
        "uri": "a.pdf",
        "filename": "a.pdf",
        "fingerprint": "sha256:abc",
    }
    return DocumentRef.model_validate({**values, **overrides})


async def _no_sleep(_: float) -> None:
    return None


def _runner(
    stages: list[FakeStage], cache: MemoryCache, ledger: MemoryLedger, attempts: int = 3
) -> DagRunner:
    return DagRunner(
        stages, cache=cache, ledger=ledger, retry=RetryPolicy(max_attempts=attempts), sleep=_no_sleep
    )


def test_levels_follow_dependencies_and_reject_cycles() -> None:
    stages = [
        FakeStage("load", ("embed", "extract")),
        FakeStage("embed", ("parse",)),
        FakeStage("parse"),
        FakeStage("extract", ("parse",)),
    ]
    assert [[s.name for s in level] for level in plan_levels(stages)] == [
        ["parse"],
        ["embed", "extract"],
        ["load"],
    ]
    with pytest.raises(ValueError, match="cycle"):
        plan_levels([FakeStage("a", ("b",)), FakeStage("b", ("a",))])
    with pytest.raises(ValueError, match="unknown"):
        plan_levels([FakeStage("a", ("missing",))])


async def test_second_run_is_served_from_cache() -> None:
    parse, extract = FakeStage("parse"), FakeStage("extract", ("parse",), cost=0.25)
    cache, ledger = MemoryCache(), MemoryLedger()
    runner = _runner([parse, extract], cache, ledger)

    first = await runner.run(_doc(), root_identity="sha256:abc")
    second = await runner.run(_doc(), root_identity="sha256:abc")

    assert first.outputs == second.outputs
    assert (parse.calls, extract.calls) == (1, 1)
    assert [r.status for r in ledger.records] == ["succeeded", "succeeded", "cached", "cached"]
    assert ledger.records[-1].cost_saved_usd == 0.25


async def test_config_change_invalidates_the_stage_and_everything_downstream() -> None:
    parse, chunk, extract = (
        FakeStage("parse"),
        FakeStage("chunk", ("parse",)),
        FakeStage("extract", ("parse",)),
    )
    cache, ledger = MemoryCache(), MemoryLedger()
    await _runner([parse, chunk, extract], cache, ledger).run(_doc(), root_identity="h")

    parse.version = "v2"
    outcome = await _runner([parse, chunk, extract], cache, MemoryLedger()).run(_doc(), root_identity="h")
    assert (parse.calls, chunk.calls, extract.calls) == (2, 2, 2)

    chunk.version = "v2"
    ledger = MemoryLedger()
    again = await _runner([parse, chunk, extract], cache, ledger).run(_doc(), root_identity="h")
    assert ledger.statuses() == {"parse": "cached", "chunk": "succeeded", "extract": "cached"}
    assert again.keys["extract"] == outcome.keys["extract"]


async def test_transient_errors_retry_with_backoff_then_succeed() -> None:
    stage = FakeStage("extract", failures=[TransientError("429"), TransientError("529")])
    ledger = MemoryLedger()
    await _runner([stage], MemoryCache(), ledger).run(_doc(), root_identity="h")
    assert stage.calls == 3
    assert ledger.records[0].attempts == 3


async def test_permanent_errors_fail_fast_and_skip_downstream() -> None:
    parse = FakeStage("parse", failures=[ParseError("truncated")])
    chunk = FakeStage("chunk", ("parse",))
    ledger = MemoryLedger()
    with pytest.raises(StageFailed) as caught:
        await _runner([parse, chunk], MemoryCache(), ledger).run(_doc(), root_identity="h")
    assert caught.value.stage == "parse" and caught.value.attempts == 1
    assert caught.value.error_type == "parse_error" and not caught.value.retryable
    assert ledger.statuses() == {"parse": "failed", "chunk": "skipped"}
    assert chunk.calls == 0


async def test_exhausted_retries_surface_as_stage_failure() -> None:
    stage = FakeStage("embed", failures=[TransientError("down")] * 5)
    with pytest.raises(StageFailed) as caught:
        await _runner([stage], MemoryCache(), MemoryLedger(), attempts=2).run(_doc(), root_identity="h")
    assert caught.value.attempts == 2 and caught.value.retryable


async def test_halt_stops_the_pipeline_without_failing() -> None:
    detect = FakeStage("detect", failures=[PipelineHalt("same bytes")], cacheable=False)
    parse = FakeStage("parse", ("detect",))
    ledger = MemoryLedger()
    with pytest.raises(PipelineHalt):
        await _runner([detect, parse], MemoryCache(), ledger).run(_doc(), root_identity="h")
    assert ledger.statuses() == {"detect": "skipped", "parse": "skipped"}


async def test_bypass_cache_recomputes() -> None:
    stage = FakeStage("parse")
    cache = MemoryCache()
    await _runner([stage], cache, MemoryLedger()).run(_doc(), root_identity="h")
    await _runner([stage], cache, MemoryLedger()).run(_doc(bypass_cache=True), root_identity="h")
    assert stage.calls == 2


def test_backoff_is_bounded() -> None:
    policy = RetryPolicy(max_attempts=5, base_delay=1.0, max_delay=4.0)
    assert all(0 <= policy.delay(attempt) <= 4.0 for attempt in range(1, 10))


async def test_an_unreadable_cache_entry_is_recomputed_not_fatal() -> None:
    stage = FakeStage("parse")
    cache, ledger = MemoryCache(), MemoryLedger()
    first = await _runner([stage], cache, MemoryLedger()).run(_doc(), root_identity="h")
    cache.entries[first.keys["parse"]] = CachedOutput(output={"unexpected": 1}, metrics=StageMetrics())

    again = await _runner([stage], cache, ledger).run(_doc(), root_identity="h")

    assert stage.calls == 2 and ledger.statuses() == {"parse": "succeeded"}
    assert again.outputs["parse"] == first.outputs["parse"]


async def test_output_schema_is_part_of_the_key() -> None:
    class Wider(BaseModel):
        text: str
        extra: int = 0

    narrow, wide = FakeStage("parse"), FakeStage("parse")
    wide.output_type = Wider  # type: ignore[assignment]
    cache = MemoryCache()
    one = await _runner([narrow], cache, MemoryLedger()).run(_doc(), root_identity="h")
    two = await _runner([wide], cache, MemoryLedger()).run(_doc(), root_identity="h")
    assert one.keys["parse"] != two.keys["parse"]
