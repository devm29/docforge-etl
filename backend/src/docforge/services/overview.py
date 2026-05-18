from __future__ import annotations

from sqlalchemy import select

from docforge.db.models import ChunkRow, DeadLetter, Document, ReviewItem, Run, StageCacheEntry
from docforge.db.repositories import DocumentRepository, StatsRepository
from docforge.db.session import SessionFactory
from docforge.services.dto import OverviewOut
from docforge.services.mappers import run_out


class OverviewService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def overview(self) -> OverviewOut:
        async with self._sessions() as session:
            stats = StatsRepository(session)
            documents = DocumentRepository(session)
            tokens, cost, saved, estimated = await stats.run_totals()
            recent = await session.scalars(select(Run).order_by(Run.created_at.desc()).limit(8))
            return OverviewOut(
                documents_total=await stats.scalar_count(Document, Document.removed_at.is_(None)),
                documents_by_status=await documents.counts_by(Document.status),
                documents_by_kind=await documents.counts_by(Document.kind),
                chunks_total=await stats.scalar_count(ChunkRow, ChunkRow.is_current),
                runs_total=await stats.scalar_count(Run),
                tokens_total=int(tokens),
                cost_total_usd=float(cost),
                cost_saved_usd=float(saved),
                cost_estimated=bool(estimated),
                pending_reviews=await stats.scalar_count(ReviewItem, ReviewItem.status == "pending"),
                open_dead_letters=await stats.scalar_count(DeadLetter, DeadLetter.status == "open"),
                cache_entries=await stats.scalar_count(StageCacheEntry),
                cache_hits=await stats.cache_hits(),
                recent_runs=[run_out(r) for r in recent],
            )
