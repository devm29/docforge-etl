from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest
from sqlalchemy import func, select

from docforge.cli import InlinePipeline
from docforge.corpus.generator import amend_invoice
from docforge.db.models import (
    ChunkRow,
    DeadLetter,
    Document,
    Extraction,
    InvoiceRecord,
    ReviewItem,
    StageRun,
)
from docforge.errors import InvalidRequestError
from docforge.services.dead_letters import DeadLetterService
from docforge.services.dto import ApproveReviewIn, CreateRunIn, EditReviewIn
from docforge.services.reviews import ReviewService

pytestmark = pytest.mark.integration


async def _count(inline: InlinePipeline, statement: object) -> int:
    async with inline.container.sessions() as session:
        return int(await session.scalar(statement) or 0)  # type: ignore[call-overload]


async def test_initial_run_loads_every_sink(inline: InlinePipeline) -> None:
    run = await inline.run(CreateRunIn())

    assert run.status == "partial"
    assert (run.docs_seen, run.docs_changed, run.docs_succeeded, run.docs_failed) == (14, 14, 13, 1)
    assert run.input_tokens > 0 and run.cost_usd > 0 and run.cost_estimated
    assert await _count(inline, select(func.count()).select_from(InvoiceRecord)) == 7
    assert await _count(inline, select(func.count()).select_from(ChunkRow).where(ChunkRow.is_current)) > 50
    assert await _count(inline, select(func.count()).select_from(ReviewItem)) == 4

    async with inline.container.sessions() as session:
        letter = await session.scalar(select(DeadLetter))
        assert letter is not None
        assert (letter.stage, letter.error_type, letter.retryable) == ("parse", "parse_error", False)
        statuses = dict(
            (await session.execute(select(Extraction.status, func.count()).group_by(Extraction.status))).all()
        )
        assert statuses == {"valid": 8, "needs_review": 3, "invalid": 1}

    export = inline.container.exporter.path_for(run.id, "fields")
    assert pq.read_table(export).num_rows == 132


async def test_unchanged_documents_are_never_reprocessed(inline: InlinePipeline) -> None:
    first = await inline.run(CreateRunIn())
    second = await inline.run(CreateRunIn())

    assert (second.docs_changed, second.docs_unchanged, second.status) == (0, 14, "succeeded")
    assert second.cost_usd == 0 and second.input_tokens == 0
    assert second.cost_saved_usd == pytest.approx(first.cost_usd, rel=1e-6)
    assert (
        await _count(inline, select(func.count()).select_from(StageRun).where(StageRun.run_id == second.id))
        == 0
    )


async def test_only_the_changed_document_and_changed_chunks_are_recomputed(
    inline: InlinePipeline, settings: object
) -> None:
    await inline.run(CreateRunIn())
    amend_invoice(Path(inline.container.settings.fs_source_root))

    run = await inline.run(CreateRunIn())

    assert (run.docs_changed, run.docs_succeeded) == (1, 1)
    async with inline.container.sessions() as session:
        embed = await session.scalar(
            select(StageRun).where(StageRun.run_id == run.id, StageRun.stage == "embed")
        )
        assert embed is not None
        assert embed.detail["reused"] > 0 and 0 < embed.items_out < embed.items_in
        document = await session.scalar(
            select(Document).where(Document.filename == "northwind-INV-24017.pdf")
        )
        assert document is not None
        invoice = await session.scalar(select(InvoiceRecord).where(InvoiceRecord.document_id == document.id))
        assert invoice is not None and str(invoice.total) == "9572.18"
        current = await session.scalar(
            select(func.count())
            .select_from(ChunkRow)
            .where(ChunkRow.document_id == document.id, ChunkRow.is_current)
        )
        stale = await session.scalar(
            select(func.count())
            .select_from(ChunkRow)
            .where(ChunkRow.document_id == document.id, ChunkRow.is_current.is_(False))
        )
        assert current and stale


async def test_forced_reprocess_is_served_from_the_stage_cache(inline: InlinePipeline) -> None:
    first = await inline.run(CreateRunIn())
    forced = await inline.run(CreateRunIn(force=True))

    assert forced.docs_changed == 14
    assert forced.cost_usd == 0
    assert forced.cost_saved_usd == pytest.approx(first.cost_usd, rel=1e-6)
    async with inline.container.sessions() as session:
        statuses = dict(
            (
                await session.execute(
                    select(StageRun.status, func.count())
                    .where(StageRun.run_id == forced.id)
                    .group_by(StageRun.status)
                )
            ).all()
        )
    assert statuses["cached"] == 13 * 4
    assert statuses["succeeded"] == 13 * 2 + 1


