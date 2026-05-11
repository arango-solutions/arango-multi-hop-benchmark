"""Rule-based generation metrics (no LLM-as-judge).

These metrics treat the answer text and the retrieved-chunk text as the only
inputs — no model is called. The trade-off vs LLM-judge metrics is precision:
these are deterministic, cheap, and reproducible, but they can't catch a
well-written hallucination that happens to share keywords with the chunks.

Metrics produced:

* **groundedness** — Fraction of answer sentences whose fuzzy match against
  the concatenated retrieved-chunk text crosses `fuzz_threshold`.
* **source_diversity** — Mean number of distinct `doc_id`s per response.
* **citation_coverage** — Of the citations the answer contains (regex
  `[doc/id]`), what fraction point at a `doc_id` the system actually
  retrieved.
* **length_anomaly_rate** — Fraction of answers whose `len(answer)` has a
  z-score exceeding `length_z_threshold` (i.e. an outlier in either direction).
* **rouge_l** — Mean ROUGE-L F1 against the golden answer.
* **empty_retrieval_rate** — Fraction of responses whose retrieved chunks
  list is empty (or whose top score is below `empty_retrieval_min_score`).
"""

from __future__ import annotations

import re
import statistics
from typing import Any

import pysbd
from rapidfuzz import fuzz
from rouge_score import rouge_scorer

from multihop_eval.rag_eval.models import RagResponse

# Recognise citations like `[sources/abc]`, `[doc-123]`, or `[some-id]`. We
# deliberately keep this loose so per-RAG citation styles don't break us.
_CITATION_RE = re.compile(r"\[([A-Za-z0-9_./:\-]{2,128})\]")

_SENTENCE_SEGMENTER = pysbd.Segmenter(language="en", clean=False)
_ROUGE_SCORER = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)


def _sentences(text: str) -> list[str]:
    """Split `text` into sentences, dropping empties."""
    if not text or not text.strip():
        return []
    return [s.strip() for s in _SENTENCE_SEGMENTER.segment(text) if s and s.strip()]


def _groundedness_score(
    answer: str,
    chunk_text_blob: str,
    *,
    fuzz_threshold: int,
) -> tuple[float, int, int]:
    """Fraction of answer sentences grounded in the retrieved-chunk text.

    Returns `(score, grounded_count, total_sentences)`. If the answer is empty
    or no chunks have text, returns `(0.0, 0, 0)`.
    """
    sentences = _sentences(answer)
    if not sentences or not chunk_text_blob:
        return 0.0, 0, len(sentences)
    grounded = 0
    for s in sentences:
        if fuzz.partial_ratio(s, chunk_text_blob) >= fuzz_threshold:
            grounded += 1
    return grounded / len(sentences), grounded, len(sentences)


def _citation_coverage(answer: str, retrieved_doc_ids: set[str]) -> tuple[float, int, int]:
    """Fraction of citation tokens in `answer` that map to a retrieved `doc_id`.

    Returns `(coverage, supported_count, total_citations)`. With zero
    citations, returns `(0.0, 0, 0)` — the dashboard treats 0 citations as
    "no claims to back up", not as a perfect score.
    """
    citations = _CITATION_RE.findall(answer or "")
    if not citations:
        return 0.0, 0, 0
    supported = sum(1 for c in citations if c in retrieved_doc_ids)
    return supported / len(citations), supported, len(citations)


def _length_anomalies(
    answer_lengths: list[int], *, z_threshold: float
) -> tuple[float, list[float]]:
    """Compute per-response length z-scores + the anomaly rate."""
    if len(answer_lengths) < 2:
        # With <2 samples, stddev is undefined — declare zero anomalies.
        return 0.0, [0.0] * len(answer_lengths)
    mu = statistics.mean(answer_lengths)
    sd = statistics.pstdev(answer_lengths)
    if sd == 0:
        return 0.0, [0.0] * len(answer_lengths)
    zs = [(length - mu) / sd for length in answer_lengths]
    anomalies = sum(1 for z in zs if abs(z) > z_threshold)
    return anomalies / len(answer_lengths), zs


def _rouge_l_f1(reference: str, candidate: str) -> float:
    """ROUGE-L F1 between two strings; 0.0 if either is empty."""
    if not reference or not candidate:
        return 0.0
    return float(_ROUGE_SCORER.score(reference, candidate)["rougeL"].fmeasure)


