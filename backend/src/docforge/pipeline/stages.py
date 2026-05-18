from __future__ import annotations

import asyncio
from typing import Protocol

from pydantic import BaseModel, Field

from docforge.chunking.chunker import StructureAwareChunker
from docforge.domain.documents import DocumentFormat, DocumentModel
from docforge.domain.records import ChunkRecord, ExtractionResult
from docforge.embedding.base import Embedder
from docforge.errors import ParseError, PipelineError
from docforge.extraction.extractor import SchemaExtractor
from docforge.extraction.registry import SchemaRegistry
from docforge.parsing.base import ParserRegistry, detect_format
from docforge.pipeline.core import DocumentRef, PipelineHalt, StageInputs, StageMetrics, StageResult
from docforge.sources.base import SourceRegistry
from docforge.sources.blobs import BlobStore
from docforge.sources.hashing import sha256_bytes


class DetectOutput(BaseModel):
    content_hash: str
    format: DocumentFormat
    size_bytes: int
    blob_key: str


class ChunkSet(BaseModel):
    chunks: list[ChunkRecord]


class EmbeddingSet(BaseModel):
    model: str
    vectors: list[list[float]]


class ExtractOutput(BaseModel):
    schema_name: str | None = None
    classification_score: float = 0.0
    result: ExtractionResult | None = None


class LoadOutput(BaseModel):
    blocks: int = 0
    chunks: int = 0
    fields: int = 0
    review_items: int = 0
    entity: str | None = None
    extraction_status: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class EmbeddingCache(Protocol):
    async def get_many(self, model: str, text_hashes: list[str]) -> dict[str, list[float]]: ...

    async def put_many(self, model: str, vectors: dict[str, list[float]]) -> None: ...


class _KeyedByOwnKey:
    def identity(self, output: BaseModel, key: str) -> str:
        return key


class DetectStage:
    """Fetches the bytes, archives them by content hash and sniffs the real format.

    If the bytes match the document's current version (an S3 re-upload with a new ETag, a touched
    file) the pipeline halts here and nothing downstream runs or gets billed.
    """

    name = "detect"
    depends_on: tuple[str, ...] = ()
    output_type = DetectOutput
    cacheable = False

    def __init__(self, sources: SourceRegistry, blobs: BlobStore) -> None:
        self._sources = sources
        self._blobs = blobs

    def config_version(self) -> str:
        return "detect-1"

    def identity(self, output: BaseModel, key: str) -> str:
        assert isinstance(output, DetectOutput)
        return output.content_hash

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[DetectOutput]:
        data = await self._sources.get(doc.source).read(doc.uri)
        content_hash = sha256_bytes(data)
        if doc.previous_content_hash == content_hash and not doc.force:
            raise PipelineHalt("content identical to the current version")
        fmt = detect_format(doc.filename, data)
        blob_key = await self._blobs.put(data)
        return StageResult(
            output=DetectOutput(
                content_hash=content_hash, format=fmt, size_bytes=len(data), blob_key=blob_key
            ),
            metrics=StageMetrics(items_in=1, items_out=1, detail={"format": fmt.value, "bytes": len(data)}),
        )


class ParseStage(_KeyedByOwnKey):
    name = "parse"
    depends_on = ("detect",)
    output_type = DocumentModel
    cacheable = True

    def __init__(self, parsers: ParserRegistry, blobs: BlobStore) -> None:
        self._parsers = parsers
        self._blobs = blobs

    def config_version(self) -> str:
        return self._parsers.version()

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[DocumentModel]:
        detected = inputs.get("detect", DetectOutput)
        data = await self._blobs.get(detected.blob_key)
        parser = self._parsers.for_format(detected.format)
        try:
            model = await asyncio.to_thread(parser.parse, data)
        except PipelineError:
            raise
        except Exception as exc:
            # Parsing is a pure function of the bytes: whatever it raised, a retry raises it again.
            raise ParseError(f"{parser.version} could not parse {doc.filename}: {exc!r}") from exc
        tables = sum(1 for block in model.iter_blocks() if block.kind == "table")
        return StageResult(
            output=model,
            metrics=StageMetrics(
                items_in=1,
                items_out=model.block_count(),
                detail={"pages": model.page_count, "tables": tables, "parser": parser.version},
            ),
        )


class ChunkStage(_KeyedByOwnKey):
    name = "chunk"
    depends_on = ("parse",)
    output_type = ChunkSet
    cacheable = True

    def __init__(self, chunker: StructureAwareChunker) -> None:
        self._chunker = chunker

    def config_version(self) -> str:
        return self._chunker.version

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[ChunkSet]:
        model = inputs.get("parse", DocumentModel)
        chunks = self._chunker.chunk(model)
        return StageResult(
            output=ChunkSet(chunks=chunks),
            metrics=StageMetrics(
                items_in=model.block_count(),
                items_out=len(chunks),
                detail={"tokens": sum(c.token_count for c in chunks)},
            ),
        )


class EmbedStage(_KeyedByOwnKey):
    """Embeds chunks, reusing vectors for any chunk text that was embedded before by the same model.

    A re-issued invoice with one new line item re-embeds one chunk, not the whole document.
    """

    name = "embed"
    depends_on = ("chunk",)
    output_type = EmbeddingSet
    cacheable = True

    def __init__(self, embedder: Embedder, cache: EmbeddingCache) -> None:
        self._embedder = embedder
        self._cache = cache

    def config_version(self) -> str:
        return self._embedder.name

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[EmbeddingSet]:
        chunks = inputs.get("chunk", ChunkSet).chunks
        hashes = [chunk.content_hash for chunk in chunks]
        known = await self._cache.get_many(self._embedder.name, hashes)
        missing = [chunk for chunk in chunks if chunk.content_hash not in known]
        if missing:
            fresh = await self._embedder.embed([chunk.embed_text for chunk in missing])
            new_vectors = {chunk.content_hash: vector for chunk, vector in zip(missing, fresh, strict=True)}
            await self._cache.put_many(self._embedder.name, new_vectors)
            known.update(new_vectors)
        return StageResult(
            output=EmbeddingSet(model=self._embedder.name, vectors=[known[h] for h in hashes]),
            metrics=StageMetrics(
                items_in=len(chunks),
                items_out=len(missing),
                detail={"reused": len(chunks) - len(missing), "model": self._embedder.name},
            ),
        )


class ExtractStage(_KeyedByOwnKey):
    name = "extract"
    depends_on = ("parse",)
    output_type = ExtractOutput
    cacheable = True

    def __init__(self, schemas: SchemaRegistry, extractor: SchemaExtractor) -> None:
        self._schemas = schemas
        self._extractor = extractor

    def config_version(self) -> str:
        return f"{self._schemas.version}:{self._extractor.version}"

    async def run(self, doc: DocumentRef, inputs: StageInputs) -> StageResult[ExtractOutput]:
        model = inputs.get("parse", DocumentModel)
        spec = self._schemas.classify(model)
        if spec is None:
            return StageResult(
                output=ExtractOutput(),
                metrics=StageMetrics(items_in=1, items_out=0, detail={"schema": None}),
            )
        score = spec.score(model.text())
        result = await self._extractor.extract(model, spec)
        return StageResult(
            output=ExtractOutput(schema_name=spec.name, classification_score=score, result=result),
            metrics=StageMetrics(
                items_in=1,
                items_out=len(result.fields),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost_usd,
                cost_estimated=result.usage.estimated,
                detail={
                    "schema": spec.name,
                    "status": result.status.value,
                    "attempts": result.attempts,
                    "repaired": result.repaired,
                    "model": result.model,
                },
            ),
        )
