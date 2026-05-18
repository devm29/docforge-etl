from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, get_args

RunTrigger = Literal["api", "schedule", "replay", "cli"]
RunStatus = Literal["queued", "scanning", "running", "finalizing", "succeeded", "partial", "failed"]
DocumentStatus = Literal["pending", "processing", "ready", "failed", "removed"]
VersionStatus = Literal["queued", "processing", "succeeded", "failed", "deduplicated"]
VersionOutcome = Literal["succeeded", "failed", "deduplicated"]
ReviewStatus = Literal["pending", "approved", "edited", "superseded"]
DeadLetterStatus = Literal["open", "resolved", "superseded", "replayed"]
StageStatus = Literal["succeeded", "cached", "failed", "skipped"]

ACTIVE_RUN_STATUSES: tuple[RunStatus, ...] = ("queued", "scanning", "running", "finalizing")
TERMINAL_RUN_STATUSES: tuple[RunStatus, ...] = ("succeeded", "partial", "failed")
IN_FLIGHT_VERSION_STATUSES: tuple[VersionStatus, ...] = ("queued", "processing")


def values_of(literal: object) -> tuple[str, ...]:
    return tuple(str(value) for value in get_args(literal))


def check_in(column: str, values: Iterable[str]) -> str:
    """SQL for a CHECK constraint that keeps a status column inside its allowed values."""
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"
