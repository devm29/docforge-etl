from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Protocol

from docforge.errors import NotFoundError, PermanentError
from docforge.sources.hashing import sha256_bytes


class BlobStore(Protocol):
    """Content-addressed storage for raw document bytes, so every version stays viewable."""

    async def put(self, data: bytes) -> str: ...

    async def get(self, key: str) -> bytes: ...


class CorruptBlobError(PermanentError):
    code = "corrupt_blob"


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
            raise NotFoundError(f"blob {key} not found")
        return self._root / key[:2] / key

    async def put(self, data: bytes) -> str:
        key = sha256_bytes(data)
        path = self._path(key)
        if not path.exists():
            await asyncio.to_thread(self._write, path, data)
        return key

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise NotFoundError(f"blob {key} not found") from exc
        if sha256_bytes(data) != key:
            raise CorruptBlobError(f"blob {key} does not match its content hash")
        return data

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            Path(tmp).replace(path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
