from __future__ import annotations

import asyncio
from typing import Any

from docforge.embedding.base import EMBEDDING_DIM


class FastEmbedEmbedder:
    """Local ONNX embeddings through fastembed (BAAI/bge-small-en-v1.5 by default, 384 dimensions)."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding

        self._model: Any = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.name = f"fastembed:{model_name}"
        self.dimensions = EMBEDDING_DIM
        self._lock = asyncio.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._lock:
            return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        vectors = [[float(x) for x in vector] for vector in self._model.embed(texts, batch_size=32)]
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(f"{self.name} returned {len(vector)} dimensions, expected {self.dimensions}")
        return vectors
