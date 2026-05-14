"""Shared dataclasses passed between pipeline stages and the UI.

Keeping these in one module means pipeline / orchestrator / UI / tests can
import the same shape without circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class RejectionReason(StrEnum):
    """Reason a candidate QA pair was discarded — surfaced in UI events."""

    LLM_GEN_ERROR = "llm_gen_error"
    MISSING_KEY = "missing_key_in_llm_output"
    MULTIHOP_BELOW_FLOOR = "multihop_below_floor"
    PROOF_VERIFY_FAILED = "proof_verification_failed"
    PROOF_COLLAPSED_TO_ONE_SOURCE = "proof_collapsed_to_one_source"
    CONTEXT_TOO_LONG = "context_too_long_at_min_size"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass
class ProofPoint:
    point: str
    source_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"point": self.point, "source_id": self.source_id}


@dataclass
class RubricScore:
    score: float
    justification: str

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "justification": self.justification}


@dataclass
class AcceptedQA:
    """A QA pair that survived multi-hop + proof checks (and optional rubric)."""

    cluster_id: str
    partition_id: str
    hop_count: int
    persona: str
    reasoning_chain: str
    question: str
    answer: str
    proof_list: list[ProofPoint]
    rubric_scores: dict[str, RubricScore] = field(default_factory=dict)
    rubric_weighted_score: float | None = None

    def to_row_dict(self) -> dict[str, Any]:
        """Serialise to the dict shape expected by `ArangoGateway.insert_qa_row`
        and the Excel exporter.
        """
        proof_str = "\n".join(f"- [{p.source_id}]\n  {p.point}" for p in self.proof_list)
        return {
            "cluster_id": self.cluster_id,
            "partition_id": self.partition_id,
            "hop_count": self.hop_count,
            "persona": self.persona,
            "reasoning_chain": self.reasoning_chain,
            "question": self.question,
            "answer": self.answer,
            "proof_list": [p.to_dict() for p in self.proof_list],
            "proof": proof_str,
            "rubric_scores": {k: v.to_dict() for k, v in self.rubric_scores.items()},
            "rubric_weighted_score": self.rubric_weighted_score,
        }


@dataclass
class RejectedQA:
    cluster_id: str
    persona: str
    seed_doc_id: str
    reason: RejectionReason
    detail: str = ""


@dataclass
class RunEvent:
    """An event emitted during a run — consumed by the Streamlit live log."""

    kind: str  # 'cluster_start', 'seed', 'accepted', 'rejected', 'pass_done', 'run_done', 'error'
    payload: dict[str, Any]
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RunResult:
    """Full result of a generation run — what the dashboard displays."""

    accepted: list[AcceptedQA]
    rejected: list[RejectedQA]
    cluster_targets: dict[str, int]
    cluster_achieved: dict[str, int]
    started_at: datetime
    finished_at: datetime

    @property
    def accept_rate(self) -> float:
        total = len(self.accepted) + len(self.rejected)
        return (len(self.accepted) / total) if total else 0.0
