"""The evidence envelope: how a schema is presented to an LLM and how its answer is read back.

Each top-level field of a registered model is wrapped as ``{value, evidence, source_block,
confidence}``. The wrapped JSON schema is made strict (closed objects, every property required,
unsupported keywords removed) so structured outputs can enforce the shape, while the business
rules (arithmetic, date ordering) stay in Pydantic and drive the repair loop.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError, field_validator

_DROPPED_KEYWORDS = frozenset(
    {
        "default",
        "title",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "examples",
    }
)
_KEPT_FORMATS = frozenset({"date", "date-time"})


class FieldEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: JsonValue = None
    evidence: str | None = None
    source_block: str | None = None
    confidence: float = 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp(cls, raw: Any) -> float:
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, max(0.0, number))


class FieldError(BaseModel):
    path: str
    field: str
    message: str
    received: JsonValue = None

    def render(self) -> str:
        return f"{self.path}: {self.message} (received {self.received!r})"


def _decimal_union(node: dict[str, Any]) -> bool | None:
    """Pydantic renders Decimal as number-or-pattern-string. Returns whether it is nullable, or None."""
    options = node.get("anyOf")
    if not isinstance(options, list):
        return None
    types = {str(option.get("type")) for option in options if isinstance(option, dict)}
    if len(types) != len(options) or not {"number", "string"} <= types <= {"number", "string", "null"}:
        return None
    return "null" in types


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node
    nullable_decimal = _decimal_union(node)
    if nullable_decimal is not None:
        description = f"{node.get('description', 'Decimal number')}. Digits and an optional dot only."
        if nullable_decimal:
            return {"anyOf": [{"type": "string"}, {"type": "null"}], "description": description}
        return {"type": "string", "description": description}

    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED_KEYWORDS:
            continue
        if key == "format" and value not in _KEPT_FORMATS:
            continue
        result[key] = _strictify(value)

    if result.get("type") == "object" and "properties" in result:
        result["additionalProperties"] = False
        result["required"] = list(result["properties"])
    return result


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    options = schema.get("anyOf")
    if isinstance(options, list) and any(option == {"type": "null"} for option in options):
        return schema
    description = schema.pop("description", None)
    wrapped: dict[str, Any] = {"anyOf": [schema, {"type": "null"}]}
    if description:
        wrapped["description"] = description
    return wrapped


def build_envelope_schema(model: type[BaseModel]) -> dict[str, Any]:
    source = copy.deepcopy(model.model_json_schema())
    defs = {name: _strictify(schema) for name, schema in source.get("$defs", {}).items()}
    properties: dict[str, Any] = {}
    for name, field_schema in source.get("properties", {}).items():
        properties[name] = {
            "type": "object",
            "properties": {
                "value": _nullable(_strictify(field_schema)),
                "evidence": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Shortest verbatim quote from the document that supports the value",
                },
                "source_block": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Id of the block the evidence was copied from, e.g. p1-b3",
                },
                "confidence": {
                    "type": "number",
                    "description": "Probability from 0 to 1 that value is correct",
                },
            },
            "required": ["value", "evidence", "source_block", "confidence"],
            "additionalProperties": False,
        }
    envelope: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if defs:
        envelope["$defs"] = defs
    return envelope


def parse_envelope(model: type[BaseModel], output: dict[str, Any]) -> dict[str, FieldEnvelope]:
    """Reads a provider answer leniently; missing or malformed fields become empty envelopes."""
    envelopes: dict[str, FieldEnvelope] = {}
    for name in model.model_fields:
        raw = output.get(name)
        if isinstance(raw, dict):
            try:
                envelopes[name] = FieldEnvelope.model_validate(raw)
                continue
            except ValidationError:
                pass
        envelopes[name] = FieldEnvelope()
    return envelopes


def validation_errors(exc: ValidationError) -> list[FieldError]:
    errors: list[FieldError] = []
    for error in exc.errors(include_url=False):
        location = [str(part) for part in error["loc"]]
        message = str(error["msg"]).removeprefix("Value error, ")
        received = error.get("input")
        errors.append(
            FieldError(
                path=".".join(location) or "(root)",
                field=location[0] if location else "",
                message=message,
                received=received
                if isinstance(received, str | int | float | bool) or received is None
                else None,
            )
        )
    return errors
