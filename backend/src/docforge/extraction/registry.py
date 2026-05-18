from __future__ import annotations

import importlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property

from pydantic import BaseModel

from docforge.domain.documents import DocumentModel
from docforge.errors import NotFoundError
from docforge.sources.hashing import stable_hash


@dataclass(frozen=True)
class SchemaSpec:
    """A user-registered extraction target.

    ``version`` is derived from the JSON schema and instructions, so editing either one changes
    the extract stage's idempotency key and re-extracts affected documents on the next run.
    """

    name: str
    model: type[BaseModel]
    description: str
    instructions: str
    keywords: dict[str, float] = field(default_factory=dict)
    min_score: float = 3.0

    @cached_property
    def version(self) -> str:
        schema = json.dumps(self.model.model_json_schema(), sort_keys=True)
        return stable_hash(self.name, schema, self.instructions)[:12]

    @property
    def field_names(self) -> list[str]:
        return list(self.model.model_fields)

    def score(self, text: str) -> float:
        lowered = text.lower()
        return sum(weight for keyword, weight in self.keywords.items() if re.search(keyword, lowered))


class SchemaRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, SchemaSpec] = {}

    def register(self, spec: SchemaSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"schema '{spec.name}' is already registered")
        self._specs[spec.name] = spec

    def get(self, name: str) -> SchemaSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise NotFoundError(f"schema '{name}' is not registered") from None

    def all(self) -> list[SchemaSpec]:
        return list(self._specs.values())

    @property
    def version(self) -> str:
        return stable_hash(*(f"{s.name}:{s.version}" for s in sorted(self.all(), key=lambda s: s.name)))[:12]

    def classify(self, document: DocumentModel) -> SchemaSpec | None:
        text = " ".join(block.text for block in document.iter_blocks())[:20000]
        scored = sorted(((spec.score(text), spec) for spec in self._specs.values()), key=lambda x: -x[0])
        if not scored:
            return None
        best_score, best = scored[0]
        return best if best_score >= best.min_score else None


def default_registry() -> SchemaRegistry:
    from docforge.extraction.schemas.contract import Contract
    from docforge.extraction.schemas.invoice import Invoice

    registry = SchemaRegistry()
    registry.register(
        SchemaSpec(
            name="invoice",
            model=Invoice,
            description="Vendor invoice with line items and totals",
            instructions=(
                "Copy amounts exactly as printed, without currency symbols or thousands separators. "
                "Use ISO dates. If the invoice says payment is due on receipt, due_date is null."
            ),
            keywords={
                r"\binvoice\b": 2.0,
                r"\binvoice (number|no\.?|#)": 2.0,
                r"\bbill to\b": 1.0,
                r"\bsubtotal\b": 1.0,
                r"\btotal due\b|\bamount due\b": 1.5,
                r"\bunit price\b": 0.5,
            },
        )
    )
    registry.register(
        SchemaSpec(
            name="contract",
            model=Contract,
            description="Commercial agreement with parties, term, renewal and value",
            instructions=(
                "party_a and party_b are the legal entity names from the preamble, without role labels. "
                "notice_period_days is the notice required to terminate or prevent renewal."
            ),
            keywords={
                r"\bagreement\b": 2.0,
                r"\bby and between\b": 2.0,
                r"\bgoverned by the laws\b": 1.0,
                r"\beffective date\b": 1.0,
                r"\bterm\b": 0.5,
                r"\bwritten notice\b": 0.5,
            },
        )
    )
    return registry


def load_registry(modules: Sequence[str] = ()) -> SchemaRegistry:
    """The bundled schemas plus any registered by configuration.

    Each module named in ``SCHEMA_MODULES`` must expose ``SCHEMAS: list[SchemaSpec]``. Schemas
    without a dedicated table are mirrored into the generic ``entity_records`` table.
    """
    registry = default_registry()
    for name in modules:
        module = importlib.import_module(name)
        specs = getattr(module, "SCHEMAS", None)
        if not isinstance(specs, list) or not all(isinstance(spec, SchemaSpec) for spec in specs):
            raise TypeError(f"{name}.SCHEMAS must be a list of SchemaSpec")
        for spec in specs:
            registry.register(spec)
    return registry
