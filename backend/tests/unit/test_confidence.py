from __future__ import annotations

from docforge.extraction.confidence import score_field


def test_grounding_caps_unverifiable_values() -> None:
    grounded = score_field(
        model_confidence=0.95, match="exact", is_null=False, repaired=False, has_open_issue=False
    )
    ungrounded = score_field(
        model_confidence=0.95, match="none", is_null=False, repaired=False, has_open_issue=False
    )
    assert grounded > 0.95 > 0.8 > ungrounded


def test_repairs_and_open_issues_reduce_confidence() -> None:
    base = score_field(
        model_confidence=0.9, match="exact", is_null=False, repaired=False, has_open_issue=False
    )
    repaired = score_field(
        model_confidence=0.9, match="exact", is_null=False, repaired=True, has_open_issue=False
    )
    broken = score_field(
        model_confidence=0.9, match="exact", is_null=False, repaired=True, has_open_issue=True
    )
    assert base > repaired > broken
    assert broken < 0.5


def test_absent_values_rely_on_the_model() -> None:
    assert (
        score_field(model_confidence=0.9, match="none", is_null=True, repaired=False, has_open_issue=False)
        == 0.81
    )
