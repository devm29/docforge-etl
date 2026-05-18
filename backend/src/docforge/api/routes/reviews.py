from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from docforge.api.auth import WriterDep
from docforge.api.deps import ServicesDep
from docforge.services.dto import ApproveReviewIn, EditReviewIn, Page, ReviewItemOut, ReviewResultOut

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("")
async def list_reviews(
    services: ServicesDep,
    status: Annotated[str, Query(max_length=16)] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ReviewItemOut]:
    return await services.reviews.page(status=status, limit=limit, offset=offset)


@router.get("/{review_id}")
async def get_review(review_id: uuid.UUID, services: ServicesDep) -> ReviewItemOut:
    return await services.reviews.get(review_id)


@router.post("/{review_id}/approve")
async def approve_review(
    review_id: uuid.UUID, body: ApproveReviewIn, services: ServicesDep, writer: WriterDep
) -> ReviewResultOut:
    return await services.reviews.approve(review_id, body, reviewer=writer.name)


@router.post("/{review_id}/edit")
async def edit_review(
    review_id: uuid.UUID, body: EditReviewIn, services: ServicesDep, writer: WriterDep
) -> ReviewResultOut:
    return await services.reviews.edit(review_id, body, reviewer=writer.name)
