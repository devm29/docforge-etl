from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update

from docforge.db.models import Document, DocumentVersion, Run
from docforge.db.repositories import DeadLetterRepository
from docforge.db.session import SessionFactory, transaction
from docforge.errors import ConflictError, NotFoundError
from docforge.pipeline.queue import JobQueue
from docforge.services.dto import DeadLetterOut, Page, RunOut
from docforge.services.mappers import dead_letter_out, run_out


class DeadLetterService:
    def __init__(self, sessions: SessionFactory, queue: JobQueue, pipeline_version: str) -> None:
        self._sessions = sessions
        self._queue = queue
        self._pipeline_version = pipeline_version

    async def page(
        self, *, status: str | None, run_id: uuid.UUID | None, limit: int, offset: int
    ) -> Page[DeadLetterOut]:
        async with self._sessions() as session:
            rows, total = await DeadLetterRepository(session).page(
                status=status, run_id=run_id, limit=limit, offset=offset
            )
            return Page[DeadLetterOut](
                items=[dead_letter_out(letter, document) for letter, document in rows],
                total=total,
                limit=limit,
                offset=offset,
            )

    async def replay(self, dead_letter_id: uuid.UUID) -> RunOut:
        """Re-queues the failed version in a new single-document run.

        Stages that succeeded before the failure are cache hits, so a replay only pays for the
        stage that failed and whatever depends on it.
        """
        async with transaction(self._sessions) as session:
            letter = await DeadLetterRepository(session).get(dead_letter_id)
            if letter is None:
                raise NotFoundError(f"dead letter {dead_letter_id} not found")
            if letter.status != "open":
                raise ConflictError(f"dead letter is already {letter.status}")
            document = await session.get(Document, letter.document_id, with_for_update=True)
            version = await session.get(DocumentVersion, letter.version_id)
            if document is None or version is None:
                raise NotFoundError("the document for this dead letter no longer exists")
            if document.current_version_id is not None and document.current_version_id != version.id:
                current = await session.get(DocumentVersion, document.current_version_id)
                if current is not None and current.version_no > version.version_no:
                    raise ConflictError(
                        f"version {version.version_no} is older than the current version "
                        f"{current.version_no}; replaying it would not change anything"
                    )
            run = Run(
                trigger="replay",
                source=document.source,
                prefix=document.uri,
                status="running",
                pipeline_version=self._pipeline_version,
                docs_seen=1,
                docs_changed=1,
                started_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            await session.execute(
                update(DocumentVersion)
                .where(DocumentVersion.id == letter.version_id)
                .values(status="queued", error=None)
            )
            document.status = "processing"
            letter.status = "replayed"
            letter.replayed_at = datetime.now(UTC)
            letter.replay_run_id = run.id
            result = run_out(run)
            version_id = letter.version_id
        await self._queue.enqueue_process(result.id, version_id)
        return result
