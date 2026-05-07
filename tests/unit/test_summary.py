"""Tests for `multihop_eval.summary.build_summary`."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from multihop_eval.models import (
    AcceptedQA,
    ProofPoint,
    RejectedQA,
    RejectionReason,
    RubricScore,
    RunResult,
)
from multihop_eval.summary import build_summary


def _accepted(
    *,
    cluster: str = "dom/cluster_a",
    persona: str = "domain_expert",
    hops: int = 2,
    weighted: float | None = 0.8,
    rubric: dict[str, RubricScore] | None = None,
) -> AcceptedQA:
    return AcceptedQA(
        cluster_id=cluster,
        partition_id="p",
        hop_count=hops,
        persona=persona,
        reasoning_chain="r",
        question="Q?",
        answer="A.",
        proof_list=[ProofPoint("x", "src/a"), ProofPoint("y", "src/b")],
        rubric_scores=rubric or {},
        rubric_weighted_score=weighted,
    )


def _rejected(reason: RejectionReason = RejectionReason.MULTIHOP_BELOW_FLOOR) -> RejectedQA:
    return RejectedQA(
        cluster_id="dom/cluster_a",
        persona="domain_expert",
        seed_doc_id="src/seed",
        reason=reason,
    )


def _result(accepted, rejected) -> RunResult:
    started = datetime(2026, 1, 1, 0, 0, 0)
    finished = started + timedelta(seconds=30)
    return RunResult(
        accepted=list(accepted),
        rejected=list(rejected),
        cluster_targets={"dom/cluster_a": 5},
        cluster_achieved={"dom/cluster_a": len(list(accepted))},
        started_at=started,
        finished_at=finished,
    )


def test_summary_empty_run():
    s = build_summary(_result([], []))
    assert s.total_accepted == 0
    assert s.total_rejected == 0
    assert s.accept_rate == 0.0
    assert s.avg_hop_count is None
    assert s.avg_weighted_rubric is None
    assert s.duration_s == 30.0


def test_summary_counts_and_distributions():
    accepted = [
        _accepted(hops=2, persona="domain_expert"),
        _accepted(hops=3, persona="analyst"),
        _accepted(hops=3, persona="domain_expert"),
    ]
    rejected = [
        _rejected(RejectionReason.MULTIHOP_BELOW_FLOOR),
        _rejected(RejectionReason.PROOF_VERIFY_FAILED),
        _rejected(RejectionReason.MULTIHOP_BELOW_FLOOR),
    ]
    s = build_summary(_result(accepted, rejected))

    assert s.total_accepted == 3
    assert s.total_rejected == 3
    assert s.accept_rate == pytest.approx(0.5)
    assert s.avg_hop_count == pytest.approx((2 + 3 + 3) / 3)
    assert s.hop_distribution == {2: 1, 3: 2}
    assert s.persona_distribution == {"domain_expert": 2, "analyst": 1}
    assert s.rejection_breakdown == {
        RejectionReason.MULTIHOP_BELOW_FLOOR.value: 2,
        RejectionReason.PROOF_VERIFY_FAILED.value: 1,
    }


def test_summary_computes_per_field_rubric_means():
    accepted = [
        _accepted(
            rubric={
                "factuality": RubricScore(5, "ok"),
                "conciseness": RubricScore(4, "ok"),
            },
            weighted=0.9,
        ),
        _accepted(
            rubric={
                "factuality": RubricScore(3, "ok"),
                "conciseness": RubricScore(2, "ok"),
            },
            weighted=0.5,
        ),
    ]
    s = build_summary(_result(accepted, []))
    assert s.rubric_means["factuality"] == pytest.approx(4.0)
    assert s.rubric_means["conciseness"] == pytest.approx(3.0)
    assert s.avg_weighted_rubric == pytest.approx(0.7)


def test_summary_handles_partial_rubric_coverage():
    """An accepted row missing a rubric field is excluded from that mean
    but still counted everywhere else."""
    accepted = [
        _accepted(rubric={"factuality": RubricScore(5, "ok")}, weighted=0.9),
        _accepted(rubric={}, weighted=None),
    ]
    s = build_summary(_result(accepted, []))
    assert s.total_accepted == 2
    assert s.rubric_means == {"factuality": 5.0}
    assert s.avg_weighted_rubric == pytest.approx(0.9)