def _empty_retrieval(
    responses: list[RagResponse], *, min_score: float | None
) -> tuple[float, list[bool]]:
    """Per-response empty flag + the rate across all responses."""
    if not responses:
        return 0.0, []
    flags: list[bool] = []
    for r in responses:
        chunks = r.retrieved_chunks
        if not chunks:
            flags.append(True)
            continue
        if min_score is None:
            flags.append(False)
            continue
        # All chunks below the min-score floor -> treated as effectively empty.
        top = max((c.score if c.score is not None else float("-inf")) for c in chunks)
        flags.append(top < min_score)
    return sum(flags) / len(flags), flags


def compute_generation_metrics(
    responses: list[RagResponse],
    goldens_by_key: dict[str, dict[str, Any]],
    *,
    fuzz_threshold: int = 75,
    length_z_threshold: float = 2.0,
    empty_retrieval_min_score: float | None = None,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Compute every rule-based generation metric the client requested.

    Args:
        responses: All `RagResponse` rows for the system under evaluation.
        goldens_by_key: `{qa_key: golden_row}` — used to grab the reference
            answer for ROUGE-L. Goldens without a matching response are ignored.
        fuzz_threshold: rapidfuzz `partial_ratio` cutoff (0-100) above which a
            sentence is considered grounded.
        length_z_threshold: |z| above which a response is flagged as a length
            outlier in either direction.
        empty_retrieval_min_score: Optional minimum chunk score for a response
            to count as "non-empty". `None` means any non-empty chunk list
            qualifies.

    Returns:
        Tuple of:
          * Aggregate metrics dict.
          * Per-query rows for the drill-down table.
    """
    answer_lengths = [len(r.answer or "") for r in responses]
    length_anomaly_rate, zs = _length_anomalies(
        answer_lengths, z_threshold=length_z_threshold
    )
    empty_rate, empty_flags = _empty_retrieval(
        responses, min_score=empty_retrieval_min_score
    )

    per_query: list[dict[str, Any]] = []
    grounded_scores: list[float] = []
    diversity_scores: list[int] = []
    citation_scores: list[float] = []
    rouge_scores: list[float] = []

    for r, z, is_empty in zip(responses, zs, empty_flags, strict=True):
        retrieved_doc_ids = {c.doc_id for c in r.retrieved_chunks}
        # Build the chunk-text blob once per response — falls back to doc_id
        # if a chunk has no text so groundedness isn't trivially zero for
        # systems that only return ids.
        blob = "\n".join(c.text or c.doc_id for c in r.retrieved_chunks)
        groundedness, g_hit, g_total = _groundedness_score(
            r.answer or "", blob, fuzz_threshold=fuzz_threshold
        )
        coverage, supported, total_citations = _citation_coverage(
            r.answer or "", retrieved_doc_ids
        )
        diversity = len(retrieved_doc_ids)
        golden = goldens_by_key.get(r.qa_pair_key) or {}
        rouge = _rouge_l_f1(str(golden.get("answer") or ""), r.answer or "")

        grounded_scores.append(groundedness)
        diversity_scores.append(diversity)
        # Only include responses that actually made claims in the citation
        # average — otherwise systems that never cite get a flattering 0.0
        # baked into the mean.
        if total_citations > 0:
            citation_scores.append(coverage)
        rouge_scores.append(rouge)

        per_query.append(
            {
                "qa_pair_key": r.qa_pair_key,
                "groundedness": groundedness,
                "grounded_sentences": g_hit,
                "total_sentences": g_total,
                "source_diversity": diversity,
                "citation_coverage": coverage,
                "n_citations": total_citations,
                "answer_length": len(r.answer or ""),
                "length_z": z,
                "is_length_anomaly": abs(z) > length_z_threshold,
                "rouge_l_f1": rouge,
                "is_empty_retrieval": is_empty,
            }
        )

    aggregate = {
        "groundedness": (
            statistics.mean(grounded_scores) if grounded_scores else 0.0
        ),
        "source_diversity": (
            statistics.mean(diversity_scores) if diversity_scores else 0.0
        ),
        "citation_coverage": (
            statistics.mean(citation_scores) if citation_scores else 0.0
        ),
        "length_anomaly_rate": length_anomaly_rate,
        "rouge_l_f1": statistics.mean(rouge_scores) if rouge_scores else 0.0,
        "empty_retrieval_rate": empty_rate,
    }
    return aggregate, per_query
