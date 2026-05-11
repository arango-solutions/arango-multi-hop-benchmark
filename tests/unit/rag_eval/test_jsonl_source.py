"""Tests for `multihop_eval.rag_eval.sources.jsonl_source`."""

from __future__ import annotations

import json
from pathlib import Path

from multihop_eval.rag_eval.sources.jsonl_source import load_responses


def _ok_row(system: str = "rag_v1", key: str = "q1") -> dict:
    return {
        "system_name": system,
        "qa_pair_key": key,
        "question": "why?",
        "answer": "because",
        "retrieved_chunks": [
            {"doc_id": "sources/a", "rank": 1, "score": 0.9, "text": "..."},
            {"doc_id": "sources/b", "rank": 2, "score": 0.8, "text": "..."},
        ],
    }


def test_loads_valid_rows():
    lines = [json.dumps(_ok_row(key="q1")), json.dumps(_ok_row(key="q2"))]
    result = load_responses(lines)
    assert result.success
    assert len(result.responses) == 2
    assert result.responses[0].qa_pair_key == "q1"
    assert result.systems() == ["rag_v1"]


def test_skips_blank_lines():
    lines = [json.dumps(_ok_row()), "", "  ", "\n"]
    result = load_responses(lines)
    assert result.success
    assert len(result.responses) == 1


def test_collects_invalid_json_with_line_numbers():
    lines = [json.dumps(_ok_row()), "not json", json.dumps(_ok_row(key="q2"))]
    result = load_responses(lines)
    assert not result.success
    assert len(result.responses) == 2
    assert len(result.errors) == 1
    assert result.errors[0].line_number == 2
    assert "invalid JSON" in result.errors[0].message


def test_collects_validation_errors():
    bad = json.dumps({"system_name": "", "qa_pair_key": "q1", "question": "q"})
    lines = [bad]
    result = load_responses(lines)
    assert not result.success
    assert result.errors[0].line_number == 1
    assert "system_name" in result.errors[0].message


def test_rejects_non_object_lines():
    lines = [json.dumps(["array", "not", "object"])]
    result = load_responses(lines)
    assert not result.success
    assert "expected JSON object" in result.errors[0].message


def test_loads_from_file(tmp_path: Path):
    p = tmp_path / "responses.jsonl"
    p.write_text(
        "\n".join(json.dumps(_ok_row(key=k)) for k in ["q1", "q2", "q3"]) + "\n",
        encoding="utf-8",
    )
    result = load_responses(p)
    assert result.success
    assert {r.qa_pair_key for r in result.responses} == {"q1", "q2", "q3"}


def test_systems_dedupes_across_lines():
    lines = [
        json.dumps(_ok_row(system="rag_v1", key="q1")),
        json.dumps(_ok_row(system="rag_v2", key="q1")),
        json.dumps(_ok_row(system="rag_v1", key="q2")),
    ]
    result = load_responses(lines)
    assert result.systems() == ["rag_v1", "rag_v2"]


def test_empty_retrieval_is_valid():
    row = _ok_row()
    row["retrieved_chunks"] = []
    result = load_responses([json.dumps(row)])
    assert result.success
    assert result.responses[0].retrieved_chunks == []
