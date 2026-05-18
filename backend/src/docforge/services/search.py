from __future__ import annotations

from sqlalchemy import select, text

from docforge.db.models import ChunkRow, Document
from docforge.db.session import SessionFactory, transaction
from docforge.embedding.base import Embedder
from docforge.services.dto import ChunkSpanOut, SearchHitOut, SearchOut
from docforge.services.mappers import document_ref


class SearchService:
    """Semantic retrieval over current chunks, the read path a RAG application would use.

    The HNSW index is partial (current chunks only) and filters for model, kind and removed
    documents are applied during the scan with pgvector's iterative scan, so a filtered query
    still returns ``limit`` hits however many old versions have piled up.
    """

    def __init__(self, sessions: SessionFactory, embedder: Embedder) -> None:
        self._sessions = sessions
        self._embedder = embedder

    async def search(self, query: str, *, limit: int, kind: str | None) -> SearchOut:
        [vector] = await self._embedder.embed([query])
        distance = ChunkRow.embedding.cosine_distance(vector).label("distance")
        statement = (
            select(ChunkRow, Document, distance)
            .join(Document, Document.id == ChunkRow.document_id)
            .where(
                ChunkRow.is_current,
                ChunkRow.embedding_model == self._embedder.name,
                Document.removed_at.is_(None),
            )
            .order_by(distance)
            .limit(limit)
        )
        if kind:
            statement = statement.where(Document.kind == kind)
        async with transaction(self._sessions) as session:
            await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
            rows = sorted((await session.execute(statement)).all(), key=lambda row: float(row[2]))
        return SearchOut(
            query=query,
            model=self._embedder.name,
            hits=[
                SearchHitOut(
                    chunk_id=chunk.id,
                    document=document_ref(document),
                    score=round(1.0 - float(dist), 4),
                    text=chunk.text,
                    heading_path=[str(h) for h in chunk.heading_path],
                    page_start=chunk.page_start,
                    spans=[ChunkSpanOut.model_validate(span) for span in chunk.spans],
                )
                for chunk, document, dist in rows
            ],
        )
