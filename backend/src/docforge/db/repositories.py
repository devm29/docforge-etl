from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Row, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from docforge.db.models import (
    BlockRow,
    ChunkRow,
    DeadLetter,
    Document,
    DocumentVersion,
    Extraction,
    ExtractionField,
    ReviewItem,
    Run,
    StageCacheEntry,
    StageRun,
)
from docforge.domain.statuses import ACTIVE_RUN_STATUSES

AnyRow = Row[*tuple[Any, ...]]


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, run_id: uuid.UUID) -> Run | None:
        return await self._session.get(Run, run_id)

    async def page(self, limit: int, offset: int) -> tuple[Sequence[Run], int]:
        total = await self._session.scalar(select(func.count()).select_from(Run)) or 0
        rows = await self._session.scalars(
            select(Run).order_by(Run.created_at.desc()).limit(limit).offset(offset)
        )
        return rows.all(), total

    async def stage_summary(self, run_id: uuid.UUID) -> Sequence[AnyRow]:
        def count(status: str) -> Any:
            return func.count(case((StageRun.status == status, 1)))

        result = await self._session.execute(
            select(
                StageRun.stage,
                count("succeeded"),
                count("cached"),
                count("failed"),
                count("skipped"),
                func.coalesce(func.sum(StageRun.items_in), 0),
                func.coalesce(func.sum(StageRun.items_out), 0),
                func.coalesce(func.sum(StageRun.input_tokens), 0),
                func.coalesce(func.sum(StageRun.output_tokens), 0),
                func.coalesce(func.sum(StageRun.cost_usd), 0),
                func.coalesce(func.sum(StageRun.cost_saved_usd), 0),
                func.coalesce(func.sum(StageRun.duration_ms), 0),
            )
            .where(StageRun.run_id == run_id)
            .group_by(StageRun.stage)
        )
        return result.all()

    async def timeline_versions(
        self, run_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[Sequence[Row[DocumentVersion, Document]], int]:
        """The run's documents, one page at a time, so a large run is never read in one go."""
        touched = select(StageRun.version_id).where(StageRun.run_id == run_id).distinct().subquery()
        total = await self._session.scalar(select(func.count()).select_from(touched)) or 0
        result = await self._session.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id.in_(select(touched.c.version_id)))
            .order_by(Document.uri, DocumentVersion.version_no)
            .limit(limit)
            .offset(offset)
        )
        return result.all(), total

    async def timeline_stages(self, run_id: uuid.UUID, version_ids: list[uuid.UUID]) -> Sequence[StageRun]:
        if not version_ids:
            return []
        result = await self._session.scalars(
            select(StageRun)
            .where(StageRun.run_id == run_id, StageRun.version_id.in_(version_ids))
            .order_by(StageRun.started_at)
        )
        return result.all()

    async def active_for_source(self, source: str, since: datetime) -> Run | None:
        return await self._session.scalar(
            select(Run)
            .where(
                Run.source == source,
                Run.trigger != "replay",
                Run.status.in_(ACTIVE_RUN_STATUSES),
                Run.created_at >= since,
            )
            .order_by(Run.created_at.desc())
            .limit(1)
        )


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self._session.scalar(
            select(Document).where(Document.id == document_id).options(selectinload(Document.versions))
        )

    async def page(
        self, *, limit: int, offset: int, kind: str | None, status: str | None, query: str | None
    ) -> tuple[Sequence[AnyRow], int]:
        review_counts = (
            select(ReviewItem.document_id, func.count().label("pending"))
            .where(ReviewItem.status == "pending")
            .group_by(ReviewItem.document_id)
            .subquery()
        )
        confidence = (
            select(
                Extraction.document_id, Extraction.status, func.avg(ExtractionField.confidence).label("avg")
            )
            .join(ExtractionField, ExtractionField.extraction_id == Extraction.id)
            .where(Extraction.is_current)
            .group_by(Extraction.document_id, Extraction.status)
            .subquery()
        )
        filters: list[Any] = [Document.removed_at.is_(None)] if status != "removed" else []
        if kind:
            filters.append(Document.kind == kind)
        if status:
            filters.append(Document.status == status)
        if query:
            filters.append(Document.uri.icontains(query, autoescape=True))

        total = await self._session.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
        rows = await self._session.execute(
            select(
                Document,
                DocumentVersion.version_no,
                DocumentVersion.page_count,
                confidence.c.status,
                confidence.c.avg,
                func.coalesce(review_counts.c.pending, 0),
            )
            .outerjoin(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .outerjoin(confidence, confidence.c.document_id == Document.id)
            .outerjoin(review_counts, review_counts.c.document_id == Document.id)
            .where(*filters)
            .order_by(Document.uri)
            .limit(limit)
            .offset(offset)
        )
        return rows.all(), total

    async def version(self, document_id: uuid.UUID, version_id: uuid.UUID) -> DocumentVersion | None:
        return await self._session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id, DocumentVersion.document_id == document_id
            )
        )

    async def blocks(self, version_id: uuid.UUID) -> Sequence[BlockRow]:
        rows = await self._session.scalars(
            select(BlockRow).where(BlockRow.version_id == version_id).order_by(BlockRow.ordinal)
        )
        return rows.all()

    async def chunks(self, version_id: uuid.UUID) -> Sequence[ChunkRow]:
        rows = await self._session.scalars(
            select(ChunkRow).where(ChunkRow.version_id == version_id).order_by(ChunkRow.ordinal)
        )
        return rows.all()

    async def extraction(self, version_id: uuid.UUID) -> Extraction | None:
        return await self._session.scalar(
            select(Extraction)
            .where(Extraction.version_id == version_id)
            .options(selectinload(Extraction.fields))
            .order_by(Extraction.created_at.desc())
            .limit(1)
        )

    async def review_ids_by_field(self, field_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        if not field_ids:
            return {}
        rows = await self._session.execute(
            select(ReviewItem.field_id, ReviewItem.id).where(
                ReviewItem.field_id.in_(field_ids), ReviewItem.status == "pending"
            )
        )
        return dict(rows.all())

    async def counts_by(self, column: Any) -> dict[str, int]:
        rows = await self._session.execute(
            select(column, func.count()).where(Document.removed_at.is_(None)).group_by(column)
        )
        return {str(key) if key is not None else "unclassified": int(count) for key, count in rows.all()}


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _base(self) -> Any:
        return (
            select(ReviewItem, ExtractionField, Extraction, Document)
            .join(ExtractionField, ExtractionField.id == ReviewItem.field_id)
            .join(Extraction, Extraction.id == ReviewItem.extraction_id)
            .join(Document, Document.id == ReviewItem.document_id)
        )

    async def page(
        self, *, status: str, limit: int, offset: int
    ) -> tuple[Sequence[Row[ReviewItem, ExtractionField, Extraction, Document]], int]:
        total = (
            await self._session.scalar(
                select(func.count()).select_from(ReviewItem).where(ReviewItem.status == status)
            )
            or 0
        )
        rows = await self._session.execute(
            self._base()
            .where(ReviewItem.status == status)
            .order_by(ExtractionField.confidence, ReviewItem.created_at)
            .limit(limit)
            .offset(offset)
        )
        return rows.all(), total

    async def get(
        self, review_id: uuid.UUID, *, for_update: bool = False
    ) -> Row[ReviewItem, ExtractionField, Extraction, Document] | None:
        statement = self._base().where(ReviewItem.id == review_id)
        if for_update:
            statement = statement.with_for_update(of=[ReviewItem, ExtractionField, Extraction])
        return (await self._session.execute(statement)).first()


class DeadLetterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(
        self, *, status: str | None, run_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[Sequence[Row[DeadLetter, Document]], int]:
        filters: list[Any] = []
        if status:
            filters.append(DeadLetter.status == status)
        if run_id:
            filters.append(DeadLetter.run_id == run_id)
        total = await self._session.scalar(select(func.count()).select_from(DeadLetter).where(*filters)) or 0
        rows = await self._session.execute(
            select(DeadLetter, Document)
            .join(Document, Document.id == DeadLetter.document_id)
            .where(*filters)
            .order_by(DeadLetter.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return rows.all(), total

    async def get(self, dead_letter_id: uuid.UUID) -> DeadLetter | None:
        return await self._session.get(DeadLetter, dead_letter_id, with_for_update=True)


class StatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def scalar_count(self, model: Any, *filters: Any) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(model).where(*filters)) or 0)

    async def run_totals(self) -> AnyRow:
        result = await self._session.execute(
            select(
                func.coalesce(func.sum(Run.input_tokens + Run.output_tokens), 0),
                func.coalesce(func.sum(Run.cost_usd), 0),
                func.coalesce(func.sum(Run.cost_saved_usd), 0),
                func.coalesce(func.bool_or(Run.cost_estimated), False),
            )
        )
        row: AnyRow = result.one()
        return row

    async def cache_hits(self) -> int:
        return int(await self._session.scalar(select(func.coalesce(func.sum(StageCacheEntry.hits), 0))) or 0)
