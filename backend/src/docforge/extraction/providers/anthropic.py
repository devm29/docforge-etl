from __future__ import annotations

import json
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessage

from docforge.config import Effort
from docforge.errors import ExtractionProviderError, ExtractionRefusedError, ProviderUnavailableError
from docforge.extraction.pricing import price_usage
from docforge.extraction.providers.base import ExtractionRequest, ProviderResponse

SYSTEM_PROMPT = """You extract structured data from business documents for a data pipeline.

The document is given as blocks, each prefixed with an id like [p1-b3]. For every field in the
schema return the value, the shortest verbatim quote from the document that supports it, the id of
the block the quote came from, and your confidence from 0 to 1. When the document does not state a
field, return null for value and evidence and a confidence that reflects how sure you are that it is
absent. Never invent values. Downstream code checks your output against validation rules; if a
previous attempt failed them you will be told which rules failed and why."""

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """Claude via the Messages API with JSON-schema structured outputs.

    Repair attempts are sent as a fresh single-turn request that quotes the failed answer and the
    validation errors, rather than replaying a synthesized assistant turn.
    """

    name = "anthropic"

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        model: str,
        effort: Effort,
        refusal_fallback: bool,
        max_tokens: int = 16000,
    ) -> None:
        self._client = client
        self.model = model
        self._effort: Effort = effort
        self._refusal_fallback = refusal_fallback
        self._max_tokens = max_tokens

    def build_prompt(self, request: ExtractionRequest) -> str:
        sections = [
            f"Schema: {request.schema_name} - {request.schema_description}",
            f"Instructions: {request.instructions}",
            "<document>",
            request.document_text,
            "</document>",
        ]
        if request.previous_output is not None and request.errors:
            sections += [
                "A previous extraction of this document failed validation.",
                "<previous_answer>",
                json.dumps(request.previous_output, indent=1, default=str),
                "</previous_answer>",
                "<validation_errors>",
                *(f"- {error.render()}" for error in request.errors),
                "</validation_errors>",
                "Return a corrected answer for every field. Fix the fields named in the errors by "
                "re-reading the document; if the document itself is inconsistent, keep the printed "
                "values and lower the confidence of the fields involved.",
            ]
        return "\n".join(sections)

    async def extract(self, request: ExtractionRequest) -> ProviderResponse:
        kwargs: dict[str, Any] = {}
        betas: list[str] = []
        if self._refusal_fallback:
            betas.append(FALLBACK_BETA)
            kwargs["fallbacks"] = "default"
        try:
            message: BetaMessage = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self.build_prompt(request)}],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": request.json_schema},
                },
                betas=betas,
                **kwargs,
            )
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as exc:
            raise ProviderUnavailableError(f"Claude is unavailable: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code == 529:
                raise ProviderUnavailableError(f"Claude returned {exc.status_code}: {exc.message}") from exc
            raise ExtractionProviderError(
                f"Claude rejected the request ({exc.status_code}): {exc.message}"
            ) from exc

        if message.stop_reason == "refusal":
            raise ExtractionRefusedError("Claude declined to extract this document")
        if message.stop_reason == "max_tokens":
            raise ExtractionProviderError("extraction output was truncated at max_tokens")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise ExtractionProviderError("Claude returned no text block")
        try:
            output = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExtractionProviderError(f"structured output was not valid JSON: {exc}") from exc
        if not isinstance(output, dict):
            raise ExtractionProviderError("structured output was not a JSON object")

        usage = message.usage
        input_tokens = (
            usage.input_tokens
            + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0)
        )
        return ProviderResponse(
            output=output,
            usage=price_usage(message.model, input_tokens, usage.output_tokens),
            model=message.model,
        )
