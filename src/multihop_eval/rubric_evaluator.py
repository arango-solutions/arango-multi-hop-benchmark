"""Score an accepted QA pair against a user-defined rubric using a judge LLM."""

from __future__ import annotations

import logging
from typing import Any

from multihop_eval.llm_client import LLMClient, extract_json
from multihop_eval.models import RubricScore
from multihop_eval.prompts import SYSTEM_PROMPT_RUBRIC, build_rubric_prompt
from multihop_eval.rubric import RubricField

log = logging.getLogger(__name__)


class RubricEvaluator:
    """Score a QA pair on each user-defined rubric criterion."""

    def __init__(self, llm: LLMClient, rubric_fields: list[RubricField]) -> None:
        if not rubric_fields:
            raise ValueError("RubricEvaluator requires at least one rubric field.")
        self.llm = llm
        self.rubric_fields = rubric_fields

    def score(
        self,
        *,
        question: str,
        answer: str,
        proof: list[dict[str, Any]],
        persona_label: str,
        content_blob: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> tuple[dict[str, RubricScore], float]:
        """Run the judge LLM and return (per-field scores, weighted aggregate).

        For any field the LLM omits, a score of `scale_min` and a default
        justification are recorded — failing soft is preferable to dropping
        an otherwise-good QA pair, but the gap is logged and visible in the UI.
        """
        prompt = build_rubric_prompt(
            question=question,
            answer=answer,
            proof=proof,
            persona_label=persona_label,
            rubric_fields=self.rubric_fields,
            content_blob=content_blob,
        )
        raw = self.llm.call(SYSTEM_PROMPT_RUBRIC, prompt, max_tokens=max_tokens, temperature=temperature)
        try:
            parsed = extract_json(raw)
        except ValueError as exc:
            raise ValueError(f"Rubric LLM returned non-JSON output: {exc}") from exc

        scores: dict[str, RubricScore] = {}
        for f in self.rubric_fields:
            entry = parsed.get(f.name)
            if not isinstance(entry, dict) or "score" not in entry:
                log.warning(
                    "Rubric judge omitted field %r — defaulting to scale_min=%d.",
                    f.name,
                    f.scale_min,
                )
                scores[f.name] = RubricScore(
                    score=float(f.scale_min),
                    justification="(judge LLM omitted this field; defaulted to scale_min)",
                )
                continue

            try:
                value = float(entry["score"])
            except (TypeError, ValueError):
                log.warning("Rubric judge gave non-numeric score for %r — defaulting.", f.name)
                value = float(f.scale_min)
            value = _clip(value, f.scale_min, f.scale_max)
            justification = str(entry.get("justification", "")).strip() or "(no justification)"
            scores[f.name] = RubricScore(score=value, justification=justification)

        weighted = self.weighted_aggregate(scores)
        return scores, weighted

    def weighted_aggregate(self, scores: dict[str, RubricScore]) -> float:
        """Weighted mean of normalised (0..1) scores, in (0..1).

        Each field's raw score is normalised against its own scale, then
        weighted by `field.weight`. Returning a normalised number lets the
        dashboard show one comparable summary even when scales differ.
        """
        total_weight = 0.0
        weighted_sum = 0.0
        for f in self.rubric_fields:
            entry = scores.get(f.name)
            if entry is None:
                continue
            denom = max(1.0, float(f.scale_max - f.scale_min))
            normalised = (entry.score - f.scale_min) / denom
            weighted_sum += normalised * f.weight
            total_weight += f.weight
        return (weighted_sum / total_weight) if total_weight else 0.0


def _clip(value: float, lo: int, hi: int) -> float:
    if value < lo:
        return float(lo)
    if value > hi:
        return float(hi)
    return value
