from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from docforge.domain.documents import DocumentModel
from docforge.domain.records import TokenUsage
from docforge.extraction.envelope import FieldError


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    schema_name: str
    schema_description: str
    instructions: str
    json_schema: dict[str, Any]
    document: DocumentModel = Field(exclude=True)
    document_text: str
    attempt: int = 1
    previous_output: dict[str, Any] | None = None
    errors: list[FieldError] = Field(default_factory=list)


class ProviderResponse(BaseModel):
    output: dict[str, Any]
    usage: TokenUsage
    model: str


class ExtractionProvider(Protocol):
    """Fills an evidence envelope for one document. Implementations must be stateless per call."""

    name: str
    model: str

    async def extract(self, request: ExtractionRequest) -> ProviderResponse: ...


def render_document(document: DocumentModel, max_chars: int = 120_000) -> str:
    """Block-addressed plain text: every block is prefixed with its id so answers can cite it."""
    parts: list[str] = []
    size = 0
    for page in document.pages:
        header = f"=== page {page.number}{f' ({page.label})' if page.label else ''} ==="
        parts.append(header)
        for block in page.blocks:
            line = f"[{block.id}] {block.text}"
            size += len(line)
            if size > max_chars:
                parts.append("[truncated]")
                return "\n".join(parts)
            parts.append(line)
    return "\n".join(parts)
