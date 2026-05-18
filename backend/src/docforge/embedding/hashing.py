from __future__ import annotations

import hashlib
import itertools
import math
import re

from docforge.embedding.base import EMBEDDING_DIM

_WORD = re.compile(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*")


class HashingEmbedder:
    """Deterministic feature-hashing embedder over unigrams and bigrams.

    It needs no model download, so tests and the offline demo are reproducible. Lexical overlap is
    all it captures, which is enough for keyword-heavy business documents.
    """

    def __init__(self, dimensions: int = EMBEDDING_DIM) -> None:
        self.dimensions = dimensions
        self.name = f"hashing-v1-{dimensions}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        tokens = _WORD.findall(text.lower())
        features = tokens + [f"{a} {b}" for a, b in itertools.pairwise(tokens)]
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log1p(len(feature) / 8))
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]
