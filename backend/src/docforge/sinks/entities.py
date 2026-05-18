from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docforge.db.models import (
    ContractRecord,
    EntityRecord,
    Extraction,
    ExtractionField,
    InvoiceLineItemRecord,
    InvoiceRecord,
    ReviewItem,
)
from docforge.domain.records import ExtractionResult, ExtractionStatus, FieldStatus
from docforge.extraction.registry import SchemaRegistry
from docforge.extraction.schemas.contract import Contract
from docforge.extraction.schemas.invoice import Invoice


class EntityWriter(Protocol):
    schema_name: str

    async def upsert(
        self, session: AsyncSession, document_id: uuid.UUID, extraction_id: uuid.UUID, entity: BaseModel
    ) -> None: ...

    async def remove(self, session: AsyncSession, document_id: uuid.UUID) -> None: ...


class InvoiceWriter:
    schema_name = "invoice"

    async def upsert(
        self, session: AsyncSession, document_id: uuid.UUID, extraction_id: uuid.UUID, entity: BaseModel
    ) -> None:
        if not isinstance(entity, Invoice):
            raise TypeError(f"expected Invoice, got {type(entity).__name__}")
        await self.remove(session, document_id)
        session.add(
            InvoiceRecord(
                document_id=document_id,
                extraction_id=extraction_id,
                invoice_number=entity.invoice_number,
                vendor_name=entity.vendor_name,
                customer_name=entity.customer_name,
                issue_date=entity.issue_date,
                due_date=entity.due_date,
                currency=entity.currency,
                purchase_order=entity.purchase_order,
                subtotal=entity.subtotal,
                tax=entity.tax,
                total=entity.total,
                line_items=[
                    InvoiceLineItemRecord(
                        ordinal=index,
                        description=item.description,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        amount=item.amount,
                    )
                    for index, item in enumerate(entity.line_items)
                ],
            )
        )

    async def remove(self, session: AsyncSession, document_id: uuid.UUID) -> None:
        await session.execute(delete(InvoiceRecord).where(InvoiceRecord.document_id == document_id))


class ContractWriter:
    schema_name = "contract"

    async def upsert(
        self, session: AsyncSession, document_id: uuid.UUID, extraction_id: uuid.UUID, entity: BaseModel
    ) -> None:
        if not isinstance(entity, Contract):
            raise TypeError(f"expected Contract, got {type(entity).__name__}")
        await self.remove(session, document_id)
        session.add(
            ContractRecord(
                document_id=document_id,
                extraction_id=extraction_id,
                title=entity.title,
                party_a=entity.party_a,
                party_b=entity.party_b,
                effective_date=entity.effective_date,
                end_date=entity.end_date,
                term_months=entity.term_months,
                governing_law=entity.governing_law,
                contract_value=entity.contract_value,
                currency=entity.currency,
                auto_renews=entity.auto_renews,
                notice_period_days=entity.notice_period_days,
            )
        )

    async def remove(self, session: AsyncSession, document_id: uuid.UUID) -> None:
        await session.execute(delete(ContractRecord).where(ContractRecord.document_id == document_id))


class GenericEntityWriter:
    """Mirrors any registered schema without a dedicated table into ``entity_records`` as JSONB."""

    def __init__(self, schema_name: str) -> None:
        self.schema_name = schema_name

    async def upsert(
        self, session: AsyncSession, document_id: uuid.UUID, extraction_id: uuid.UUID, entity: BaseModel
    ) -> None:
        await self.remove(session, document_id)
        session.add(
            EntityRecord(
                document_id=document_id,
                extraction_id=extraction_id,
                schema_name=self.schema_name,
                data=entity.model_dump(mode="json"),
            )
        )

    async def remove(self, session: AsyncSession, document_id: uuid.UUID) -> None:
        await session.execute(delete(EntityRecord).where(EntityRecord.document_id == document_id))


