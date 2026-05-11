"""Tests for `multihop_eval.rag_eval.metrics.retrieval`."""

from __future__ import annotations

import pytest

from multihop_eval.rag_eval.metrics.retrieval import compute_retrieval_metrics
from multihop_eval.rag_eval.models import RagResponse, RetrievedChunk


def _response(
    *,
    key: str,
    chunk_ids: list[str],
    answer: str = "",
    system: str = "rag_v1",
) -> RagResponse:
    return RagResponse(
        system_name=system,
        qa_pair_key=key,
        question="q",
        answer=answer,
        retrieved_chunks=[
            RetrievedChunk(doc_id=d, rank=i + 1, score=1.0 / (i + 1))
            for i, d in enumerate(chunk_ids)
        ],
    )


def test_perfect_retrieval_yields_full_scores():
    qrels = {"q1": {"sources/a": 1, "sources/b": 1}}
    responses = [_response(key="q1", chunk_ids=["sources/a", "sources/b"])]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}}, k_values=[2]
    )
    assert agg["precision@2"] == pytest.approx(1.0)
    assert agg["recall@2"] == pytest.approx(1.0)
    assert agg["ndcg@2"] == pytest.approx(1.0)
    assert agg["mrr"] == pytest.approx(1.0)
    assert agg["hit_rate@2"] == pytest.approx(1.0)


def test_no_overlap_yields_zero_recall():
    qrels = {"q1": {"sources/a": 1}}
    responses = [_response(key="q1", chunk_ids=["sources/x", "sources/y"])]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}}, k_values=[2]
    )
    assert agg["recall@2"] == pytest.approx(0.0)
    assert agg["precision@2"] == pytest.approx(0.0)
    assert agg["hit_rate@2"] == 0.0


def test_mrr_is_one_over_first_relevant_rank():
    qrels = {"q1": {"sources/target": 1}}
    # Target appears at rank 3 -> MRR = 1/3
    responses = [_response(key="q1", chunk_ids=["sources/x", "sources/y", "sources/target"])]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}}, k_values=[3]
    )
    assert agg["mrr"] == pytest.approx(1 / 3)


def test_hit_rate_respects_k_cutoff():
    qrels = {"q1": {"sources/target": 1}}
    # Target appears at rank 3 -> hit_rate@2 = 0, hit_rate@3 = 1
    responses = [_response(key="q1", chunk_ids=["sources/x", "sources/y", "sources/target"])]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}}, k_values=[2, 3]
    )
    assert agg["hit_rate@2"] == 0.0
    assert agg["hit_rate@3"] == 1.0


def test_hit_rate_averages_across_queries():
    qrels = {"q1": {"sources/a": 1}, "q2": {"sources/b": 1}}
    responses = [
        _response(key="q1", chunk_ids=["sources/a"]),  # hit
        _response(key="q2", chunk_ids=["sources/x"]),  # miss
    ]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}, "q2": {"answer": ""}}, k_values=[1]
    )
    assert agg["hit_rate@1"] == pytest.approx(0.5)


def test_chunk_overlap_zero_when_all_distinct():
    qrels = {"q1": {"sources/a": 1}, "q2": {"sources/b": 1}}
    responses = [
        _response(key="q1", chunk_ids=["sources/a", "sources/b"]),
        _response(key="q2", chunk_ids=["sources/c", "sources/d"]),
    ]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}, "q2": {"answer": ""}}, k_values=[2]
    )
    # 4 slots, 4 distinct -> overlap = 0.
    assert agg["chunk_overlap_rate"] == pytest.approx(0.0)


