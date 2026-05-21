"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('uri', sa.String(length=1024), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('format', sa.String(length=8), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=True),
    sa.Column('fingerprint', sa.String(length=128), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'uri', name='uq_documents_source_uri')
    )
    op.create_index(op.f('ix_documents_kind'), 'documents', ['kind'], unique=False)
    op.create_table('embedding_cache',
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('text_hash', sa.String(length=64), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('model', 'text_hash')
    )
    op.create_table('runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('prefix', sa.String(length=512), nullable=False),
    sa.Column('force', sa.Boolean(), nullable=False),
    sa.Column('bypass_cache', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('pipeline_version', sa.String(length=64), nullable=False),
    sa.Column('docs_seen', sa.Integer(), nullable=False),
    sa.Column('docs_changed', sa.Integer(), nullable=False),
    sa.Column('docs_unchanged', sa.Integer(), nullable=False),
    sa.Column('docs_removed', sa.Integer(), nullable=False),
    sa.Column('docs_succeeded', sa.Integer(), nullable=False),
    sa.Column('docs_failed', sa.Integer(), nullable=False),
    sa.Column('docs_deduplicated', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.BigInteger(), nullable=False),
    sa.Column('output_tokens', sa.BigInteger(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=14, scale=8), nullable=False),
    sa.Column('cost_saved_usd', sa.Numeric(precision=14, scale=8), nullable=False),
    sa.Column('cost_estimated', sa.Boolean(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('export_path', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_runs_status'), 'runs', ['status'], unique=False)
    op.create_table('stage_cache',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('hits', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_hit_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_stage_cache_stage'), 'stage_cache', ['stage'], unique=False)
    op.create_table('document_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('fingerprint', sa.String(length=128), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('blob_key', sa.String(length=64), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('format', sa.String(length=8), nullable=True),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('page_sizes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'version_no', name='uq_versions_doc_no')
    )
    op.create_foreign_key(
        'fk_documents_current_version', 'documents', 'document_versions',
        ['current_version_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(op.f('ix_document_versions_document_id'), 'document_versions', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_versions_run_id'), 'document_versions', ['run_id'], unique=False)
    op.create_table('blocks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('block_key', sa.String(length=32), nullable=False),
    sa.Column('page', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('geometry', sa.String(length=8), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('x0', sa.Float(), nullable=False),
    sa.Column('top', sa.Float(), nullable=False),
    sa.Column('x1', sa.Float(), nullable=False),
    sa.Column('bottom', sa.Float(), nullable=False),
    sa.Column('heading_level', sa.Integer(), nullable=True),
    sa.Column('rows', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('words', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('cell_range', sa.String(length=32), nullable=True),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id', 'block_key', name='uq_blocks_version_key')
    )
    op.create_index(op.f('ix_blocks_version_id'), 'blocks', ['version_id'], unique=False)
    op.create_table('chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('heading_path', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('page_start', sa.Integer(), nullable=False),
    sa.Column('page_end', sa.Integer(), nullable=False),
    sa.Column('spans', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('is_table', sa.Boolean(), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
    sa.Column('embedding_model', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id', 'ordinal', name='uq_chunks_version_ordinal')
    )
    op.create_index('ix_chunks_current', 'chunks', ['document_id'], unique=False, postgresql_where=sa.text('is_current'))
    op.create_index(op.f('ix_chunks_document_id'), 'chunks', ['document_id'], unique=False)
    op.create_index('ix_chunks_embedding_hnsw', 'chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index(op.f('ix_chunks_version_id'), 'chunks', ['version_id'], unique=False)
    op.create_table('dead_letters',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('error_type', sa.String(length=64), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('retryable', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('replayed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replay_run_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dead_letters_run_id'), 'dead_letters', ['run_id'], unique=False)
    op.create_table('extractions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('schema_name', sa.String(length=64), nullable=False),
    sa.Column('schema_version', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('repaired', sa.Boolean(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('attempt_log', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=14, scale=8), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id', 'schema_name', name='uq_extractions_version_schema')
    )
    op.create_index(op.f('ix_extractions_document_id'), 'extractions', ['document_id'], unique=False)
    op.create_index(op.f('ix_extractions_status'), 'extractions', ['status'], unique=False)
    op.create_table('stage_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('items_in', sa.Integer(), nullable=False),
    sa.Column('items_out', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=14, scale=8), nullable=False),
    sa.Column('cost_saved_usd', sa.Numeric(precision=14, scale=8), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_stage_runs_run_version', 'stage_runs', ['run_id', 'version_id'], unique=False)
    op.create_table('contracts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('extraction_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('party_a', sa.String(length=256), nullable=False),
    sa.Column('party_b', sa.String(length=256), nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('term_months', sa.Integer(), nullable=True),
    sa.Column('governing_law', sa.String(length=128), nullable=True),
    sa.Column('contract_value', sa.Numeric(precision=16, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('auto_renews', sa.Boolean(), nullable=True),
    sa.Column('notice_period_days', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['extraction_id'], ['extractions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id')
    )
    op.create_table('extraction_fields',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('extraction_id', sa.UUID(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(length=128), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('model_confidence', sa.Float(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('repaired', sa.Boolean(), nullable=False),
    sa.Column('issues', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('match', sa.String(length=8), nullable=False),
    sa.Column('block_key', sa.String(length=32), nullable=True),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('x0', sa.Float(), nullable=True),
    sa.Column('top', sa.Float(), nullable=True),
    sa.Column('x1', sa.Float(), nullable=True),
    sa.Column('bottom', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['extraction_id'], ['extractions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('extraction_id', 'path', name='uq_fields_extraction_path')
    )
    op.create_table('invoices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('extraction_id', sa.UUID(), nullable=False),
    sa.Column('invoice_number', sa.String(length=128), nullable=False),
    sa.Column('vendor_name', sa.String(length=256), nullable=False),
    sa.Column('customer_name', sa.String(length=256), nullable=True),
    sa.Column('issue_date', sa.Date(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('purchase_order', sa.String(length=128), nullable=True),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['extraction_id'], ['extractions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id')
    )
    op.create_index(op.f('ix_invoices_invoice_number'), 'invoices', ['invoice_number'], unique=False)
    op.create_index(op.f('ix_invoices_vendor_name'), 'invoices', ['vendor_name'], unique=False)
    op.create_table('invoice_line_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invoice_line_items_invoice_id'), 'invoice_line_items', ['invoice_id'], unique=False)
    op.create_table('review_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('extraction_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('original_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('resolved_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reviewer', sa.String(length=128), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['extraction_id'], ['extractions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['field_id'], ['extraction_fields.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('field_id')
    )
    op.create_index(op.f('ix_review_items_document_id'), 'review_items', ['document_id'], unique=False)
    op.create_index(op.f('ix_review_items_extraction_id'), 'review_items', ['extraction_id'], unique=False)
    op.create_index('ix_review_items_pending', 'review_items', ['created_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_constraint('fk_documents_current_version', 'documents', type_='foreignkey')
    op.drop_index('ix_review_items_pending', table_name='review_items', postgresql_where=sa.text("status = 'pending'"))
    op.drop_index(op.f('ix_review_items_extraction_id'), table_name='review_items')
    op.drop_index(op.f('ix_review_items_document_id'), table_name='review_items')
    op.drop_table('review_items')
    op.drop_index(op.f('ix_invoice_line_items_invoice_id'), table_name='invoice_line_items')
    op.drop_table('invoice_line_items')
    op.drop_index(op.f('ix_invoices_vendor_name'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_invoice_number'), table_name='invoices')
    op.drop_table('invoices')
    op.drop_table('extraction_fields')
    op.drop_table('contracts')
    op.drop_index('ix_stage_runs_run_version', table_name='stage_runs')
    op.drop_table('stage_runs')
    op.drop_index(op.f('ix_extractions_status'), table_name='extractions')
    op.drop_index(op.f('ix_extractions_document_id'), table_name='extractions')
    op.drop_table('extractions')
    op.drop_index(op.f('ix_dead_letters_run_id'), table_name='dead_letters')
    op.drop_table('dead_letters')
    op.drop_index(op.f('ix_chunks_version_id'), table_name='chunks')
    op.drop_index('ix_chunks_embedding_hnsw', table_name='chunks', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_chunks_document_id'), table_name='chunks')
    op.drop_index('ix_chunks_current', table_name='chunks', postgresql_where=sa.text('is_current'))
    op.drop_table('chunks')
    op.drop_index(op.f('ix_blocks_version_id'), table_name='blocks')
    op.drop_table('blocks')
    op.drop_index(op.f('ix_document_versions_run_id'), table_name='document_versions')
    op.drop_index(op.f('ix_document_versions_document_id'), table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_index(op.f('ix_stage_cache_stage'), table_name='stage_cache')
    op.drop_table('stage_cache')
    op.drop_index(op.f('ix_runs_status'), table_name='runs')
    op.drop_table('runs')
    op.drop_table('embedding_cache')
    op.drop_index(op.f('ix_documents_kind'), table_name='documents')
    op.drop_table('documents')