class EntitySink:
    """Writes extractions with field-level provenance, opens review items, and maintains typed tables.

    Typed rows only ever hold records that pass the schema; an invalid extraction removes the row
    for that document until a reviewer resolves it. Whether a record needs review is decided here,
    not by the extractor, so tuning the threshold never invalidates (and re-bills) cached extractions.
    """

    def __init__(
        self, registry: SchemaRegistry, writers: list[EntityWriter], review_threshold: float
    ) -> None:
        self._registry = registry
        self._writers = {writer.schema_name: writer for writer in writers}
        self._threshold = review_threshold

    def _writer(self, schema_name: str) -> EntityWriter:
        return self._writers.get(schema_name) or GenericEntityWriter(schema_name)

    async def retire(self, session: AsyncSession, document_id: uuid.UUID) -> None:
        """Takes a document out of every typed table and closes its open reviews.

        Used before a new current version is written (it may have been reclassified) and when the
        document disappears from its source.
        """
        for writer in self._writers.values():
            await writer.remove(session, document_id)
        await session.execute(delete(EntityRecord).where(EntityRecord.document_id == document_id))
        await session.execute(
            update(Extraction)
            .where(Extraction.document_id == document_id, Extraction.is_current)
            .values(is_current=False)
        )
        await session.execute(
            update(ReviewItem)
            .where(ReviewItem.document_id == document_id, ReviewItem.status == "pending")
            .values(status="superseded")
        )

    async def write(
        self,
        session: AsyncSession,
        *,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        result: ExtractionResult,
        current: bool = True,
    ) -> tuple[Extraction, int]:
        """Stores the extraction. A non-current (out-of-order) version is kept for history only:
        it opens no review items and never touches the typed tables."""
        decisions = await self._prior_decisions(session, document_id, result.schema_name)
        if current:
            await self.retire(session, document_id)
        await session.execute(
            delete(Extraction).where(
                Extraction.version_id == version_id, Extraction.schema_name == result.schema_name
            )
        )
        extraction = Extraction(
            document_id=document_id,
            version_id=version_id,
            schema_name=result.schema_name,
            schema_version=result.schema_version,
            status=result.status.value,
            data=result.data,
            attempts=result.attempts,
            repaired=result.repaired,
            provider=result.provider,
            model=result.model,
            attempt_log=[log.model_dump(mode="json") for log in result.attempt_log],
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=Decimal(str(result.usage.cost_usd)),
            is_current=current,
        )
        session.add(extraction)
        await session.flush()

        reviews = carried = open_flags = 0
        data = dict(result.data)
        for ordinal, item in enumerate(result.fields):
            flagged = bool(item.issues) or item.confidence < self._threshold
            value, confidence = item.value, item.confidence
            status = FieldStatus.NEEDS_REVIEW if flagged else FieldStatus.ACCEPTED
            decision = decisions.get(item.path)
            if flagged and decision is not None and decision.original_value == item.value:
                # A reviewer already ruled on this exact value; reprocessing must not undo that.
                value, confidence, flagged = decision.resolved_value, 1.0, False
                status = FieldStatus.EDITED if decision.status == "edited" else FieldStatus.APPROVED
                data[item.path] = value
                carried += 1
            bbox = item.provenance.bbox
            field = ExtractionField(
                extraction_id=extraction.id,
                ordinal=ordinal,
                path=item.path,
                value=value,
                confidence=confidence,
                model_confidence=item.model_confidence,
                status=status.value,
                repaired=item.repaired,
                issues=item.issues,
                evidence=item.provenance.evidence,
                match=item.provenance.match,
                block_key=item.provenance.block_id,
                page=item.provenance.page,
                x0=bbox.x0 if bbox else None,
                top=bbox.top if bbox else None,
                x1=bbox.x1 if bbox else None,
                bottom=bbox.bottom if bbox else None,
            )
            session.add(field)
            open_flags += flagged
            if flagged and current:
                await session.flush()
                session.add(
                    ReviewItem(
                        field_id=field.id,
                        extraction_id=extraction.id,
                        document_id=document_id,
                        reason="validation_failed" if item.issues else "low_confidence",
                        status="pending",
                        original_value=item.value,
                    )
                )
                reviews += 1

        if result.status is ExtractionStatus.VALID and open_flags:
            extraction.status = ExtractionStatus.NEEDS_REVIEW.value
        if carried and not reviews and current:
            spec = self._registry.get(result.schema_name)
            try:
                extraction.data = spec.model.model_validate(data).model_dump(mode="json")
                extraction.status = ExtractionStatus.APPROVED.value
            except ValidationError:
                extraction.data = data
        if current:
            await self.sync_entity(session, extraction)
        return extraction, reviews

    @staticmethod
    async def _prior_decisions(
        session: AsyncSession, document_id: uuid.UUID, schema_name: str
    ) -> dict[str, ReviewItem]:
        rows = await session.execute(
            select(ExtractionField.path, ReviewItem)
            .join(ReviewItem, ReviewItem.field_id == ExtractionField.id)
            .join(Extraction, Extraction.id == ExtractionField.extraction_id)
            .where(
                ReviewItem.document_id == document_id,
                ReviewItem.status.in_(("approved", "edited")),
                Extraction.schema_name == schema_name,
            )
            .order_by(ReviewItem.resolved_at.desc())
        )
        decisions: dict[str, ReviewItem] = {}
        for path, item in rows.all():
            decisions.setdefault(path, item)
        return decisions

    async def sync_entity(self, session: AsyncSession, extraction: Extraction) -> list[str]:
        """Re-validates the extraction's current field values and mirrors them into the typed table.

        Returns the validation errors, empty when the record is valid.
        """
        writer = self._writer(extraction.schema_name)
        spec = self._registry.get(extraction.schema_name)
        if extraction.status == ExtractionStatus.INVALID.value and not await self._all_resolved(
            session, extraction
        ):
            await writer.remove(session, extraction.document_id)
            return []
        try:
            entity = spec.model.model_validate(extraction.data)
        except ValidationError as exc:
            await writer.remove(session, extraction.document_id)
            return [
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors(include_url=False)
            ]
        await writer.upsert(session, extraction.document_id, extraction.id, entity)
        return []

    @staticmethod
    async def _all_resolved(session: AsyncSession, extraction: Extraction) -> bool:
        pending = await session.scalar(
            select(ReviewItem.id)
            .where(ReviewItem.extraction_id == extraction.id, ReviewItem.status == "pending")
            .limit(1)
        )
        return pending is None


def default_writers() -> list[EntityWriter]:
    return [InvoiceWriter(), ContractWriter()]
