"""Tests for `multihop_eval.generation.rubric_evaluator`."""

from __future__ import annotations

import pytest

from multihop_eval.generation.rubric import RubricField
from multihop_eval.generation.rubric_evaluator import RubricEvaluator
from tests.conftest import FakeLLMClient


def _fields() -> list[RubricField]:
    return [
        RubricField(
            name="factuality",
            description="Are claims supported by source content?",
            scale_min=1,
            scale_max=5,
            weight=2.0,
        ),
        RubricField(
            name="conciseness",
            description="Is the answer free of unnecessary filler?",
            scale_min=1,
            scale_max=5,
            weight=1.0,
        ),
    ]


def _make_evaluator(responses):
    fake = FakeLLMClient(responses=responses)
    evaluator = RubricEvaluator(fake, _fields())  # type: ignore[arg-type]
    return evaluator, fake


def test_rubric_evaluator_requires_at_least_one_field():
    fake = FakeLLMClient(responses=[])
    with pytest.raises(ValueError):
        RubricEvaluator(fake, [])  # type: ignore[arg-type]


def test_rubric_evaluator_returns_per_field_scores_and_aggregate():
    judge_response = {
        "factuality": {"score": 5, "justification": "All claims sourced."},
        "conciseness": {"score": 3, "justification": "Could trim."},
    }
    evaluator, _fake = _make_evaluator([judge_response])
    scores, weighted = evaluator.score(
        question="Q?",
        answer="A.",
        proof=[],
        persona_label="domain_expert",
        content_blob="content",
    )
    assert scores["factuality"].score == 5
    assert scores["factuality"].justification == "All claims sourced."
    assert scores["conciseness"].score == 3
    # Weighted aggregate, normalised to 0..1:
    #   factuality: (5-1)/(5-1) = 1.0, weight 2.0
    #   conciseness: (3-1)/(5-1) = 0.5, weight 1.0
    #   weighted_sum / total_weight = (1.0*2 + 0.5*1) / 3 = 0.8333...
    assert weighted == pytest.approx((1.0 * 2 + 0.5 * 1) / 3, rel=1e-3)


def test_rubric_evaluator_clips_out_of_range_scores():
    evaluator, _ = _make_evaluator(
        [{"factuality": {"score": 99, "justification": "x"}, "conciseness": {"score": -3, "justification": "y"}}]
    )
    scores, _ = evaluator.score(
        question="Q?", answer="A.", proof=[], persona_label="x", content_blob="c"
    )
    assert scores["factuality"].score == 5  # clipped to scale_max
    assert scores["conciseness"].score == 1  # clipped to scale_min


def test_rubric_evaluator_handles_missing_field_softly():
    evaluator, _ = _make_evaluator(
        [{"factuality": {"score": 4, "justification": "ok"}}]  # no 'conciseness'
    )
    scores, _ = evaluator.score(
        question="Q?", answer="A.", proof=[], persona_label="x", content_blob="c"
    )
    assert scores["factuality"].score == 4
    assert scores["conciseness"].score == 1
    assert "omitted" in scores["conciseness"].justification.lower()


def test_rubric_evaluator_handles_non_numeric_score():
    evaluator, _ = _make_evaluator(
        [{"factuality": {"score": "five", "justification": "x"}, "conciseness": {"score": 4, "justification": "y"}}]
    )
    scores, _ = evaluator.score(
        question="Q?", answer="A.", proof=[], persona_label="x", content_blob="c"
    )
    # Non-numeric falls back to scale_min.
    assert scores["factuality"].score == 1


def test_rubric_evaluator_raises_on_non_json_output():
    evaluator, _ = _make_evaluator(["this is not json at all"])
    with pytest.raises(ValueError, match="non-JSON"):
        evaluator.score(
            question="Q?", answer="A.", proof=[], persona_label="x", content_blob="c"
        )
