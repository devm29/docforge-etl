from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from docforge.errors import InvalidRequestError

SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".xlsx", ".csv"})


class SourceObject(BaseModel):
    source: str
    uri: str
    filename: str
    size_bytes: int
    fingerprint: str
    modified_at: datetime | None = None


@runtime_checkable
class SourceConnector(Protocol):
    """A place documents come from.

    ``fingerprint`` must change whenever the object's bytes change. It is compared against the
    documents table to decide what to reprocess, so it should be cheap to obtain while listing.

    A ``prefix`` is a folder or file path relative to the source (see ``normalize_prefix``), and
    ``uri_scope`` maps it to the URI path that a listing with that prefix covers, so the scan knows
    which previously seen documents a listing is allowed to retire.
    """

    name: str

    def list_objects(self, prefix: str = "") -> AsyncIterator[SourceObject]: ...

    async def read(self, uri: str) -> bytes: ...

    def uri_scope(self, prefix: str) -> str: ...


def normalize_prefix(prefix: str) -> str:
    """Validates a user-supplied prefix as a relative POSIX path and drops a trailing slash."""
    value = prefix.strip()
    if not value:
        return ""
    if any(ord(char) < 32 for char in value) or "\\" in value:
        raise ValueError("prefix must not contain control characters or backslashes")
    if value.startswith("/"):
        raise ValueError("prefix must be relative to the source root")
    value = value.rstrip("/")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("prefix must not contain empty, '.' or '..' segments")
    return value


def in_scope(uri: str, scope: str) -> bool:
    return not scope or uri == scope or uri.startswith(f"{scope}/")


def is_supported(key: str) -> bool:
    path = PurePosixPath(key)
    if any(part.startswith(".") for part in path.parts):
        return False
    return path.suffix.lower() in SUPPORTED_SUFFIXES


class SourceRegistry:
    def __init__(self, connectors: list[SourceConnector]) -> None:
        self._connectors = {connector.name: connector for connector in connectors}

    def get(self, name: str) -> SourceConnector:
        try:
            return self._connectors[name]
        except KeyError:
            raise InvalidRequestError(
                f"unknown source '{name}', expected one of {sorted(self._connectors)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._connectors)
