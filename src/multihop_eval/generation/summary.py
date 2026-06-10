"""Aggregate stats over a `RunResult` for the dashboard."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from multihop_eval.generation.models import AcceptedQA, RejectedQA, RunResult


@dataclass
class Summary:
    """Plain-data summary the dashboard renders as KPIs + charts."""

    total_accepted: int = 0
    total_rejected: int = 0
    accept_rate: float = 0.0
    avg_hop_count: float | None = None
    avg_weighted_rubric: float | None = None
    hop_distribution: dict[int, int] = field(default_factory=dict)
    persona_distribution: dict[str, int] = field(default_factory=dict)
    cluster_coverage: dict[str, int] = field(default_factory=dict)
    rejection_breakdown: dict[str, int] = field(default_factory=dict)
    rubric_means: dict[str, float] = field(default_factory=dict)
    cluster_targets: dict[str, int] = field(default_factory=dict)
    cluster_achieved: dict[str, int] = field(default_factory=dict)
    duration_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "accept_rate": self.accept_rate,
            "avg_hop_count": self.avg_hop_count,
            "avg_weighted_rubric": self.avg_weighted_rubric,
            "hop_distribution": dict(self.hop_distribution),
            "persona_distribution": dict(self.persona_distribution),
            "cluster_coverage": dict(self.cluster_coverage),
            "rejection_breakdown": dict(self.rejection_breakdown),
            "rubric_means": dict(self.rubric_means),
            "cluster_targets": dict(self.cluster_targets),
            "cluster_achieved": dict(self.cluster_achieved),
            "duration_s": self.duration_s,
        }


def build_summary(result: RunResult) -> Summary:
    """Compute summary stats from a `RunResult`."""
    accepted: list[AcceptedQA] = result.accepted
    rejected: list[RejectedQA] = result.rejected

    total_accepted = len(accepted)
    total_rejected = len(rejected)
    total = total_accepted + total_rejected

    hop_dist: Counter[int] = Counter(qa.hop_count for qa in accepted)
    persona_dist: Counter[str] = Counter(qa.persona for qa in accepted)
    cluster_coverage: Counter[str] = Counter(qa.cluster_id for qa in accepted)
    rejection_breakdown: Counter[str] = Counter(rj.reason.value for rj in rejected)

    avg_hop = mean(qa.hop_count for qa in accepted) if accepted else None

    rubric_means: dict[str, float] = {}
    if accepted:
        all_field_names: set[str] = set()
        for qa in accepted:
            all_field_names.update(qa.rubric_scores.keys())
        for f in all_field_names:
            scores = [qa.rubric_scores[f].score for qa in accepted if f in qa.rubric_scores]
            if scores:
                rubric_means[f] = mean(scores)

    weighted_scores = [
        qa.rubric_weighted_score for qa in accepted if qa.rubric_weighted_score is not None
    ]
    avg_weighted = mean(weighted_scores) if weighted_scores else None

    duration_s = (result.finished_at - result.started_at).total_seconds()

    return Summary(
        total_accepted=total_accepted,
        total_rejected=total_rejected,
        accept_rate=(total_accepted / total) if total else 0.0,
        avg_hop_count=avg_hop,
        avg_weighted_rubric=avg_weighted,
        hop_distribution=dict(hop_dist),
        persona_distribution=dict(persona_dist),
        cluster_coverage=dict(cluster_coverage),
        rejection_breakdown=dict(rejection_breakdown),
        rubric_means=rubric_means,
        cluster_targets=dict(result.cluster_targets),
        cluster_achieved=dict(result.cluster_achieved),
        duration_s=duration_s,
    )


def summary_from_qa_rows(rows: list[dict[str, Any]]) -> Summary:
    """Compute a dashboard `Summary` from persisted QA rows.

    Used by the Dashboard tab when reading already-saved rows from the Arango
    QA collection (as opposed to an in-memory `RunResult`). Persisted rows
    carry no rejection records, so `total_rejected`, `accept_rate`, and
    `rejection_breakdown` are reported as empty/zero for this source.

    Each row is the dict shape produced by ``AcceptedQA.to_row_dict`` /
    ``ArangoGateway.fetch_qa_rows``: ``hop_count``, ``persona``, ``cluster_id``,
    ``rubric_scores`` (``{field: {score, justification}}``), and an optional
    ``rubric_weighted_score``.
    """
    total = len(rows)

    def _hop(row: dict[str, Any]) -> int | None:
        value = row.get("hop_count")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    hops = [h for h in (_hop(r) for r in rows) if h is not None]
    hop_dist: Counter[int] = Counter(hops)
    persona_dist: Counter[str] = Counter(str(r.get("persona", "")) for r in rows)
    cluster_coverage: Counter[str] = Counter(str(r.get("cluster_id", "")) for r in rows)

    avg_hop = mean(hops) if hops else None

    rubric_means: dict[str, float] = {}
    field_scores: dict[str, list[float]] = {}
    for row in rows:
        scores = row.get("rubric_scores") or {}
        if not isinstance(scores, dict):
            continue
        for field_name, entry in scores.items():
            score = entry.get("score") if isinstance(entry, dict) else None
            if score is None:
                continue
            try:
                field_scores.setdefault(field_name, []).append(float(score))
            except (TypeError, ValueError):
                continue
    for field_name, values in field_scores.items():
        if values:
            rubric_means[field_name] = mean(values)

    weighted = [
        float(r["rubric_weighted_score"])
        for r in rows
        if r.get("rubric_weighted_score") is not None
    ]
    avg_weighted = mean(weighted) if weighted else None

    return Summary(
        total_accepted=total,
        total_rejected=0,
        accept_rate=0.0,
        avg_hop_count=avg_hop,
        avg_weighted_rubric=avg_weighted,
        hop_distribution=dict(hop_dist),
        persona_distribution=dict(persona_dist),
        cluster_coverage=dict(cluster_coverage),
        rejection_breakdown={},
        rubric_means=rubric_means,
        cluster_targets={},
        cluster_achieved=dict(cluster_coverage),
        duration_s=None,
    )
