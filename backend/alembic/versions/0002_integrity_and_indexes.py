"""status checks, foreign-key indexes, partial HNSW index, generic entity table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from docforge.domain.records import ExtractionStatus, FieldStatus, MatchKind
from docforge.domain.statuses import (
    DeadLetterStatus,
    DocumentStatus,
    ReviewStatus,
    RunStatus,
    RunTrigger,
    VersionStatus,
    check_in,
    values_of,
)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS: list[tuple[str, str, tuple[str, ...]]] = [
    ("runs", "status", values_of(RunStatus)),
    ("runs", "trigger", values_of(RunTrigger)),
    ("documents", "status", values_of(DocumentStatus)),
    ("document_versions", "status", values_of(VersionStatus)),
    ("extractions", "status", tuple(s.value for s in ExtractionStatus)),
    ("extraction_fields", "status", tuple(s.value for s in FieldStatus)),
    ("extraction_fields", "match", values_of(MatchKind)),
    ("review_items", "status", values_of(ReviewStatus)),
    ("dead_letters", "status", values_of(DeadLetterStatus)),
    ("stage_runs", "status", ("succeeded", "cached", "failed", "skipped")),
]

FK_INDEXES: list[tuple[str, str]] = [
    ("dead_letters", "document_id"),
    ("dead_letters", "version_id"),
    ("stage_runs", "version_id"),
    ("invoices", "extraction_id"),
    ("contracts", "extraction_id"),
]

HNSW = {
    "postgresql_using": "hnsw",
    "postgresql_with": {"m": 16, "ef_construction": 64},
    "postgresql_ops": {"embedding": "vector_cosine_ops"},
}


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for table, column, values in CHECKS:
        op.create_check_constraint(op.f(f"ck_{table}_{column}"), table, check_in(column, values))
    for table, column in FK_INDEXES:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column], unique=False)

    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.create_index(
        "ix_chunks_embedding_hnsw", "chunks", ["embedding"], postgresql_where=sa.text("is_current"), **HNSW
    )

    op.create_table(
        "entity_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("extraction_id", sa.UUID(), nullable=False),
        sa.Column("schema_name", sa.String(length=64), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_id"], ["extractions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index(op.f("ix_entity_records_extraction_id"), "entity_records", ["extraction_id"])
    op.create_index(op.f("ix_entity_records_schema_name"), "entity_records", ["schema_name"])


def downgrade() -> None:
    op.drop_index(op.f("ix_entity_records_schema_name"), table_name="entity_records")
    op.drop_index(op.f("ix_entity_records_extraction_id"), table_name="entity_records")
    op.drop_table("entity_records")
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.create_index("ix_chunks_embedding_hnsw", "chunks", ["embedding"], **HNSW)
    for table, column in reversed(FK_INDEXES):
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
    for table, column, _ in reversed(CHECKS):
        op.drop_constraint(op.f(f"ck_{table}_{column}"), table, type_="check")
    op.drop_column("document_versions", "updated_at")
