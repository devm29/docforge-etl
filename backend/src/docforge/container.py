from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import anthropic
from sqlalchemy.ext.asyncio import AsyncEngine

from docforge.chunking.chunker import StructureAwareChunker
from docforge.config import Settings
from docforge.db.session import SessionFactory, create_engine, create_session_factory
from docforge.embedding.base import Embedder
from docforge.embedding.factory import build_embedder
from docforge.extraction.extractor import SchemaExtractor
from docforge.extraction.providers.anthropic import AnthropicProvider
from docforge.extraction.providers.base import ExtractionProvider
from docforge.extraction.providers.offline import OfflineProvider
from docforge.extraction.registry import SchemaRegistry, load_registry
from docforge.logs import get_logger
from docforge.parsing.base import ParserRegistry
from docforge.parsing.base import default_registry as default_parsers
from docforge.pipeline.core import Stage
from docforge.pipeline.load import LoadStage
from docforge.pipeline.queue import JobQueue
from docforge.pipeline.runner import DagRunner, RetryPolicy
from docforge.pipeline.service import PipelineService
from docforge.pipeline.stages import ChunkStage, DetectStage, EmbedStage, ExtractStage, ParseStage
from docforge.pipeline.stores import DbEmbeddingCache, DbLedger, DbStageCache
from docforge.sinks.documents import BlockSink
from docforge.sinks.entities import EntitySink, default_writers
from docforge.sinks.parquet import ParquetExporter
from docforge.sinks.vectors import PgVectorSink
from docforge.sources.base import SourceConnector, SourceRegistry
from docforge.sources.blobs import BlobStore, LocalBlobStore
from docforge.sources.fs import FsSource
from docforge.sources.s3 import S3Source

log = get_logger(__name__)


def build_provider(settings: Settings) -> ExtractionProvider:
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    use_anthropic = settings.llm_provider == "anthropic" or (settings.llm_provider == "auto" and bool(key))
    if not use_anthropic:
        return OfflineProvider(priced_as=settings.extraction_model)
    return AnthropicProvider(
        anthropic.AsyncAnthropic(api_key=key, max_retries=2, timeout=120.0),
        model=settings.extraction_model,
        effort=settings.extraction_effort,
        refusal_fallback=settings.extraction_refusal_fallback,
    )


def build_sources(settings: Settings) -> SourceRegistry:
    connectors: list[SourceConnector] = [FsSource(settings.fs_source_root)]
    if settings.s3_endpoint_url or settings.s3_access_key_id:
        connectors.append(
            S3Source(
                bucket=settings.s3_bucket,
                prefix=settings.s3_prefix,
                endpoint_url=settings.s3_endpoint_url,
                region=settings.s3_region,
                access_key_id=settings.s3_access_key_id,
                secret_access_key=(
                    settings.s3_secret_access_key.get_secret_value()
                    if settings.s3_secret_access_key
                    else None
                ),
            )
        )
    return SourceRegistry(connectors)


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: SessionFactory
    sources: SourceRegistry
    blobs: BlobStore
    parsers: ParserRegistry
    chunker: StructureAwareChunker
    embedder: Embedder
    schemas: SchemaRegistry
    provider: ExtractionProvider
    extractor: SchemaExtractor
    entities: EntitySink
    vectors: PgVectorSink
    exporter: ParquetExporter

    def runner(self) -> DagRunner:
        stages: list[Stage] = [
            DetectStage(self.sources, self.blobs),
            ParseStage(self.parsers, self.blobs),
            ChunkStage(self.chunker),
            EmbedStage(self.embedder, DbEmbeddingCache(self.sessions)),
            ExtractStage(self.schemas, self.extractor),
            LoadStage(self.sessions, BlockSink(), self.vectors, self.entities),
        ]
        return DagRunner(
            stages,
            cache=DbStageCache(self.sessions),
            ledger=DbLedger(self.sessions),
            retry=RetryPolicy(
                max_attempts=self.settings.stage_max_attempts,
                base_delay=self.settings.stage_backoff_base_seconds,
                max_delay=self.settings.stage_backoff_max_seconds,
            ),
        )

    @property
    def stale_after(self) -> timedelta:
        return timedelta(seconds=self.settings.run_stale_after_seconds)

    def pipeline(self, queue: JobQueue) -> PipelineService:
        return PipelineService(
            sessions=self.sessions,
            sources=self.sources,
            runner=self.runner(),
            queue=queue,
            exporter=self.exporter,
            vectors=self.vectors,
            entities=self.entities,
            stale_after=self.stale_after,
        )

    async def close(self) -> None:
        await self.engine.dispose()


def build_container(settings: Settings, *, embedder: Embedder | None = None) -> Container:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    schemas = load_registry(settings.schema_modules)
    provider = build_provider(settings)
    log.info("container.ready", provider=provider.name, model=provider.model)
    return Container(
        settings=settings,
        engine=engine,
        sessions=create_session_factory(engine),
        sources=build_sources(settings),
        blobs=LocalBlobStore(settings.blob_dir),
        parsers=default_parsers(),
        chunker=StructureAwareChunker(settings.chunk_max_tokens, settings.chunk_overlap_blocks),
        embedder=embedder or build_embedder(settings),
        schemas=schemas,
        provider=provider,
        extractor=SchemaExtractor(provider, max_repairs=settings.extraction_max_repairs),
        entities=EntitySink(schemas, default_writers(), settings.review_confidence_threshold),
        vectors=PgVectorSink(),
        exporter=ParquetExporter(settings.export_dir),
    )
