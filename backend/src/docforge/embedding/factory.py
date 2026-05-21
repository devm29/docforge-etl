from __future__ import annotations

from docforge.config import Settings
from docforge.embedding.base import Embedder
from docforge.embedding.hashing import HashingEmbedder
from docforge.logs import get_logger

log = get_logger(__name__)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder()
    try:
        from docforge.embedding.fastembed import FastEmbedEmbedder

        return FastEmbedEmbedder(settings.fastembed_model, cache_dir=str(settings.data_dir / "models"))
    except Exception as exc:
        if settings.embedding_provider == "fastembed":
            raise
        log.warning("embedding.fastembed_unavailable", error=str(exc), fallback="hashing")
        return HashingEmbedder()
