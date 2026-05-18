from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from docforge.errors import InvalidRequestError, SourceUnavailableError
from docforge.sources.base import SourceObject, is_supported, normalize_prefix


class FsSource:
    """Local directory source.

    Listing only stats files: the fingerprint is size, mtime and inode, so a scheduled scan never
    reads unchanged bytes. A touched-but-identical file gets a new fingerprint and is then stopped
    by the detect stage, which compares the real content hash.
    """

    def __init__(self, root: Path, name: str = "fs") -> None:
        self.name = name
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def uri_scope(self, prefix: str) -> str:
        return normalize_prefix(prefix)

    async def list_objects(self, prefix: str = "") -> AsyncIterator[SourceObject]:
        if not self._root.is_dir():
            raise SourceUnavailableError(f"source directory {self._root} does not exist")
        paths = await asyncio.to_thread(self._scan, normalize_prefix(prefix))
        for path in paths:
            described = await asyncio.to_thread(self._describe, path)
            if described is not None:
                yield described

    async def read(self, uri: str) -> bytes:
        path = self._resolve(uri)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise SourceUnavailableError(f"{uri} disappeared from {self._root}") from exc

    def _scan(self, prefix: str) -> list[Path]:
        base = self._resolve(prefix) if prefix else self._root
        if not base.exists():
            raise InvalidRequestError(f"prefix '{prefix}' does not exist in source '{self.name}'")
        if base.is_file():
            return [base]
        return sorted(
            path
            for path in base.rglob("*")
            if path.is_file() and is_supported(path.relative_to(self._root).as_posix())
        )

    def _describe(self, path: Path) -> SourceObject | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return SourceObject(
            source=self.name,
            uri=path.relative_to(self._root).as_posix(),
            filename=path.name,
            size_bytes=stat.st_size,
            fingerprint=f"stat:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}",
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

    def _resolve(self, uri: str) -> Path:
        candidate = (self._root / uri).resolve()
        if not candidate.is_relative_to(self._root):
            raise SourceUnavailableError(f"{uri} escapes the source root")
        return candidate
