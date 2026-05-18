from __future__ import annotations

from typing import Protocol

EMBEDDING_DIM = 384


class Embedder(Protocol):
    """Produces unit-length vectors of ``EMBEDDING_DIM`` dimensions.

    ``name`` identifies the model and is part of the embed stage's idempotency key, so swapping
    models re-embeds everything while keeping old vectors addressable by their own key.
    """

    name: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
