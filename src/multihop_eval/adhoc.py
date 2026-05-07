"""Ad-hoc evaluation entrypoint.

The Streamlit "Ad-hoc" tab lets users paste a question / answer / proof /
sources and run only the validation (no generation). This module exposes the
exact same verification logic the full pipeline uses, plus an optional rubric
score, returning a structured result the UI can render directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from multihop_eval.llm_client import LLMClient
from multihop_eval.pipeline import GenerationPipeline, _build_content_blob
from multihop_eval.rubric import RubricField
from multihop_eval.rubric_evaluator import RubricEvaluator

log = logging.getLogger(__name__)


@dataclass
class AdhocResult:
    """Outcome of an ad-hoc evaluation run."""

    multi_hop_pass: bool
    genuine_hop_count: int
    multi_hop_reason: str
    proof_verdict: str
    corrected_proof: list[dict[str, Any]]
    rubric_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    rubric_weighted_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "multi_hop_pass": self.multi_hop_pass,
            "genuine_hop_count": self.genuine_hop_count,
            "multi_hop_reason": self.multi_hop_reason,
            "proof_verdict": self.proof_verdict,
            "corrected_proof": self.corrected_proof,
            "rubric_scores": self.rubric_scores,
            "rubric_weighted_score": self.rubric_weighted_score,
        }


class AdhocEvaluator:
    """Run multi-hop check + proof verification on user-supplied inputs."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        rubric_fields: list[RubricField] | None = None,
        max_verify_rounds: int = 3,
    ) -> None:
        self.llm = llm
        self._pipeline = GenerationPipeline(llm=llm, max_verify_rounds=max_verify_rounds)
        self._rubric = (
            RubricEvaluator(llm, rubric_fields)
            if rubric_fields
            else None
        )

    def evaluate(
        self,
        *,
        question: str,
        answer: str,
        reasoning_chain: str,
        proof: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        persona_label: str = "ad_hoc",
        score_with_rubric: bool = False,
    ) -> AdhocResult:
        """Validate the supplied QA + proof against the supplied sources."""
        if len(sources) < 2:
            raise ValueError("Need at least 2 source documents for multi-hop evaluation.")
        for required in ("_id",):
            if not all(required in s for s in sources):
                raise ValueError(f"Every source dict must contain a {required!r} key.")

        content_blob = _build_content_blob(sources)
        required_hops = max(2, len({p.get("source_id") for p in proof if p.get("source_id")}))

        passed, genuine_hops, mh_reason = self._pipeline._check_multihop(
            question, answer, reasoning_chain, proof, required_hops, content_blob
        )

        verdict = "fail"
        corrected = list(proof)
        for _ in range(self._pipeline.max_verify_rounds):
            verdict, corrected = self._pipeline._verify_and_correct_proof(
                question, answer, corrected, content_blob
            )
            if verdict == "pass":
                break

        result = AdhocResult(
            multi_hop_pass=passed,
            genuine_hop_count=genuine_hops,
            multi_hop_reason=mh_reason,
            proof_verdict=verdict,
            corrected_proof=corrected,
        )

        if score_with_rubric:
            if self._rubric is None:
                raise ValueError(
                    "score_with_rubric=True but no rubric_fields were provided to AdhocEvaluator."
                )
            scores, weighted = self._rubric.score(
                question=question,
                answer=answer,
                proof=corrected,
                persona_label=persona_label,
                content_blob=content_blob,
            )
            result.rubric_scores = {k: v.to_dict() for k, v in scores.items()}
            result.rubric_weighted_score = weighted

        return result
