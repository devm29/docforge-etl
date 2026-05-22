from __future__ import annotations

from docforge.domain.records import MatchKind

GROUNDING_SCORE: dict[MatchKind, float] = {"exact": 1.0, "fuzzy": 0.85, "block": 0.7, "none": 0.3}
REPAIR_FACTOR = 0.92
OPEN_ISSUE_FACTOR = 0.5
ABSENT_FACTOR = 0.9


def score_field(
    *, model_confidence: float, match: MatchKind, is_null: bool, repaired: bool, has_open_issue: bool
) -> float:
    """Blends what the model claims with what the pipeline can verify.

    A value whose quote is found word for word on the page earns full grounding credit; a value that
    cannot be traced back to the document is capped no matter how sure the model says it is.
    Absent values cannot be grounded, so they rely on the model's confidence that nothing is there.
    """
    if is_null:
        score = model_confidence * ABSENT_FACTOR
    else:
        score = 0.5 * model_confidence + 0.5 * GROUNDING_SCORE[match]
    if repaired:
        score *= REPAIR_FACTOR
    if has_open_issue:
        score *= OPEN_ISSUE_FACTOR
    return round(min(1.0, max(0.0, score)), 3)
