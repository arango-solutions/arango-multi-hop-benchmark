"""Tests for `multihop_eval.rag_eval.sources.arango_source`."""

from __future__ import annotations

from typing import Any

from multihop_eval.rag_eval.sources.arango_source import list_systems, load_responses


def _row(
    *,
    key: str,
    system: str,
    qa_key: str,
    question: str = "q",
    chunks: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "_key": key,
        "_id": f"rag_responses_v1/{key}",
        "_rev": "rev1",
        "system_name": system,
        "qa_pair_key": qa_key,
        "question": question,
        "answer": "a",
        "retrieved_chunks": chunks
        if chunks is not None
        else [{"doc_id": "sources/a", "rank": 1}],
    }


def test_load_all_responses(fake_arango):
    fake_arango.rag_responses["rag_responses_v1"] = [
        _row(key="rag_v1__q1", system="rag_v1", qa_key="q1"),
        _row(key="rag_v1__q2", system="rag_v1", qa_key="q2"),
    ]
    result = load_responses(fake_arango, "rag_responses_v1")
    assert result.success
    assert {r.qa_pair_key for r in result.responses} == {"q1", "q2"}


def test_filter_by_system_name(fake_arango):
    fake_arango.rag_responses["c"] = [
        _row(key="rag_v1__q1", system="rag_v1", qa_key="q1"),
        _row(key="rag_v2__q1", system="rag_v2", qa_key="q1"),
    ]
    result = load_responses(fake_arango, "c", system_name="rag_v2")
    assert len(result.responses) == 1
    assert result.responses[0].system_name == "rag_v2"


def test_filter_by_qa_keys(fake_arango):
    fake_arango.rag_responses["c"] = [
        _row(key="rag_v1__q1", system="rag_v1", qa_key="q1"),
        _row(key="rag_v1__q2", system="rag_v1", qa_key="q2"),
        _row(key="rag_v1__q3", system="rag_v1", qa_key="q3"),
    ]
    result = load_responses(fake_arango, "c", qa_keys=["q1", "q3"])
    assert {r.qa_pair_key for r in result.responses} == {"q1", "q3"}


def test_validation_errors_collected_not_raised(fake_arango):
    fake_arango.rag_responses["c"] = [
        _row(key="good", system="rag_v1", qa_key="q1"),
        # Invalid: blank system_name
        _row(key="bad", system="", qa_key="q2"),
    ]
    result = load_responses(fake_arango, "c")
    assert len(result.responses) == 1
    assert len(result.errors) == 1
    assert result.errors[0].arango_key == "bad"


def test_arango_internal_fields_stripped_before_validation(fake_arango):
    row = _row(key="rag_v1__q1", system="rag_v1", qa_key="q1")
    # Add a stray underscored field; the loader must drop it.
    row["_extra"] = "irrelevant"
    fake_arango.rag_responses["c"] = [row]
    result = load_responses(fake_arango, "c")
    assert result.success
    assert len(result.responses) == 1


def test_list_systems(fake_arango):
    fake_arango.rag_responses["c"] = [
        _row(key="a", system="rag_v1", qa_key="q1"),
        _row(key="b", system="rag_v2", qa_key="q1"),
        _row(key="c", system="rag_v1", qa_key="q2"),
    ]
    assert list_systems(fake_arango, "c") == ["rag_v1", "rag_v2"]


def test_empty_collection_returns_empty_result(fake_arango):
    result = load_responses(fake_arango, "missing")
    assert result.success
    assert result.responses == []
