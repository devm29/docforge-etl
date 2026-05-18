from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import text

from docforge.api.auth import WriterDep
from docforge.api.deps import ServicesDep
from docforge.services.dto import DeadLetterOut, HealthOut, OverviewOut, Page, RunOut, SchemaOut, SearchOut

router = APIRouter()


@router.get("/health", tags=["system"])
async def health(services: ServicesDep) -> HealthOut:
    container = services.container
    database = True
    try:
        async with container.sessions() as session:
            await session.execute(text("select 1"))
    except Exception:
        database = False
    queue = True
    try:
        await services.queue.ping()
    except Exception:
        queue = False
    return HealthOut(
        status="ok" if database and queue else "degraded",
        database=database,
        queue=queue,
        provider=container.provider.name,
        model=container.provider.model,
        embedder=container.embedder.name,
    )


@router.get("/overview", tags=["system"])
async def overview(services: ServicesDep) -> OverviewOut:
    return await services.overview.overview()


@router.get("/schemas", tags=["system"])
async def schemas(services: ServicesDep) -> list[SchemaOut]:
    return [
        SchemaOut(
            name=spec.name,
            version=spec.version,
            description=spec.description,
            instructions=spec.instructions,
            fields=spec.field_names,
            json_schema=spec.model.model_json_schema(),
        )
        for spec in services.container.schemas.all()
    ]


@router.get("/search", tags=["search"])
async def search(
    services: ServicesDep,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
    kind: Annotated[str | None, Query(max_length=32)] = None,
) -> SearchOut:
    return await services.search.search(q, limit=limit, kind=kind)


@router.get("/dead-letters", tags=["dead letters"])
async def dead_letters(
    services: ServicesDep,
    status_filter: Annotated[str | None, Query(alias="status", max_length=16)] = None,
    run_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DeadLetterOut]:
    return await services.dead_letters.page(status=status_filter, run_id=run_id, limit=limit, offset=offset)


@router.post(
    "/dead-letters/{dead_letter_id}/replay", tags=["dead letters"], status_code=status.HTTP_202_ACCEPTED
)
async def replay_dead_letter(dead_letter_id: uuid.UUID, services: ServicesDep, _: WriterDep) -> RunOut:
    return await services.dead_letters.replay(dead_letter_id)
