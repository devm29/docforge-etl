from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update

from docforge.cli import InlinePipeline
from docforge.corpus.generator import amend_invoice
from docforge.db.models import (
    ChunkRow,
    ContractRecord,
    DeadLetter,
    Document,
    DocumentVersion,
    Extraction,
    InvoiceRecord,
    ReviewItem,
    Run,
)
from docforge.errors import ConflictError, InvalidRequestError
from docforge.extraction.schemas.invoice import Invoice
from docforge.services.dead_letters import DeadLetterService
from docforge.services.dto import CreateRunIn, EditReviewIn
from docforge.services.reviews import ReviewService

pytestmark = pytest.mark.integration


async def _document(inline: InlinePipeline, filename: str) -> Document:
    async with inline.container.sessions() as session:
        document = await session.scalar(select(Document).where(Document.filename == filename))
    assert document is not None
    return document


async def _new_run(inline: InlinePipeline, **values: object) -> uuid.UUID:
    async with inline.container.sessions() as session, session.begin():
        defaults: dict[str, object] = {
            "trigger": "api",
            "source": "fs",
            "prefix": "",
            "status": "queued",
            "pipeline_version": inline.pipeline.version,
        }
        run = Run(**(defaults | values))
        session.add(run)
        await session.flush()
        return run.id


async def _run(inline: InlinePipeline, run_id: uuid.UUID) -> Run:
    async with inline.container.sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    return run


async def test_a_wildcard_prefix_cannot_retire_the_corpus(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    with pytest.raises(ValidationError):
        CreateRunIn(prefix="../outside")

    started = await inline.runs.start(CreateRunIn(prefix="%"))
    with pytest.raises(InvalidRequestError, match="does not exist"):
        await inline.queue.drain()

    run = await _run(inline, started.id)
    assert run.status == "failed" and run.error and "does not exist" in run.error
    async with inline.container.sessions() as session:
        removed = await session.scalar(
            select(func.count()).select_from(Document).where(Document.removed_at.is_not(None))
        )
        live = await session.scalar(select(func.count()).select_from(ChunkRow).where(ChunkRow.is_current))
    assert removed == 0 and live


async def test_a_prefixed_run_only_retires_documents_under_its_folder(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    root = Path(inline.container.settings.fs_source_root)
    (root / "invoices/2026-04/atlas-facilities-AF-7710.pdf").unlink()
    (root / "invoices/2026-03/northwind-INV-24017.pdf").unlink()

    run = await inline.run(CreateRunIn(prefix="invoices/2026-03/"))

    assert (run.prefix, run.docs_seen, run.docs_removed) == ("invoices/2026-03", 3, 1)
    assert (await _document(inline, "northwind-INV-24017.pdf")).status == "removed"
    assert (await _document(inline, "atlas-facilities-AF-7710.pdf")).status == "ready"


async def test_concurrent_runs_on_one_source_both_finish(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    first, second = await _new_run(inline, force=True), await _new_run(inline, force=True)

    await asyncio.gather(inline.pipeline.scan(first), inline.pipeline.scan(second))
    await inline.queue.drain()

    for run_id in (first, second):
        run = await _run(inline, run_id)
        assert run.status == "partial" and run.docs_changed == 14
    async with inline.container.sessions() as session:
        documents = (await session.scalars(select(Document).where(Document.status == "ready"))).all()
        for document in documents:
            newest = await session.scalar(
                select(DocumentVersion.id)
                .where(DocumentVersion.document_id == document.id, DocumentVersion.status == "succeeded")
                .order_by(DocumentVersion.version_no.desc())
                .limit(1)
            )
            assert document.current_version_id == newest


async def test_a_scan_that_crashed_mid_way_is_resumed(inline: InlinePipeline) -> None:
    run_id = await _new_run(inline, started_at=datetime.now(UTC))
    async with inline.container.sessions() as session, session.begin():
        await session.execute(update(Run).where(Run.id == run_id).values(status="scanning"))

    await inline.pipeline.scan(run_id)
    await inline.queue.drain()

    run = await _run(inline, run_id)
    assert (run.status, run.docs_changed) == ("partial", 14)


async def test_finalize_is_idempotent_and_recovers_a_lost_export(inline: InlinePipeline) -> None:
    done = await inline.run(CreateRunIn())
    async with inline.container.sessions() as session, session.begin():
        await session.execute(
            update(Run)
            .where(Run.id == done.id)
            .values(status="running", finished_at=None, export_path=None, cost_usd=0)
        )

    await inline.pipeline.finalize(done.id)
    await inline.pipeline.finalize(done.id)

    run = await _run(inline, done.id)
    assert run.status == "partial" and run.finished_at is not None and run.export_path is not None
    assert float(run.cost_usd) == pytest.approx(done.cost_usd)
    assert float(run.cost_saved_usd) == pytest.approx(done.cost_saved_usd)
    assert inline.container.exporter.path_for(done.id, "chunks").exists()


async def test_a_load_that_committed_before_a_crash_is_settled_once(inline: InlinePipeline) -> None:
    done = await inline.run(CreateRunIn())
    document = await _document(inline, "northwind-INV-24017.pdf")
    assert document.current_version_id is not None
    async with inline.container.sessions() as session, session.begin():
        await session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == document.current_version_id)
            .values(status="processing")
        )
        await session.execute(
            update(Run)
            .where(Run.id == done.id)
            .values(status="running", docs_succeeded=Run.docs_succeeded - 1, finished_at=None)
        )

    outcome = await inline.pipeline.process(done.id, document.current_version_id)
    again = await inline.pipeline.process(done.id, document.current_version_id)
    await inline.queue.drain()

    assert (outcome, again) == ("succeeded", "succeeded")
    run = await _run(inline, done.id)
    assert (run.status, run.docs_succeeded, run.docs_failed) == ("partial", 13, 1)


async def test_an_older_version_finishing_late_never_becomes_current(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    amend_invoice(Path(inline.container.settings.fs_source_root))
    await inline.run(CreateRunIn())
    document = await _document(inline, "northwind-INV-24017.pdf")
    async with inline.container.sessions() as session, session.begin():
        old = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id, DocumentVersion.version_no == 1
            )
        )
        assert old is not None
        letter = DeadLetter(
            run_id=old.run_id,
            version_id=old.id,
            document_id=document.id,
            stage="extract",
            error_type="transient_error",
            error="simulated",
            attempts=3,
            retryable=True,
        )
        session.add(letter)
        old.status = "queued"
    with pytest.raises(ConflictError, match="older than the current version"):
        await DeadLetterService(inline.container.sessions, inline.queue, inline.pipeline.version).replay(
            letter.id
        )

    # Forced, so detect does not stop it as a duplicate of the bytes now on disk.
    late = await _new_run(inline, status="running", docs_changed=1, force=True)
    assert await inline.pipeline.process(late, old.id) == "succeeded"
    await inline.queue.drain()

    async with inline.container.sessions() as session:
        refreshed = await session.get(Document, document.id)
        assert refreshed is not None and refreshed.current_version_id == document.current_version_id
        invoice = await session.scalar(select(InvoiceRecord).where(InvoiceRecord.document_id == document.id))
        assert invoice is not None and str(invoice.total) == "9572.18"
        stale = await session.scalar(
            select(func.count())
            .select_from(ChunkRow)
            .where(ChunkRow.version_id == old.id, ChunkRow.is_current)
        )
        current_extractions = await session.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(Extraction.document_id == document.id, Extraction.is_current)
        )
    assert stale == 0 and current_extractions == 1
    assert (await _run(inline, late)).status == "succeeded"


