"""Retrieval metrics computed against the golden proof_list.

We implement P@K, R@K, MRR, NDCG@K, and HitRate@K natively rather than
depending on `ranx` because (a) `ranx`'s import chain pulls in `ir_datasets`
which is slow and creates filesystem state, and (b) every formula here is
a textbook one-liner. Chunk Overlap Rate and Exact Match are also native
because they don't fit the standard qrels-vs-run shape.

Ranking convention:

* Chunks are ranked by their `score` if present, else by their `rank` field.
* Ties are broken by original `rank` (so the RAG system's order is preserved).
* When the same `doc_id` appears in multiple chunks, only the best-scored
  position counts toward gains (so a system can't game P@K by repeating).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from multihop_eval.rag_eval.models import RagResponse, RetrievedChunk

# Loose normaliser used by Exact Match: lowercase, collapse whitespace, strip
# punctuation. This is intentionally conservative; stricter EM would be too
# brittle for free-form RAG answers.
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text.lower())).strip()


def _ranked_doc_ids(chunks: list[RetrievedChunk]) -> list[str]:
    """Return doc_ids in ranking order, deduped by first occurrence.

    Ranking key: `(-score, rank)`. Chunks without a score fall to the end of
    their score bucket, ordered by their original `rank`. The first occurrence
    of any `doc_id` wins so that repeating a chunk can't boost P@K artificially.
    """
    ordered = sorted(
        chunks,
        key=lambda c: (-(c.score if c.score is not None else float("-inf")), c.rank),
    )
    seen: set[str] = set()
    out: list[str] = []
    for c in ordered:
        if c.doc_id not in seen:
            seen.add(c.doc_id)
            out.append(c.doc_id)
    return out


def _precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    if k <= 0 or not retrieved:
        return 0.0
    topk = retrieved[:k]
    return sum(1 for d in topk if d in relevant) / k


def _recall_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    if not relevant or k <= 0:
        return 0.0
    topk = retrieved[:k]
    return sum(1 for d in topk if d in relevant) / len(relevant)


def _reciprocal_rank(relevant: set[str], retrieved: list[str]) -> float:
    for i, d in enumerate(retrieved, start=1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def _ndcg_at_k(grades: dict[str, int], retrieved: list[str], k: int) -> float:
    """Standard graded NDCG@K with log2(i+2) discount (1-indexed positions).

    Works for both binary and graded qrels because binary grades are just
    grades in {0, 1}.
    """
    if k <= 0 or not grades:
        return 0.0
    dcg = sum(
        grades.get(d, 0) / math.log2(i + 2) for i, d in enumerate(retrieved[:k])
    )
    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_grades))
    return (dcg / idcg) if idcg > 0 else 0.0


def _hit_rate_at_k(relevant: set[str], retrieved: list[str], k: int) -> int:
    if k <= 0:
        return 0
    return 1 if any(d in relevant for d in retrieved[:k]) else 0


def _chunk_overlap_rate(responses: list[RagResponse]) -> float:
    """How often the same chunk doc_id reappears across queries.

    Definition: `1 - (distinct_doc_ids / total_chunk_slots)`. A value near
    `0` means the retriever returns very different chunks for every query;
    near `1` means the same handful of chunks keep coming back.
    """
    total = 0
    counts: Counter[str] = Counter()
    for r in responses:
        for chunk in r.retrieved_chunks:
            counts[chunk.doc_id] += 1
            total += 1
    if total == 0:
        return 0.0
    return 1.0 - (len(counts) / total)


def _exact_match(
    responses_by_key: dict[str, RagResponse],
    goldens_by_key: dict[str, dict[str, Any]],
) -> float:
    """Fraction of responses whose answer contains the golden answer (normalised)."""
    matched_keys = [k for k in goldens_by_key if k in responses_by_key]
    if not matched_keys:
        return 0.0
    hits = 0
    for k in matched_keys:
        gold_answer = _normalise(str(goldens_by_key[k].get("answer") or ""))
        gen_answer = _normalise(responses_by_key[k].answer or "")
        if gold_answer and gold_answer in gen_answer:
            hits += 1
    return hits / len(matched_keys)


def compute_retrieval_metrics(
    qrels: dict[str, dict[str, int]],
    responses: list[RagResponse],
    goldens_by_key: dict[str, dict[str, Any]],
    *,
    k_values: list[int],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Compute every retrieval metric the client requested.

    Args:
        qrels: Output of `build_qrels` — `{qa_key: {doc_id: grade}}`.
        responses: All `RagResponse` rows for the system under evaluation.
        goldens_by_key: `{qa_key: golden_row}` for `Exact Match` against the
            golden answer.
        k_values: Cut-offs for P@K, R@K, NDCG@K, HitRate@K.

    Returns:
        Tuple of:
          * Aggregate metrics dict — one float per metric name (mean across
            queries that appear in both `qrels` and `responses`).
          * Per-query rows: one dict per response with `qa_pair_key` and the
            per-query metric values. These drive the drill-down table in the
            dashboard.
    """
    responses_by_key = {r.qa_pair_key: r for r in responses}
    queries_in_common = [q for q in qrels if q in responses_by_key]

    sums: dict[str, float] = {"mrr": 0.0}
    for k in k_values:
        for name in ("precision", "recall", "ndcg", "hit_rate"):
            sums[f"{name}@{k}"] = 0.0

    per_query: list[dict[str, Any]] = []
    ranked_cache: dict[str, list[str]] = {}

    for r in responses:
        ranked_cache[r.qa_pair_key] = _ranked_doc_ids(r.retrieved_chunks)

    for q in queries_in_common:
        grades = qrels[q]
        relevant = {d for d, g in grades.items() if g > 0}
        retrieved = ranked_cache[q]
        sums["mrr"] += _reciprocal_rank(relevant, retrieved)
        for k in k_values:
            sums[f"precision@{k}"] += _precision_at_k(relevant, retrieved, k)
            sums[f"recall@{k}"] += _recall_at_k(relevant, retrieved, k)
            sums[f"ndcg@{k}"] += _ndcg_at_k(grades, retrieved, k)
            sums[f"hit_rate@{k}"] += _hit_rate_at_k(relevant, retrieved, k)

    aggregate: dict[str, float] = {}
    if queries_in_common:
        n = len(queries_in_common)
        aggregate = {name: total / n for name, total in sums.items()}

    aggregate["chunk_overlap_rate"] = _chunk_overlap_rate(responses)
    aggregate["exact_match"] = _exact_match(responses_by_key, goldens_by_key)

    for r in responses:
        grades = qrels.get(r.qa_pair_key, {})
        relevant = {d for d, g in grades.items() if g > 0}
        retrieved = ranked_cache[r.qa_pair_key]
        row: dict[str, Any] = {
            "qa_pair_key": r.qa_pair_key,
            "n_retrieved": len(retrieved),
            "n_relevant_retrieved": sum(1 for d in retrieved if d in relevant),
            "first_relevant_rank": next(
                (i + 1 for i, d in enumerate(retrieved) if d in relevant),
                None,
            ),
        }
        for k in k_values:
            row[f"hit_rate@{k}"] = _hit_rate_at_k(relevant, retrieved, k)
            row[f"precision@{k}"] = _precision_at_k(relevant, retrieved, k)
            row[f"recall@{k}"] = _recall_at_k(relevant, retrieved, k)
        per_query.append(row)

    return aggregate, per_query
