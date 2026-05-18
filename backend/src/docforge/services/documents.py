from __future__ import annotations

import uuid
from dataclasses import dataclass

from docforge.db.models import Document, DocumentVersion
from docforge.db.repositories import DocumentRepository
from docforge.db.session import SessionFactory
from docforge.domain.records import ExtractionStatus
from docforge.errors import ConflictError, NotFoundError
from docforge.services.dto import (
    AttemptOut,
    BBoxOut,
    BlockOut,
    ChunkOut,
    DocumentDetailOut,
    DocumentOut,
    ExtractionOut,
    Page,
    PageSizeOut,
    WordOut,
)
from docforge.services.mappers import chunk_out, field_out, version_out
from docforge.sources.blobs import BlobStore

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}


@dataclass(frozen=True)
class DocumentFile:
    data: bytes
    media_type: str
    filename: str


class DocumentService:
    def __init__(self, sessions: SessionFactory, blobs: BlobStore) -> None:
        self._sessions = sessions
        self._blobs = blobs

    async def page(
        self, *, limit: int, offset: int, kind: str | None, status: str | None, query: str | None
    ) -> Page[DocumentOut]:
        async with self._sessions() as session:
            rows, total = await DocumentRepository(session).page(
                limit=limit, offset=offset, kind=kind, status=status, query=query
            )
            items = [
                self._summary(document, version_no, page_count, extraction_status, avg, pending)
                for document, version_no, page_count, extraction_status, avg, pending in rows
            ]
            return Page[DocumentOut](items=items, total=total, limit=limit, offset=offset)

    @staticmethod
    def _summary(
        document: Document,
        version_no: int | None,
        page_count: int | None,
        extraction_status: str | None,
        average: float | None,
        pending: int,
    ) -> DocumentOut:
        return DocumentOut(
            id=document.id,
            source=document.source,
            uri=document.uri,
            filename=document.filename,
            format=document.format,
            kind=document.kind,
            status=document.status,
            version_no=version_no,
            page_count=page_count,
            extraction_status=ExtractionStatus(extraction_status) if extraction_status else None,
            average_confidence=round(float(average), 3) if average is not None else None,
            pending_reviews=int(pending),
            updated_at=document.updated_at,
        )

    async def detail(self, document_id: uuid.UUID) -> DocumentDetailOut:
        async with self._sessions() as session:
            repo = DocumentRepository(session)
            document = await repo.get(document_id)
            if document is None:
                raise NotFoundError(f"document {document_id} not found")
            current = next((v for v in document.versions if v.id == document.current_version_id), None)
            extraction = await repo.extraction(current.id) if current else None
            pending = await repo.review_ids_by_field([f.id for f in extraction.fields]) if extraction else {}
            average = (
                sum(f.confidence for f in extraction.fields) / len(extraction.fields)
                if extraction and extraction.fields
                else None
            )
            summary = self._summary(
                document,
                current.version_no if current else None,
                current.page_count if current else None,
                extraction.status if extraction else None,
                average,
                len(pending),
            )
            return DocumentDetailOut(
                **summary.model_dump(),
                content_hash=document.content_hash,
                current_version=version_out(current) if current else None,
                versions=[version_out(v) for v in sorted(document.versions, key=lambda v: -v.version_no)],
                pages=[PageSizeOut.model_validate(p) for p in (current.page_sizes or [])] if current else [],
            )

    async def _version(self, document_id: uuid.UUID, version_id: uuid.UUID | None) -> DocumentVersion:
        async with self._sessions() as session:
            repo = DocumentRepository(session)
            if version_id is None:
                document = await repo.get(document_id)
                if document is None:
                    raise NotFoundError(f"document {document_id} not found")
                if document.current_version_id is None:
                    raise ConflictError("document has not been processed successfully yet")
                version_id = document.current_version_id
            version = await repo.version(document_id, version_id)
            if version is None:
                raise NotFoundError(f"version {version_id} not found for document {document_id}")
            return version

    async def extraction(self, document_id: uuid.UUID, version_id: uuid.UUID | None) -> ExtractionOut | None:
        version = await self._version(document_id, version_id)
        async with self._sessions() as session:
            repo = DocumentRepository(session)
            extraction = await repo.extraction(version.id)
            if extraction is None:
                return None
            reviews = await repo.review_ids_by_field([f.id for f in extraction.fields])
            return ExtractionOut(
                id=extraction.id,
                version_id=extraction.version_id,
                schema_name=extraction.schema_name,
                schema_version=extraction.schema_version,
                status=ExtractionStatus(extraction.status),
                data=extraction.data,
                attempts=extraction.attempts,
                repaired=extraction.repaired,
                provider=extraction.provider,
                model=extraction.model,
                input_tokens=extraction.input_tokens,
                output_tokens=extraction.output_tokens,
                cost_usd=float(extraction.cost_usd),
                attempt_log=[AttemptOut.model_validate(a) for a in extraction.attempt_log],
                created_at=extraction.created_at,
                fields=[field_out(f, reviews.get(f.id)) for f in extraction.fields],
            )

    async def blocks(self, document_id: uuid.UUID, version_id: uuid.UUID | None) -> list[BlockOut]:
        version = await self._version(document_id, version_id)
        async with self._sessions() as session:
            return [
                BlockOut(
                    id=b.block_key,
                    page=b.page,
                    kind=b.kind,
                    geometry=b.geometry,
                    text=b.text,
                    bbox=BBoxOut(x0=b.x0, top=b.top, x1=b.x1, bottom=b.bottom),
                    heading_level=b.heading_level,
                    rows=b.rows,
                    cell_range=b.cell_range,
                    words=[
                        WordOut(text=str(w[0]), bbox=BBoxOut(x0=w[1], top=w[2], x1=w[3], bottom=w[4]))
                        for w in b.words
                    ],
                )
                for b in await DocumentRepository(session).blocks(version.id)
            ]

    async def chunks(self, document_id: uuid.UUID, version_id: uuid.UUID | None) -> list[ChunkOut]:
        version = await self._version(document_id, version_id)
        async with self._sessions() as session:
            return [chunk_out(c) for c in await DocumentRepository(session).chunks(version.id)]

    async def file(self, document_id: uuid.UUID, version_id: uuid.UUID | None) -> DocumentFile:
        version = await self._version(document_id, version_id)
        if version.blob_key is None:
            raise ConflictError("this version has no stored content")
        async with self._sessions() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            filename = document.filename
        data = await self._blobs.get(version.blob_key)
        return DocumentFile(
            data=data,
            media_type=MEDIA_TYPES.get(version.format or "", "application/octet-stream"),
            filename=filename,
        )
