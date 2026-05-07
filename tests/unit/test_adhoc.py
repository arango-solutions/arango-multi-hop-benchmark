"""Tests for `multihop_eval.adhoc.AdhocEvaluator`."""

from __future__ import annotations

import pytest

from multihop_eval.adhoc import AdhocEvaluator
from multihop_eval.rubric import RubricField
from tests.conftest import FakeLLMClient


def _sources():
    return [
        {"_id": "src/a", "content": "Doc A about wellness benefits."},
        {"_id": "src/b", "content": "Doc B about retirement matching."},
    ]


def _proof():
    return [
        {"point": "Wellness program is offered.", "source_id": "src/a"},
        {"point": "Retirement match is 5%.", "source_id": "src/b"},
    ]


def test_adhoc_happy_path_pass_pass():
    fake = FakeLLMClient(
        responses=[
            # Multi-hop check
            {
                "verdict": "pass",
                "genuine_hop_count": 2,
                "is_multihop": True,
                "reason": "Two distinct hops.",
                "genuine_source_ids": ["src/a", "src/b"],
            },
            # Proof verify
            {"verdict": "pass", "corrected_proof": _proof(), "notes": "all correct"},
        ]
    )
    evaluator = AdhocEvaluator(llm=fake, rubric_fields=None)  # type: ignore[arg-type]
    result = evaluator.evaluate(
        question="What's offered?",
        answer="Wellness and 5% retirement match.",
        reasoning_chain="A->B",
        proof=_proof(),
        sources=_sources(),
    )
    assert result.multi_hop_pass is True
    assert result.genuine_hop_count == 2
    assert result.proof_verdict == "pass"
    assert result.rubric_scores == {}


def test_adhoc_fail_path_returns_reason():
    fake = FakeLLMClient(
        responses=[
            {
                "verdict": "fail",
                "genuine_hop_count": 1,
                "is_multihop": False,
                "reason": "Single source could answer.",
                "genuine_source_ids": ["src/a"],
            },
            {"verdict": "fail", "corrected_proof": _proof(), "notes": "could not ground"},
            {"verdict": "fail", "corrected_proof": _proof(), "notes": "still failing"},
            {"verdict": "fail", "corrected_proof": _proof(), "notes": "still failing"},
        ]
    )
    evaluator = AdhocEvaluator(llm=fake, rubric_fields=None)  # type: ignore[arg-type]
    result = evaluator.evaluate(
        question="What's offered?",
        answer="Just wellness.",
        reasoning_chain="just A",
        proof=_proof(),
        sources=_sources(),
    )
    assert result.multi_hop_pass is False
    assert result.genuine_hop_count == 1
    assert "Single source" in result.multi_hop_reason
    assert result.proof_verdict == "fail"


def test_adhoc_with_rubric_scoring():
    rubric = [
        RubricField(name="factuality", description="x" * 12, scale_min=1, scale_max=5),
    ]
    fake = FakeLLMClient(
        responses=[
            {"verdict": "pass", "genuine_hop_count": 2, "is_multihop": True, "reason": "ok", "genuine_source_ids": ["src/a", "src/b"]},
            {"verdict": "pass", "corrected_proof": _proof(), "notes": "ok"},
            {"factuality": {"score": 5, "justification": "all sourced"}},
        ]
    )
    evaluator = AdhocEvaluator(llm=fake, rubric_fields=rubric)  # type: ignore[arg-type]
    result = evaluator.evaluate(
        question="Q?",
        answer="A.",
        reasoning_chain="r",
        proof=_proof(),
        sources=_sources(),
        score_with_rubric=True,
    )
    assert "factuality" in result.rubric_scores
    assert result.rubric_scores["factuality"]["score"] == 5
    assert result.rubric_weighted_score == pytest.approx(1.0)


def test_adhoc_requires_at_least_two_sources():
    fake = FakeLLMClient(responses=[])
    evaluator = AdhocEvaluator(llm=fake, rubric_fields=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least 2"):
        evaluator.evaluate(
            question="Q?",
            answer="A.",
            reasoning_chain="r",
            proof=_proof(),
            sources=_sources()[:1],
        )


def test_adhoc_score_with_rubric_without_fields_raises():
    fake = FakeLLMClient(
        responses=[
            {"verdict": "pass", "genuine_hop_count": 2, "is_multihop": True, "reason": "ok", "genuine_source_ids": ["src/a", "src/b"]},
            {"verdict": "pass", "corrected_proof": _proof(), "notes": "ok"},
        ]
    )
    evaluator = AdhocEvaluator(llm=fake, rubric_fields=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="no rubric_fields"):
        evaluator.evaluate(
            question="Q?",
            answer="A.",
            reasoning_chain="r",
            proof=_proof(),
            sources=_sources(),
            score_with_rubric=True,
        )
