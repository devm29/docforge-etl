from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse

from docforge.api.auth import WriterDep
from docforge.api.deps import ServicesDep
from docforge.services.dto import CreateRunIn, Page, RunDetailOut, RunOut, TimelineOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_run(body: CreateRunIn, services: ServicesDep, _: WriterDep) -> RunOut:
    return await services.runs.start(body)


@router.get("")
async def list_runs(
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RunOut]:
    return await services.runs.page(limit, offset)


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, services: ServicesDep) -> RunDetailOut:
    return await services.runs.detail(run_id)


@router.get("/{run_id}/timeline")
async def get_timeline(
    run_id: uuid.UUID,
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TimelineOut:
    return await services.runs.timeline(run_id, limit=limit, offset=offset)


@router.get("/{run_id}/export/{table}.parquet", response_class=FileResponse)
async def download_export(
    run_id: uuid.UUID, table: Literal["chunks", "fields", "stages"], services: ServicesDep
) -> FileResponse:
    path = await services.runs.export_file(run_id, table)
    return FileResponse(
        path, media_type="application/vnd.apache.parquet", filename=f"docforge-{run_id}-{table}.parquet"
    )
