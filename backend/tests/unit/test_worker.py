from __future__ import annotations

import uuid
from typing import Any

import pytest
from arq import Retry

from docforge.errors import InvalidRequestError, SourceUnavailableError
from docforge.pipeline.queue import deserialize_job, serialize_job
from docforge.worker import main as worker


class FlakyPipeline:
    def __init__(self) -> None:
        self.failures: list[tuple[uuid.UUID, uuid.UUID, BaseException]] = []

    async def process(self, run_id: uuid.UUID, version_id: uuid.UUID) -> str:
        raise ConnectionError("database went away")

    async def fail_unexpectedly(self, run_id: uuid.UUID, version_id: uuid.UUID, error: BaseException) -> None:
        self.failures.append((run_id, version_id, error))


def _ctx(pipeline: FlakyPipeline, job_try: int) -> dict[str, Any]:
    return {"pipeline": pipeline, "job_try": job_try}


async def test_infrastructure_errors_are_retried_with_backoff() -> None:
    pipeline = FlakyPipeline()
    with pytest.raises(Retry) as caught:
        await worker.process_document(_ctx(pipeline, 1), str(uuid.uuid4()), str(uuid.uuid4()))
    assert caught.value.defer_score == 2000
    assert pipeline.failures == []


async def test_last_attempt_dead_letters_instead_of_retrying() -> None:
    pipeline = FlakyPipeline()
    run_id, version_id = uuid.uuid4(), uuid.uuid4()
    result = await worker.process_document(
        _ctx(pipeline, worker.settings.worker_job_tries), str(run_id), str(version_id)
    )
    assert result == "failed"
    [(failed_run, failed_version, error)] = pipeline.failures
    assert (failed_run, failed_version) == (run_id, version_id)
    assert isinstance(error, ConnectionError)


class ScanPipeline:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.failed: list[tuple[uuid.UUID, str]] = []

    async def scan(self, run_id: uuid.UUID) -> None:
        raise self.error

    async def fail_run(self, run_id: uuid.UUID, error: str) -> None:
        self.failed.append((run_id, error))


async def test_transient_scan_errors_are_retried_without_failing_the_run() -> None:
    pipeline = ScanPipeline(SourceUnavailableError("bucket unreachable"))
    with pytest.raises(Retry):
        await worker.scan_source({"pipeline": pipeline, "job_try": 1}, str(uuid.uuid4()))
    assert pipeline.failed == []


async def test_scan_fails_the_run_on_a_permanent_error_or_the_last_attempt() -> None:
    bad_prefix = ScanPipeline(InvalidRequestError("prefix 'x' does not exist"))
    await worker.scan_source({"pipeline": bad_prefix, "job_try": 1}, str(uuid.uuid4()))
    assert len(bad_prefix.failed) == 1 and "does not exist" in bad_prefix.failed[0][1]

    exhausted = ScanPipeline(SourceUnavailableError("still down"))
    await worker.scan_source(
        {"pipeline": exhausted, "job_try": worker.settings.worker_job_tries}, str(uuid.uuid4())
    )
    assert len(exhausted.failed) == 1


def test_jobs_are_serialized_as_json_not_pickle() -> None:
    payload = {"t": 1, "f": "process_document", "a": ["run", "version"], "k": {}, "et": 1700000000000}
    encoded = serialize_job(payload)
    assert encoded.startswith(b"{") and deserialize_job(encoded) == payload
    assert b"ValueError" in serialize_job({"r": ValueError("boom")})


def test_registered_jobs_match_queue_names() -> None:
    from docforge.pipeline.queue import FINALIZE_JOB, PROCESS_JOB, SCAN_JOB

    names = {f.__name__ for f in worker.WorkerSettings.functions}
    assert names == {SCAN_JOB, PROCESS_JOB, FINALIZE_JOB}