async def test_review_decisions_survive_reprocessing(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    reviews = ReviewService(inline.container.sessions, inline.container.schemas, inline.container.entities)
    pending = await reviews.page(status="pending", limit=50, offset=0)
    due = next(i for i in pending.items if i.field.path == "due_date")

    result = await reviews.approve(due.id, ApproveReviewIn(), reviewer="test")
    assert result.extraction_status == "approved"

    await inline.run(CreateRunIn(force=True))
    after = await reviews.page(status="pending", limit=50, offset=0)
    assert all(i.field.path != "due_date" for i in after.items)
    assert after.total == pending.total - 1


async def test_reviewers_cannot_approve_a_record_that_breaks_the_schema(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    reviews = ReviewService(inline.container.sessions, inline.container.schemas, inline.container.entities)
    pending = await reviews.page(status="pending", limit=50, offset=0)
    total = next(i for i in pending.items if i.field.path == "total")

    with pytest.raises(InvalidRequestError, match="total"):
        await reviews.approve(total.id, ApproveReviewIn(), reviewer="test")
    with pytest.raises(InvalidRequestError):
        await reviews.edit(total.id, EditReviewIn(value="not money"), reviewer="test")

    fixed = await reviews.edit(total.id, EditReviewIn(value="6322.40", note="vendor typo"), reviewer="test")
    assert fixed.extraction_status == "approved"
    assert fixed.item.resolved_value == "6322.40"
    async with inline.container.sessions() as session:
        invoice = await session.scalar(
            select(InvoiceRecord).where(InvoiceRecord.invoice_number == "BL-55302")
        )
        assert invoice is not None and str(invoice.total) == "6322.40"


async def test_dead_letters_can_be_replayed_after_the_file_is_fixed(
    inline: InlinePipeline, corpus_dir: Path
) -> None:
    await inline.run(CreateRunIn())
    root = Path(inline.container.settings.fs_source_root)
    broken = root / "inbox-scans/scan-2026-04-17-0042.pdf"
    broken.write_bytes((corpus_dir / "contracts/harbor-way-lease-amendment.pdf").read_bytes())

    async with inline.container.sessions() as session:
        letter = await session.scalar(select(DeadLetter))
    assert letter is not None
    service = DeadLetterService(inline.container.sessions, inline.queue, inline.pipeline.version)
    replay = await service.replay(letter.id)
    await inline.queue.drain()

    detail = await inline.runs.detail(replay.id)
    assert detail.run.status == "succeeded" and detail.run.docs_succeeded == 1
    exported = pq.read_table(inline.container.exporter.path_for(replay.id, "chunks"))
    assert exported.num_rows > 0
    async with inline.container.sessions() as session:
        document = await session.get(Document, letter.document_id)
        assert document is not None and document.status == "ready" and document.kind == "contract"


async def test_removed_files_are_retired_from_retrieval(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    root = Path(inline.container.settings.fs_source_root)
    (root / "reference/vendor-master.csv").unlink()

    run = await inline.run(CreateRunIn())

    assert (run.docs_removed, run.docs_changed) == (1, 0)
    async with inline.container.sessions() as session:
        document = await session.scalar(select(Document).where(Document.filename == "vendor-master.csv"))
        assert document is not None and document.status == "removed" and document.removed_at is not None
        live = await session.scalar(
            select(func.count())
            .select_from(ChunkRow)
            .where(ChunkRow.document_id == document.id, ChunkRow.is_current)
        )
        assert live == 0


async def test_same_bytes_under_a_new_fingerprint_stop_after_detect(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    async with inline.container.sessions() as session, session.begin():
        document = await session.scalar(
            select(Document).where(Document.filename == "atlas-facilities-AF-7710.pdf")
        )
        assert document is not None
        document.fingerprint = "etag:re-uploaded"

    run = await inline.run(CreateRunIn())

    assert (run.docs_changed, run.docs_deduplicated, run.status) == (1, 1, "succeeded")
    async with inline.container.sessions() as session:
        stages = (
            await session.execute(select(StageRun.stage, StageRun.status).where(StageRun.run_id == run.id))
        ).all()
    assert dict(stages) == {
        "detect": "skipped",
        "parse": "skipped",
        "chunk": "skipped",
        "embed": "skipped",
        "extract": "skipped",
        "load": "skipped",
    }