def test_chunk_overlap_grows_with_repetition():
    qrels = {"q1": {"sources/a": 1}, "q2": {"sources/a": 1}}
    responses = [
        _response(key="q1", chunk_ids=["sources/a", "sources/a"]),  # duplicate rank not allowed per pydantic
        _response(key="q2", chunk_ids=["sources/a"]),
    ]
    # Distinct ranks but same doc — we expect partial overlap.
    # However pydantic enforces unique ranks (which it does) but allows
    # repeated doc_ids. Build a fresh response with same doc repeated under
    # different ranks.
    responses = [
        RagResponse(
            system_name="rag_v1",
            qa_pair_key="q1",
            question="q",
            retrieved_chunks=[
                RetrievedChunk(doc_id="sources/a", rank=1),
                RetrievedChunk(doc_id="sources/a", rank=2),  # duplicate doc, distinct rank
            ],
        ),
        RagResponse(
            system_name="rag_v1",
            qa_pair_key="q2",
            question="q",
            retrieved_chunks=[RetrievedChunk(doc_id="sources/a", rank=1)],
        ),
    ]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}, "q2": {"answer": ""}}, k_values=[1]
    )
    # 3 slots, 1 distinct doc -> overlap = 1 - 1/3 = 0.667
    assert agg["chunk_overlap_rate"] == pytest.approx(2 / 3)


def test_chunk_overlap_zero_for_empty_run():
    qrels: dict[str, dict[str, int]] = {}
    agg, _ = compute_retrieval_metrics(qrels, [], goldens_by_key={}, k_values=[1])
    assert agg["chunk_overlap_rate"] == 0.0
    assert agg["exact_match"] == 0.0


def test_exact_match_normalised_substring():
    qrels = {"q1": {"sources/a": 1}}
    responses = [_response(key="q1", chunk_ids=["sources/a"], answer="The Answer Is 42!")]
    goldens = {"q1": {"answer": "answer is 42"}}
    agg, _ = compute_retrieval_metrics(qrels, responses, goldens_by_key=goldens, k_values=[1])
    assert agg["exact_match"] == pytest.approx(1.0)


def test_exact_match_misses_when_answer_absent():
    qrels = {"q1": {"sources/a": 1}}
    responses = [_response(key="q1", chunk_ids=["sources/a"], answer="completely off topic")]
    goldens = {"q1": {"answer": "the right thing"}}
    agg, _ = compute_retrieval_metrics(qrels, responses, goldens_by_key=goldens, k_values=[1])
    assert agg["exact_match"] == pytest.approx(0.0)


def test_per_query_rows_carry_drill_down_fields():
    qrels = {"q1": {"sources/a": 1, "sources/b": 1}}
    responses = [_response(key="q1", chunk_ids=["sources/x", "sources/a"])]
    _, per_query = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}}, k_values=[1, 2]
    )
    assert per_query[0]["qa_pair_key"] == "q1"
    assert per_query[0]["n_retrieved"] == 2
    assert per_query[0]["n_relevant_retrieved"] == 1
    assert per_query[0]["first_relevant_rank"] == 2
    assert per_query[0]["hit_rate@1"] == 0  # rank 1 is 'sources/x'
    assert per_query[0]["hit_rate@2"] == 1


def test_no_queries_in_common_omits_per_k_metrics():
    qrels = {"q1": {"sources/a": 1}}
    # Response for a different qa_pair_key entirely.
    responses = [_response(key="q_other", chunk_ids=["sources/a"])]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}}, k_values=[1]
    )
    # No overlap -> per-k metrics undefined, NOT reported as 0.0 (misleading).
    assert "precision@1" not in agg
    assert "hit_rate@1" not in agg
    assert "mrr" not in agg
    # But the corpus-wide metrics still get computed.
    assert "chunk_overlap_rate" in agg
    assert "exact_match" in agg


def test_uses_chunk_score_for_ranking_when_provided():
    qrels = {"q1": {"sources/b": 1}}
    # Even though sources/a is rank 1 by the RAG system, we'll trust the score:
    # b has a higher score, so ranx should rank it first.
    responses = [
        RagResponse(
            system_name="rag_v1",
            qa_pair_key="q1",
            question="q",
            retrieved_chunks=[
                RetrievedChunk(doc_id="sources/a", rank=1, score=0.2),
                RetrievedChunk(doc_id="sources/b", rank=2, score=0.9),
            ],
        )
    ]
    agg, _ = compute_retrieval_metrics(
        qrels, responses, goldens_by_key={"q1": {"answer": ""}}, k_values=[2]
    )
    # b is the only relevant doc and gets the higher score -> MRR should be 1.0.
    assert agg["mrr"] == pytest.approx(1.0)
