from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import uuid
from pathlib import Path

from sqlalchemy import select, text

from docforge.config import BACKEND_ROOT, Settings, get_settings
from docforge.container import Container, build_container
from docforge.corpus.generator import amend_invoice, generate_corpus
from docforge.db.models import Base, Document, ExtractionField, ReviewItem
from docforge.domain.statuses import RunTrigger
from docforge.logs import configure_logging
from docforge.pipeline.queue import InlineJobQueue
from docforge.services.dto import ApproveReviewIn, CreateRunIn, EditReviewIn, RunOut
from docforge.services.reviews import ReviewService
from docforge.services.runs import RunService


class InlinePipeline:
    """Runs the full pipeline in-process (no Redis), sharing code paths with the worker."""

    def __init__(self, container: Container) -> None:
        self.container = container
        self.queue = InlineJobQueue(concurrency=container.settings.worker_max_jobs)
        self.pipeline = container.pipeline(self.queue)
        self.queue.bind(scan=self._scan, process=self._process, finalize=self.pipeline.finalize)
        self.runs = RunService(
            container.sessions,
            self.queue,
            container.sources,
            container.exporter,
            self.pipeline.version,
            stale_after=container.stale_after,
        )

    async def _scan(self, run_id: uuid.UUID) -> None:
        try:
            await self.pipeline.scan(run_id)
        except Exception as exc:
            await self.pipeline.fail_run(run_id, f"scan failed: {exc}")
            raise

    async def _process(self, run_id: uuid.UUID, version_id: uuid.UUID) -> None:
        try:
            await self.pipeline.process(run_id, version_id)
        except Exception as exc:
            await self.pipeline.fail_unexpectedly(run_id, version_id, exc)
            raise

    async def run(self, request: CreateRunIn, trigger: RunTrigger = "cli") -> RunOut:
        started = await self.runs.start(request, trigger=trigger)
        await self.queue.drain()
        detail = await self.runs.detail(started.id)
        return detail.run


def _print_run(label: str, run: RunOut) -> None:
    cost = f"${run.cost_usd:.4f}{' est.' if run.cost_estimated else ''}"
    print(
        f"{label:<28} {run.status:<10} seen={run.docs_seen:<3} changed={run.docs_changed:<3} "
        f"unchanged={run.docs_unchanged:<3} ok={run.docs_succeeded:<3} failed={run.docs_failed:<3} "
        f"tokens={run.input_tokens + run.output_tokens:<7} cost={cost:<14} saved=${run.cost_saved_usd:.4f}"
    )


def migrate(settings: Settings) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


async def reset(container: Container) -> None:
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with container.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    for path in (container.settings.blob_dir, container.settings.export_dir):
        shutil.rmtree(path, ignore_errors=True)


def demo_inbox(settings: Settings) -> Path:
    return (settings.data_dir / "inbox").resolve()


async def seed(settings: Settings) -> None:
    """Builds a realistic history: an initial load, a no-op rerun, an amended invoice, a review.

    It only ever writes to DocForge's own demo inbox under DATA_DIR; pointing FS_SOURCE_ROOT at a
    real folder makes seeding refuse rather than overwrite it.
    """
    inbox = demo_inbox(settings)
    if settings.fs_source_root.resolve() != inbox:
        raise SystemExit(
            f"seed writes the sample corpus to {inbox}, but FS_SOURCE_ROOT is {settings.fs_source_root}. "
            "Unset FS_SOURCE_ROOT (or point it at the demo inbox) to seed."
        )
    shutil.rmtree(inbox, ignore_errors=True)
    shutil.copytree(settings.corpus_dir, inbox)

    container = build_container(settings)
    try:
        await reset(container)
        inline = InlinePipeline(container)
        _print_run("1. initial load", await inline.run(CreateRunIn(), trigger="api"))
        _print_run("2. nothing changed", await inline.run(CreateRunIn(), trigger="schedule"))
        amend_invoice(inbox)
        _print_run("3. one invoice re-issued", await inline.run(CreateRunIn(), trigger="api"))

        reviews = ReviewService(container.sessions, container.schemas, container.entities)
        async with container.sessions() as session:
            due_date_item = await session.scalar(
                select(ReviewItem.id)
                .join(ExtractionField, ExtractionField.id == ReviewItem.field_id)
                .join(Document, Document.id == ReviewItem.document_id)
                .where(
                    ReviewItem.status == "pending",
                    ExtractionField.path == "due_date",
                    Document.filename.like("quantum-print%"),
                )
            )
        if due_date_item is not None:
            await reviews.approve(
                due_date_item, ApproveReviewIn(note="Due on receipt."), reviewer="maya.chen"
            )
            print("4. review approved          quantum-print due_date (due on receipt)")

        async with container.sessions() as session:
            term_item = await session.scalar(
                select(ReviewItem.id)
                .join(ExtractionField, ExtractionField.id == ReviewItem.field_id)
                .join(Document, Document.id == ReviewItem.document_id)
                .where(
                    ReviewItem.status == "pending",
                    ExtractionField.path == "term_months",
                    Document.filename.like("orion-labs%"),
                )
            )
        if term_item is not None:
            await reviews.edit(term_item, EditReviewIn(value=24, note="Two-year NDA."), reviewer="maya.chen")
            print("5. review edited            orion-labs term_months -> 24")

        _print_run("6. full reprocess (force)", await inline.run(CreateRunIn(force=True), trigger="api"))
    finally:
        await container.close()


async def run_once(settings: Settings, request: CreateRunIn) -> None:
    container = build_container(settings)
    try:
        _print_run("run", await InlinePipeline(container).run(request))
    finally:
        await container.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docforge", description="DocForge pipeline tools")
    commands = parser.add_subparsers(dest="command", required=True)
    corpus = commands.add_parser("generate-corpus", help="write the bundled sample corpus")
    corpus.add_argument("--dir", type=Path, default=None)
    commands.add_parser("migrate", help="apply database migrations")
    seed_cmd = commands.add_parser("seed", help="reset the database and load a realistic demo history")
    seed_cmd.add_argument(
        "--yes", action="store_true", help="confirm: every table is truncated and the demo inbox replaced"
    )
    run = commands.add_parser("run", help="run the pipeline in-process, without a worker")
    run.add_argument("--source", default="fs")
    run.add_argument("--prefix", default="")
    run.add_argument("--force", action="store_true", help="reprocess unchanged documents too")
    run.add_argument("--bypass-cache", action="store_true", help="recompute every stage")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging("WARNING" if args.command in {"seed", "run"} else settings.log_level)
    match args.command:
        case "generate-corpus":
            target = args.dir or settings.corpus_dir
            for path in generate_corpus(target):
                print(path.relative_to(target))
        case "migrate":
            migrate(settings)
        case "seed":
            if not args.yes:
                print(
                    "seed truncates every DocForge table and replaces the demo inbox; "
                    "re-run with --yes to continue.",
                    file=sys.stderr,
                )
                return 2
            migrate(settings)
            asyncio.run(seed(settings))
        case "run":
            asyncio.run(
                run_once(
                    settings,
                    CreateRunIn(
                        source=args.source,
                        prefix=args.prefix,
                        force=args.force,
                        bypass_cache=args.bypass_cache,
                    ),
                )
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
