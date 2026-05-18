from __future__ import annotations

from typing import Any

from pydantic import JsonValue, ValidationError

from docforge.domain.documents import DocumentModel
from docforge.domain.records import (
    AttemptLog,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    TokenUsage,
)
from docforge.extraction.confidence import score_field
from docforge.extraction.envelope import (
    FieldEnvelope,
    FieldError,
    build_envelope_schema,
    parse_envelope,
    validation_errors,
)
from docforge.extraction.grounding import locate
from docforge.extraction.providers.base import ExtractionProvider, ExtractionRequest, render_document
from docforge.extraction.registry import SchemaSpec
from docforge.logs import get_logger

log = get_logger(__name__)


class SchemaExtractor:
    """Fills a registered schema from a document and keeps asking until the answer validates.

    Each failed attempt feeds the structured validation errors back to the provider, bounded by
    ``max_repairs``. When the document is internally inconsistent no repair can succeed; the result
    is then returned as ``invalid`` with the offending fields flagged, so a reviewer decides.
    """

    def __init__(self, provider: ExtractionProvider, *, max_repairs: int) -> None:
        self._provider = provider
        self._max_repairs = max_repairs

    @property
    def version(self) -> str:
        return f"{self._provider.name}:{self._provider.model}:repairs={self._max_repairs}"

    async def extract(self, document: DocumentModel, spec: SchemaSpec) -> ExtractionResult:
        request = ExtractionRequest(
            schema_name=spec.name,
            schema_description=spec.description,
            instructions=spec.instructions,
            json_schema=build_envelope_schema(spec.model),
            document=document,
            document_text=render_document(document),
        )
        usage = TokenUsage()
        attempts: list[AttemptLog] = []
        history: list[dict[str, FieldEnvelope]] = []
        errors: list[FieldError] = []
        validated: dict[str, JsonValue] | None = None
        model = self._provider.model

        for attempt in range(1, self._max_repairs + 2):
            response = await self._provider.extract(request)
            usage += response.usage
            model = response.model
            envelopes = parse_envelope(spec.model, response.output)
            history.append(envelopes)
            try:
                instance = spec.model.model_validate({name: env.value for name, env in envelopes.items()})
            except ValidationError as exc:
                errors = validation_errors(exc)
                attempts.append(AttemptLog(attempt=attempt, errors=[e.render() for e in errors]))
                log.info(
                    "extraction.validation_failed", schema=spec.name, attempt=attempt, errors=len(errors)
                )
                request = request.model_copy(
                    update={
                        "attempt": attempt + 1,
                        "previous_output": {name: env.model_dump() for name, env in envelopes.items()},
                        "errors": errors,
                    }
                )
                continue
            validated = instance.model_dump(mode="json")
            errors = []
            attempts.append(AttemptLog(attempt=attempt, errors=[]))
            break

        final = history[-1]
        data: dict[str, JsonValue] = (
            validated if validated is not None else {n: e.value for n, e in final.items()}
        )
        open_issues: dict[str, list[str]] = {}
        for error in errors:
            open_issues.setdefault(error.field, []).append(error.render())

        fields = [
            self._field(document, name, data.get(name), envelope, history, open_issues.get(name, []))
            for name, envelope in final.items()
        ]
        return ExtractionResult(
            schema_name=spec.name,
            schema_version=spec.version,
            status=ExtractionStatus.INVALID if validated is None else ExtractionStatus.VALID,
            data=data,
            fields=fields,
            attempts=len(attempts),
            repaired=validated is not None and len(attempts) > 1,
            model=model,
            provider=self._provider.name,
            usage=usage,
            attempt_log=attempts,
        )

    @staticmethod
    def _field(
        document: DocumentModel,
        name: str,
        value: JsonValue,
        envelope: FieldEnvelope,
        history: list[dict[str, FieldEnvelope]],
        issues: list[str],
    ) -> ExtractedField:
        first = history[0][name].value
        repaired = len(history) > 1 and _canonical(first) != _canonical(envelope.value)
        provenance = locate(document, envelope.value, envelope.evidence, envelope.source_block)
        confidence = score_field(
            model_confidence=envelope.confidence,
            match=provenance.match,
            is_null=value is None or value == [] or value == "",
            repaired=repaired,
            has_open_issue=bool(issues),
        )
        return ExtractedField(
            path=name,
            value=value,
            confidence=confidence,
            model_confidence=envelope.confidence,
            provenance=provenance,
            repaired=repaired,
            issues=issues,
        )


def _canonical(value: Any) -> str:
    return repr(value)
