"""Tests for `multihop_eval.rag_eval.metrics.generation`."""

from __future__ import annotations

import pytest

from multihop_eval.rag_eval.metrics.generation import compute_generation_metrics
from multihop_eval.rag_eval.models import RagResponse, RetrievedChunk


def _resp(
    *,
    key: str,
    answer: str,
    chunks: list[tuple[str, str]] | None = None,
    chunk_score: float | None = None,
) -> RagResponse:
    """Build a `RagResponse` with chunk (doc_id, text) tuples."""
    chunks = chunks or []
    return RagResponse(
        system_name="rag_v1",
        qa_pair_key=key,
        question="q",
        answer=answer,
        retrieved_chunks=[
            RetrievedChunk(doc_id=doc_id, rank=i + 1, score=chunk_score, text=text)
            for i, (doc_id, text) in enumerate(chunks)
        ],
    )


def test_groundedness_full_when_sentence_quoted_verbatim():
    chunk_text = (
        "The capital of France is Paris. The Eiffel Tower opened in 1889 and "
        "stands on the Champ de Mars."
    )
    r = _resp(
        key="q1",
        answer="The capital of France is Paris. The Eiffel Tower opened in 1889.",
        chunks=[("sources/a", chunk_text)],
    )
    agg, per = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": ""}})
    assert agg["groundedness"] == pytest.approx(1.0)
    assert per[0]["grounded_sentences"] == 2
    assert per[0]["total_sentences"] == 2


def test_groundedness_zero_for_hallucination():
    r = _resp(
        key="q1",
        answer="Quantum widgets exhibit purple flavours under moonlight.",
        chunks=[("sources/a", "The capital of France is Paris.")],
    )
    agg, _ = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": ""}})
    assert agg["groundedness"] < 0.5


def test_groundedness_zero_for_empty_chunks():
    r = _resp(key="q1", answer="Anything goes.", chunks=[])
    agg, _ = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": ""}})
    assert agg["groundedness"] == 0.0


def test_groundedness_zero_for_empty_answer():
    r = _resp(key="q1", answer="", chunks=[("sources/a", "anything")])
    agg, _ = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": ""}})
    assert agg["groundedness"] == 0.0


def test_source_diversity_counts_distinct_doc_ids():
    r = _resp(
        key="q1",
        answer="some answer",
        chunks=[("sources/a", "t"), ("sources/b", "t"), ("sources/c", "t")],
    )
    agg, per = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": ""}})
    assert agg["source_diversity"] == pytest.approx(3.0)
    assert per[0]["source_diversity"] == 3


def test_citation_coverage_one_when_every_citation_retrieved():
    r = _resp(
        key="q1",
        answer="Foo bar [sources/a]. Baz [sources/b].",
        chunks=[("sources/a", "t"), ("sources/b", "t")],
    )
    agg, per = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": ""}})
    assert agg["citation_coverage"] == pytest.approx(1.0)
    assert per[0]["n_citations"] == 2


def test_citation_coverage_partial():
    r = _resp(
        key="q1",
        answer="Backed [sources/a]. Hallucinated [sources/nonexistent].",
        chunks=[("sources/a", "t")],
    )
    agg, _ = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": ""}})
    assert agg["citation_coverage"] == pytest.approx(0.5)


def test_no_citations_excluded_from_mean():
    # Two responses: one with two perfectly-covered citations, one with no
    # citations at all. The mean should equal the first response's coverage
    # (1.0), not be dragged down by the second.
    r1 = _resp(
        key="q1",
        answer="Backed [sources/a] [sources/b].",
        chunks=[("sources/a", "t"), ("sources/b", "t")],
    )
    r2 = _resp(
        key="q2", answer="Just text, no markers.", chunks=[("sources/c", "t")]
    )
    agg, _ = compute_generation_metrics(
        [r1, r2], goldens_by_key={"q1": {"answer": ""}, "q2": {"answer": ""}}
    )
    assert agg["citation_coverage"] == pytest.approx(1.0)


def test_length_anomaly_flags_outliers():
    # Nine medium-length answers, one extremely long outlier.
    responses = [
        _resp(key=f"q{i}", answer="a sentence of typical length.")
        for i in range(9)
    ]
    responses.append(_resp(key="q9", answer="x" * 5000))
    goldens = {r.qa_pair_key: {"answer": ""} for r in responses}
    agg, per = compute_generation_metrics(responses, goldens_by_key=goldens)
    assert agg["length_anomaly_rate"] > 0.0
    assert per[-1]["is_length_anomaly"] is True
    assert per[0]["is_length_anomaly"] is False


def test_length_anomaly_zero_for_uniform_answers():
    responses = [
        _resp(key=f"q{i}", answer="every answer the same length.") for i in range(5)
    ]
    goldens = {r.qa_pair_key: {"answer": ""} for r in responses}
    agg, _ = compute_generation_metrics(responses, goldens_by_key=goldens)
    assert agg["length_anomaly_rate"] == 0.0


def test_rouge_l_high_for_similar_answers():
    r = _resp(key="q1", answer="The quick brown fox jumps over the lazy dog.")
    goldens = {"q1": {"answer": "The quick brown fox jumped over the lazy dog."}}
    agg, _ = compute_generation_metrics([r], goldens_by_key=goldens)
    assert agg["rouge_l_f1"] > 0.7


def test_rouge_l_zero_for_disjoint_answers():
    r = _resp(key="q1", answer="completely unrelated text here")
    goldens = {"q1": {"answer": "different non overlapping content entirely"}}
    agg, _ = compute_generation_metrics([r], goldens_by_key=goldens)
    assert agg["rouge_l_f1"] == pytest.approx(0.0)


def test_empty_retrieval_rate_default_uses_chunk_presence():
    r1 = _resp(key="q1", answer="a", chunks=[("sources/a", "t")])
    r2 = _resp(key="q2", answer="b", chunks=[])
    agg, per = compute_generation_metrics(
        [r1, r2], goldens_by_key={"q1": {"answer": ""}, "q2": {"answer": ""}}
    )
    assert agg["empty_retrieval_rate"] == pytest.approx(0.5)
    assert per[0]["is_empty_retrieval"] is False
    assert per[1]["is_empty_retrieval"] is True


def test_empty_retrieval_rate_honours_min_score():
    r1 = _resp(key="q1", answer="a", chunks=[("sources/a", "t")], chunk_score=0.9)
    r2 = _resp(key="q2", answer="b", chunks=[("sources/b", "t")], chunk_score=0.1)
    agg, _ = compute_generation_metrics(
        [r1, r2],
        goldens_by_key={"q1": {"answer": ""}, "q2": {"answer": ""}},
        empty_retrieval_min_score=0.5,
    )
    # Only r2's top score is below 0.5, so it's treated as empty.
    assert agg["empty_retrieval_rate"] == pytest.approx(0.5)


def test_empty_input_returns_zero_metrics():
    agg, per = compute_generation_metrics([], goldens_by_key={})
    assert per == []
    for value in agg.values():
        assert value == 0.0


def test_per_query_row_shape():
    r = _resp(key="q1", answer="hello [sources/a].", chunks=[("sources/a", "t")])
    _, per = compute_generation_metrics([r], goldens_by_key={"q1": {"answer": "hello"}})
    row = per[0]
    for field in (
        "qa_pair_key",
        "groundedness",
        "grounded_sentences",
        "total_sentences",
        "source_diversity",
        "citation_coverage",
        "n_citations",
        "answer_length",
        "length_z",
        "is_length_anomaly",
        "rouge_l_f1",
        "is_empty_retrieval",
    ):
        assert field in row
