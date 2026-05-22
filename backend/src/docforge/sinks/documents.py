from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from docforge.db.models import BlockRow
from docforge.domain.documents import DocumentModel


class BlockSink:
    """Persists the normalized document model so the viewer can render any version's layout."""

    async def write(self, session: AsyncSession, version_id: uuid.UUID, model: DocumentModel) -> int:
        await session.execute(delete(BlockRow).where(BlockRow.version_id == version_id))
        rows = [
            BlockRow(
                version_id=version_id,
                block_key=block.id,
                page=block.page,
                ordinal=ordinal,
                kind=block.kind.value,
                geometry=block.geometry.value,
                text=block.text,
                x0=block.bbox.x0,
                top=block.bbox.top,
                x1=block.bbox.x1,
                bottom=block.bbox.bottom,
                heading_level=block.heading_level,
                rows=block.rows,
                words=[
                    [word.text, word.bbox.x0, word.bbox.top, word.bbox.x1, word.bbox.bottom]
                    for word in block.words
                ],
                cell_range=block.cell_range,
            )
            for ordinal, block in enumerate(model.iter_blocks())
        ]
        session.add_all(rows)
        return len(rows)
