from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import JsonValue, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from docforge.db.models import Extraction, ExtractionField, ReviewItem
from docforge.db.repositories import ReviewRepository
from docforge.db.session import SessionFactory, transaction
from docforge.domain.records import ExtractionStatus, FieldStatus
from docforge.domain.statuses import ReviewStatus, values_of
from docforge.errors import ConflictError, InvalidRequestError, NotFoundError
from docforge.extraction.registry import SchemaRegistry
from docforge.services.dto import ApproveReviewIn, EditReviewIn, Page, ReviewItemOut, ReviewResultOut
from docforge.services.mappers import review_out
from docforge.sinks.entities import EntitySink

REVIEW_STATUSES = values_of(ReviewStatus)


class ReviewService:
    """Human-in-the-loop resolution of low-confidence or invalid fields.

    An edit is type-checked against the field's annotation before it is accepted. Resolving the last
    pending item re-validates the whole record against its schema: if it passes, the record is
    approved and written to the typed entity table; if not, the decision is rejected with the rule
    that still fails, so a value that breaks the schema can never be approved into the warehouse.
    """

    def __init__(self, sessions: SessionFactory, schemas: SchemaRegistry, entities: EntitySink) -> None:
        self._sessions = sessions
        self._schemas = schemas
        self._entities = entities

    async def page(self, *, status: str, limit: int, offset: int) -> Page[ReviewItemOut]:
        if status not in REVIEW_STATUSES:
            raise InvalidRequestError(f"status must be one of {', '.join(REVIEW_STATUSES)}")
        async with self._sessions() as session:
            rows, total = await ReviewRepository(session).page(status=status, limit=limit, offset=offset)
            return Page[ReviewItemOut](
                items=[review_out(*row) for row in rows], total=total, limit=limit, offset=offset
            )

    async def get(self, review_id: uuid.UUID) -> ReviewItemOut:
        async with self._sessions() as session:
            row = await ReviewRepository(session).get(review_id)
            if row is None:
                raise NotFoundError(f"review item {review_id} not found")
            return review_out(*row)

    async def approve(
        self, review_id: uuid.UUID, decision: ApproveReviewIn, *, reviewer: str
    ) -> ReviewResultOut:
        return await self._resolve(review_id, decision, reviewer, new_value=None, edited=False)

    async def edit(self, review_id: uuid.UUID, decision: EditReviewIn, *, reviewer: str) -> ReviewResultOut:
        return await self._resolve(review_id, decision, reviewer, new_value=decision.value, edited=True)

    async def _resolve(
        self,
        review_id: uuid.UUID,
        decision: ApproveReviewIn,
        reviewer: str,
        *,
        new_value: JsonValue,
        edited: bool,
    ) -> ReviewResultOut:
        async with transaction(self._sessions) as session:
            row = await ReviewRepository(session).get(review_id, for_update=True)
            if row is None:
                raise NotFoundError(f"review item {review_id} not found")
            item, field, extraction, _ = row
            if item.status != "pending":
                raise ConflictError(f"review item is already {item.status}")

            spec = self._schemas.get(extraction.schema_name)
            value: Any = field.value
            if edited:
                value = self._coerce(spec.model.model_fields[field.path], field.path, new_value)
                field.value = value
                data = dict(extraction.data)
                data[field.path] = value
                extraction.data = data

            now = datetime.now(UTC)
            item.status = "edited" if edited else "approved"
            item.resolved_value = value
            item.reviewer = reviewer
            item.note = decision.note
            item.resolved_at = now
            field.status = (FieldStatus.EDITED if edited else FieldStatus.APPROVED).value
            field.confidence = 1.0
            await session.flush()

            remaining = await session.scalar(
                select(func.count())
                .select_from(ReviewItem)
                .where(ReviewItem.extraction_id == extraction.id, ReviewItem.status == "pending")
            )
            if not remaining:
                await self._finalize(session, extraction)
            await session.flush()
            refreshed = await ReviewRepository(session).get(review_id)
            assert refreshed is not None
            return ReviewResultOut(
                item=review_out(*refreshed), extraction_status=ExtractionStatus(extraction.status)
            )

    async def _finalize(self, session: AsyncSession, extraction: Extraction) -> None:
        """Last item resolved: the record must now satisfy its schema, or the decision is rejected."""
        spec = self._schemas.get(extraction.schema_name)
        try:
            validated = spec.model.model_validate(extraction.data).model_dump(mode="json")
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {str(e['msg']).removeprefix('Value error, ')}"
                for e in exc.errors(include_url=False)
            )
            raise InvalidRequestError(
                f"the record would still fail validation ({problems}). "
                "Edit the value so it satisfies the rule."
            ) from exc
        extraction.data = validated
        extraction.status = ExtractionStatus.APPROVED.value
        fields = await session.scalars(
            select(ExtractionField).where(ExtractionField.extraction_id == extraction.id)
        )
        for field in fields:
            if field.path in validated:
                field.value = validated[field.path]
        await session.flush()
        await self._entities.sync_entity(session, extraction)

    @staticmethod
    def _coerce(info: FieldInfo, path: str, value: JsonValue) -> JsonValue:
        # rebuild_annotation keeps the Field constraints (pattern, ge/le, min_length) that a bare
        # annotation would drop.
        adapter: TypeAdapter[Any] = TypeAdapter(info.rebuild_annotation())
        try:
            parsed = adapter.validate_python(value)
        except ValidationError as exc:
            message = exc.errors(include_url=False)[0]["msg"]
            raise InvalidRequestError(f"{path}: {message}") from exc
        dumped: JsonValue = adapter.dump_python(parsed, mode="json")
        return dumped
