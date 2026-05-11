"""Tests for `multihop_eval.rag_eval.models`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multihop_eval.rag_eval.models import (
    RagEvalRun,
    RagMetricBundle,
    RagResponse,
    RetrievedChunk,
)


def test_retrieved_chunk_requires_positive_rank():
    with pytest.raises(ValidationError):
        RetrievedChunk(doc_id="sources/a", rank=0)


def test_retrieved_chunk_requires_doc_id():
    with pytest.raises(ValidationError):
        RetrievedChunk(doc_id="", rank=1)


def test_rag_response_sorts_chunks_by_rank():
    resp = RagResponse(
        system_name="rag_v1",
        qa_pair_key="abc123",
        question="why?",
        answer="because",
        retrieved_chunks=[
            RetrievedChunk(doc_id="sources/c", rank=3),
            RetrievedChunk(doc_id="sources/a", rank=1),
            RetrievedChunk(doc_id="sources/b", rank=2),
        ],
    )
    assert [c.rank for c in resp.retrieved_chunks] == [1, 2, 3]
    assert resp.retrieved_chunks[0].doc_id == "sources/a"


def test_rag_response_rejects_duplicate_ranks():
    with pytest.raises(ValidationError):
        RagResponse(
            system_name="rag_v1",
            qa_pair_key="abc",
            question="q",
            retrieved_chunks=[
                RetrievedChunk(doc_id="sources/a", rank=1),
                RetrievedChunk(doc_id="sources/b", rank=1),
            ],
        )


def test_rag_response_allows_empty_retrieval():
    resp = RagResponse(
        system_name="rag_v1", qa_pair_key="abc", question="q", retrieved_chunks=[]
    )
    assert resp.retrieved_chunks == []


def test_rag_response_requires_non_empty_keys():
    with pytest.raises(ValidationError):
        RagResponse(system_name="", qa_pair_key="abc", question="q")
    with pytest.raises(ValidationError):
        RagResponse(system_name="x", qa_pair_key="", question="q")


def test_rag_eval_run_duration_s_is_non_negative():
    run = RagEvalRun(system_name="rag_v1", n_responses=0)
    assert run.duration_s >= 0.0


def test_rag_metric_bundle_default_empty():
    b = RagMetricBundle()
    assert b.retrieval == {}
    assert b.generation == {}
    assert b.per_query == []
