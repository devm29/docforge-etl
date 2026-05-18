from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docforge.db.models import Document, DocumentVersion
from docforge.db.session import SessionFactory, transaction
from docforge.domain.documents import DocumentModel
from docforge.errors import PermanentError
from docforge.pipeline.core import DocumentRef, StageInputs, StageMetrics, StageResult
from docforge.pipeline.stages import ChunkSet, DetectOutput, EmbeddingSet, ExtractOutput, LoadOutput
from docforge.sinks.documents import BlockSink
from docforge.sinks.entities import EntitySink
from docforge.sinks.vectors import PgVectorSink


class LoadStage:
    """Writes every sink for a version in one transaction, then makes it the document's current version.

    It is not memoized: sinks are idempotent (replace-by-version), and a document that returns to an
    earlier content hash must still be re-pointed even though every upstream stage is a cache hit.

    Versions can finish out of order (concurrent runs, retries, a dead letter replayed late). Only a
    version newer than the current one becomes current; an older one is stored for history without
    touching search, typed tables or the review queue. The version's terminal status is not set
    here: the pipeline service settles it together with the run counters.
    """

    name = "load"
    depends_on = ("detect", "parse", "chunk", "embed", "extract")
    output_type = LoadOutput
    cacheable = False

    def __init__(
        self, sessions: SessionFactory, blocks: BlockSink, vectors: PgVectorSink, entities: EntitySink
    ) -> None:
        self._sessions = sessions
        self._blocks = blocks
        self._vectors = vectors
        self._entities = entities

    def config_version(self) -> str:
        return "load-1"

    def identity(self, output: BaseModel, key: str) -> str:
        return key

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[LoadOutput]:
        detected = inputs.get("detect", DetectOutput)
        model = inputs.get("parse", DocumentModel)
        chunks = inputs.get("chunk", ChunkSet).chunks
        embeddings = inputs.get("embed", EmbeddingSet)
        extracted = inputs.get("extract", ExtractOutput)

        async with transaction(self._sessions) as session:
            current = await self._becomes_current(session, doc)
            block_count = await self._blocks.write(session, doc.version_id, model)
            chunk_count = await self._vectors.write(
                session,
                document_id=doc.document_id,
                version_id=doc.version_id,
                chunks=chunks,
                vectors=embeddings.vectors,
                model=embeddings.model,
                current=current,
            )
            fields = reviews = 0
            status: str | None = None
            if extracted.result is not None:
                extraction, reviews = await self._entities.write(
                    session,
                    document_id=doc.document_id,
                    version_id=doc.version_id,
                    result=extracted.result,
                    current=current,
                )
                fields = len(extracted.result.fields)
                status = extraction.status
            elif current:
                await self._entities.retire(session, doc.document_id)

            now = datetime.now(UTC)
            await session.execute(
                update(DocumentVersion)
                .where(DocumentVersion.id == doc.version_id)
                .values(
                    content_hash=detected.content_hash,
                    blob_key=detected.blob_key,
                    format=detected.format.value,
                    page_count=model.page_count,
                    page_sizes=[
                        {"number": p.number, "width": p.width, "height": p.height, "label": p.label}
                        for p in model.pages
                    ],
                    error=None,
                    processed_at=now,
                )
            )
            if current:
                await session.execute(
                    update(Document)
                    .where(Document.id == doc.document_id)
                    .values(
                        current_version_id=doc.version_id,
                        content_hash=detected.content_hash,
                        format=detected.format.value,
                        kind=extracted.schema_name,
                        status="ready",
                    )
                )

        output = LoadOutput(
            blocks=block_count,
            chunks=chunk_count,
            fields=fields,
            review_items=reviews,
            entity=extracted.schema_name,
            extraction_status=status,
        )
        return StageResult(
            output=output,
            metrics=StageMetrics(
                items_in=chunk_count + fields,
                items_out=block_count + chunk_count + fields,
                detail={"review_items": reviews, "extraction_status": status, "current": current},
            ),
        )

    @staticmethod
    async def _becomes_current(session: AsyncSession, doc: DocumentRef) -> bool:
        document = await session.get(Document, doc.document_id, with_for_update=True)
        version = await session.get(DocumentVersion, doc.version_id)
        if document is None or version is None:
            raise PermanentError(f"{doc.uri} was deleted while it was being processed")
        if document.current_version_id is None or document.current_version_id == version.id:
            return True
        current_no = await session.scalar(
            select(DocumentVersion.version_no).where(DocumentVersion.id == document.current_version_id)
        )
        return current_no is None or version.version_no > current_no