async def test_a_reclassified_document_leaves_no_stale_typed_rows(
    inline: InlinePipeline, corpus_dir: Path
) -> None:
    await inline.run(CreateRunIn())
    root = Path(inline.container.settings.fs_source_root)
    target = root / "invoices/2026-03/quantum-print-QP-0931.pdf"
    target.write_bytes((corpus_dir / "contracts/harbor-way-lease-amendment.pdf").read_bytes())

    await inline.run(CreateRunIn())

    document = await _document(inline, "quantum-print-QP-0931.pdf")
    assert document.kind == "contract"
    async with inline.container.sessions() as session:
        invoices = await session.scalar(
            select(func.count()).select_from(InvoiceRecord).where(InvoiceRecord.document_id == document.id)
        )
        contracts = await session.scalar(
            select(func.count()).select_from(ContractRecord).where(ContractRecord.document_id == document.id)
        )
        current = (
            await session.scalars(
                select(Extraction.schema_name).where(
                    Extraction.document_id == document.id, Extraction.is_current
                )
            )
        ).all()
        pending = await session.scalar(
            select(func.count())
            .select_from(ReviewItem)
            .join(Extraction, Extraction.id == ReviewItem.extraction_id)
            .where(
                ReviewItem.document_id == document.id,
                ReviewItem.status == "pending",
                Extraction.schema_name == "invoice",
            )
        )
    assert (invoices, contracts, list(current), pending) == (0, 1, ["contract"], 0)


async def test_a_removed_document_is_taken_out_of_every_sink(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    document = await _document(inline, "quantum-print-QP-0931.pdf")
    root = Path(inline.container.settings.fs_source_root)
    (root / "invoices/2026-03/quantum-print-QP-0931.pdf").unlink()

    run = await inline.run(CreateRunIn())

    assert run.docs_removed == 1
    async with inline.container.sessions() as session:
        invoice = await session.scalar(select(InvoiceRecord).where(InvoiceRecord.document_id == document.id))
        current = await session.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(Extraction.document_id == document.id, Extraction.is_current)
        )
        statuses = set(
            (
                await session.scalars(select(ReviewItem.status).where(ReviewItem.document_id == document.id))
            ).all()
        )
    assert invoice is None and current == 0 and statuses == {"superseded"}


async def test_review_edits_enforce_the_field_constraints(inline: InlinePipeline) -> None:
    await inline.run(CreateRunIn())
    reviews = ReviewService(inline.container.sessions, inline.container.schemas, inline.container.entities)
    pending = await reviews.page(status="pending", limit=50, offset=0)
    term = next(i for i in pending.items if i.field.path == "term_months")

    with pytest.raises(InvalidRequestError, match="term_months"):
        await reviews.edit(term.id, EditReviewIn(value=-3), reviewer="qa")
    with pytest.raises(InvalidRequestError, match="currency"):
        ReviewService._coerce(Invoice.model_fields["currency"], "currency", "usd")

    result = await reviews.edit(term.id, EditReviewIn(value=24), reviewer="qa")
    assert result.item.resolved_value == 24 and result.item.reviewer == "qa"


async def test_the_reaper_restarts_a_run_whose_scan_job_was_lost(inline: InlinePipeline) -> None:
    run_id = await _new_run(inline, created_at=datetime.now(UTC) - timedelta(hours=1))

    assert await inline.pipeline.reap_stale() == 1
    await inline.queue.drain()

    assert (await _run(inline, run_id)).status == "partial"
    assert await inline.pipeline.reap_stale() == 0
