from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from docforge.api.deps import ServicesDep
from docforge.services.dto import BlockOut, ChunkOut, DocumentDetailOut, DocumentOut, ExtractionOut, Page

router = APIRouter(prefix="/documents", tags=["documents"])

VersionQuery = Annotated[uuid.UUID | None, Query(description="Defaults to the current version")]


@router.get("")
async def list_documents(
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    kind: Annotated[str | None, Query(max_length=32)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[DocumentOut]:
    return await services.documents.page(limit=limit, offset=offset, kind=kind, status=status, query=q)


@router.get("/{document_id}")
async def get_document(document_id: uuid.UUID, services: ServicesDep) -> DocumentDetailOut:
    return await services.documents.detail(document_id)


@router.get("/{document_id}/extraction")
async def get_extraction(
    document_id: uuid.UUID, services: ServicesDep, version_id: VersionQuery = None
) -> ExtractionOut | None:
    return await services.documents.extraction(document_id, version_id)


@router.get("/{document_id}/blocks")
async def get_blocks(
    document_id: uuid.UUID, services: ServicesDep, version_id: VersionQuery = None
) -> list[BlockOut]:
    return await services.documents.blocks(document_id, version_id)


@router.get("/{document_id}/chunks")
async def get_chunks(
    document_id: uuid.UUID, services: ServicesDep, version_id: VersionQuery = None
) -> list[ChunkOut]:
    return await services.documents.chunks(document_id, version_id)


@router.get("/{document_id}/file")
async def get_file(
    document_id: uuid.UUID, services: ServicesDep, version_id: VersionQuery = None
) -> Response:
    file = await services.documents.file(document_id, version_id)
    return Response(
        content=file.data,
        media_type=file.media_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(file.filename, safe='')}",
            "Cache-Control": "private, max-age=3600, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
