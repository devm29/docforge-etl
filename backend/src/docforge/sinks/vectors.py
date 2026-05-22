from __future__ import annotations

import uuid

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from docforge.db.models import ChunkRow
from docforge.domain.records import ChunkRecord


class PgVectorSink:
    """Writes chunks with their vectors and lineage. Older versions stay queryable but not current."""

    async def write(
        self,
        session: AsyncSession,
        *,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        chunks: list[ChunkRecord],
        vectors: list[list[float]],
        model: str,
        current: bool = True,
    ) -> int:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if current:
            await self.retire(session, document_id)
        await session.execute(delete(ChunkRow).where(ChunkRow.version_id == version_id))
        session.add_all(
            ChunkRow(
                document_id=document_id,
                version_id=version_id,
                ordinal=chunk.index,
                text=chunk.text,
                heading_path=chunk.heading_path,
                token_count=chunk.token_count,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                spans=[span.model_dump(mode="json") for span in chunk.spans],
                content_hash=chunk.content_hash,
                is_table=chunk.is_table,
                is_current=current,
                embedding=vector,
                embedding_model=model,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        )
        return len(chunks)

    async def retire(self, session: AsyncSession, document_id: uuid.UUID) -> None:
        await session.execute(
            update(ChunkRow)
            .where(ChunkRow.document_id == document_id, ChunkRow.is_current)
            .values(is_current=False)
        )
