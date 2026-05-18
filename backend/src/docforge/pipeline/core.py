from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field, JsonValue

from docforge.domain.statuses import StageStatus
from docforge.errors import DocforgeError

OutputT = TypeVar("OutputT", bound=BaseModel)


class DocumentRef(BaseModel):
    run_id: uuid.UUID
    version_id: uuid.UUID
    document_id: uuid.UUID
    source: str
    uri: str
    filename: str
    fingerprint: str
    previous_content_hash: str | None = None
    force: bool = False
    bypass_cache: bool = False


class StageMetrics(BaseModel):
    items_in: int = 0
    items_out: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_estimated: bool = False
    detail: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class StageResult[T: BaseModel]:
    output: T
    metrics: StageMetrics


class StageInputs:
    """Typed access to upstream outputs; a stage can only read what it declared in ``depends_on``."""

    def __init__(self, outputs: dict[str, BaseModel]) -> None:
        self._outputs = outputs

    def get(self, stage: str, kind: type[OutputT]) -> OutputT:
        value = self._outputs.get(stage)
        if not isinstance(value, kind):
            raise TypeError(f"stage input '{stage}' is {type(value).__name__}, expected {kind.__name__}")
        return value


class Stage(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def depends_on(self) -> tuple[str, ...]: ...

    @property
    def output_type(self) -> type[BaseModel]: ...

    @property
    def cacheable(self) -> bool: ...

    def config_version(self) -> str: ...

    def identity(self, output: BaseModel, key: str) -> str:
        """What downstream keys are derived from. Usually the stage's own key."""
        ...

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[Any]: ...


class StageRecord(BaseModel):
    run_id: uuid.UUID
    version_id: uuid.UUID
    stage: str
    status: StageStatus
    idempotency_key: str | None
    attempts: int
    metrics: StageMetrics
    cost_saved_usd: float = 0.0
    duration_ms: int
    started_at: datetime
    finished_at: datetime
    error: str | None = None


class CachedOutput(BaseModel):
    output: dict[str, Any]
    metrics: StageMetrics


class StageCache(Protocol):
    async def get(self, key: str) -> CachedOutput | None: ...

    async def put(self, key: str, stage: str, output: BaseModel, metrics: StageMetrics) -> None: ...


class Ledger(Protocol):
    async def record(self, record: StageRecord) -> None: ...


class PipelineHalt(Exception):  # noqa: N818
    """Raised by a stage when there is nothing left to do for this document (not a failure)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StageFailed(DocforgeError):  # noqa: N818
    code = "stage_failed"

    def __init__(self, stage: str, attempts: int, cause: BaseException, *, retryable: bool) -> None:
        super().__init__(f"stage '{stage}' failed after {attempts} attempt(s): {cause}")
        self.stage = stage
        self.attempts = attempts
        self.cause = cause
        self.retryable = retryable
        self.error_type = getattr(cause, "code", type(cause).__name__)
