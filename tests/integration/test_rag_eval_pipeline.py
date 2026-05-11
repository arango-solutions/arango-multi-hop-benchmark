"""End-to-end test for `RagEvalOrchestrator` with two fake RAG systems.

We hand-build a small golden set with deterministic proof_lists, plus two
"systems" (one accurate, one weak), and verify that:

* The orchestrator produces one `RagEvalRun` per system_name.
* The accurate system wins on retrieval metrics (precision, recall, NDCG).
* Both retrieval and generation metric bundles are populated.
* Per-query rows are merged across the two metric modules.
"""

from __future__ import annotations

import json

from multihop_eval.config import RagEvalConfig
from multihop_eval.rag_eval.models import RagResponse, RetrievedChunk
from multihop_eval.rag_eval.pipeline import RagEvalOrchestrator


def _golden(key: str, proof_source_ids: list[str], answer: str = "ground truth") -> dict:
    return {
        "_key": key,
        "question": f"why {key}?",
        "answer": answer,
        "proof": [{"point": f"point {sid}", "source_id": sid} for sid in proof_source_ids],
    }


def _accurate_response(key: str, doc_ids: list[str], answer: str) -> RagResponse:
    """Returns the relevant docs first, with high scores."""
    return RagResponse(
        system_name="rag_accurate",
        qa_pair_key=key,
        question=f"why {key}?",
        answer=answer,
        retrieved_chunks=[
            RetrievedChunk(
                doc_id=d, rank=i + 1, score=0.9 - i * 0.1, text="supporting text " + d
            )
            for i, d in enumerate(doc_ids)
        ],
    )


def _weak_response(key: str, decoy_ids: list[str], answer: str) -> RagResponse:
    """Returns irrelevant docs with mediocre scores."""
    return RagResponse(
        system_name="rag_weak",
        qa_pair_key=key,
        question=f"why {key}?",
        answer=answer,
        retrieved_chunks=[
            RetrievedChunk(doc_id=d, rank=i + 1, score=0.4, text="unrelated text")
            for i, d in enumerate(decoy_ids)
        ],
    )


def test_two_systems_produce_two_runs_with_orderable_metrics():
    goldens = [
        _golden("q1", ["sources/a", "sources/b"], answer="paris is the capital"),
        _golden("q2", ["sources/c", "sources/d"], answer="eiffel opened 1889"),
        _golden("q3", ["sources/e", "sources/f"], answer="seine flows through paris"),
    ]
    accurate = [
        _accurate_response("q1", ["sources/a", "sources/b"], "Paris is the capital."),
        _accurate_response("q2", ["sources/c", "sources/d"], "Eiffel opened in 1889."),
        _accurate_response("q3", ["sources/e", "sources/f"], "The Seine flows through Paris."),
    ]
    weak = [
        _weak_response("q1", ["sources/x", "sources/y"], "I don't know."),
        _weak_response("q2", ["sources/z"], "Something off topic."),
        _weak_response("q3", ["sources/w", "sources/v"], "More irrelevant text."),
    ]

    orchestrator = RagEvalOrchestrator(RagEvalConfig(k_values=[1, 3]))
    runs = orchestrator.evaluate(goldens, accurate + weak)

    # Two systems, sorted alphabetically.
    assert [r.system_name for r in runs] == ["rag_accurate", "rag_weak"]

    accurate_run = runs[0]
    weak_run = runs[1]

    # Both systems answered every golden.
    assert accurate_run.n_responses == 3
    assert accurate_run.n_matched_goldens == 3
    assert weak_run.n_responses == 3

    # Accurate beats weak on every key retrieval metric.
    assert accurate_run.metrics.retrieval["precision@3"] > weak_run.metrics.retrieval["precision@3"]
    assert accurate_run.metrics.retrieval["recall@3"] > weak_run.metrics.retrieval["recall@3"]
    assert accurate_run.metrics.retrieval["ndcg@3"] > weak_run.metrics.retrieval["ndcg@3"]
    assert accurate_run.metrics.retrieval["mrr"] > weak_run.metrics.retrieval["mrr"]
    assert accurate_run.metrics.retrieval["hit_rate@1"] >= weak_run.metrics.retrieval["hit_rate@1"]
    assert accurate_run.metrics.retrieval["exact_match"] >= weak_run.metrics.retrieval["exact_match"]


def test_per_query_rows_merge_retrieval_and_generation():
    goldens = [_golden("q1", ["sources/a"], answer="x")]
    responses = [_accurate_response("q1", ["sources/a"], "x")]
    runs = RagEvalOrchestrator(RagEvalConfig(k_values=[1])).evaluate(goldens, responses)
    assert len(runs) == 1
    row = runs[0].metrics.per_query[0]
    # Field from retrieval module:
    assert "first_relevant_rank" in row
    assert "precision@1" in row
    # Field from generation module:
    assert "groundedness" in row
    assert "rouge_l_f1" in row


def test_orchestrator_ignores_responses_with_no_matching_golden():
    goldens = [_golden("q1", ["sources/a"])]
    # System returns a response for q1 (matches) AND for q_phantom (no golden).
    responses = [
        _accurate_response("q1", ["sources/a"], "x"),
        _accurate_response("q_phantom", ["sources/q"], "x"),
    ]
    runs = RagEvalOrchestrator(RagEvalConfig(k_values=[1])).evaluate(goldens, responses)
    assert runs[0].n_responses == 2
    assert runs[0].n_matched_goldens == 1


def test_orchestrator_load_responses_from_jsonl_lines():
    cfg = RagEvalConfig(response_source="jsonl")
    line = json.dumps(
        {
            "system_name": "rag_v1",
            "qa_pair_key": "q1",
            "question": "q?",
            "answer": "a",
            "retrieved_chunks": [{"doc_id": "sources/a", "rank": 1}],
        }
    )
    orch = RagEvalOrchestrator(cfg)
    responses = orch.load_responses(jsonl_lines=[line])
    assert len(responses) == 1
    assert responses[0].system_name == "rag_v1"


def test_orchestrator_load_responses_from_arango(fake_arango):
    cfg = RagEvalConfig(response_source="arango", response_arango_collection="rag_responses_v1")
    fake_arango.rag_responses["rag_responses_v1"] = [
        {
            "_key": "rag_v1__q1",
            "system_name": "rag_v1",
            "qa_pair_key": "q1",
            "question": "q?",
            "answer": "a",
            "retrieved_chunks": [{"doc_id": "sources/a", "rank": 1}],
        }
    ]
    orch = RagEvalOrchestrator(cfg)
    responses = orch.load_responses(arango_gateway=fake_arango)
    assert len(responses) == 1


def test_orchestrator_system_filter_drops_unwanted_systems():
    cfg = RagEvalConfig(response_source="jsonl", system_filter=["rag_v1"])
    rows = [
        json.dumps({"system_name": "rag_v1", "qa_pair_key": "q1", "question": "q?"}),
        json.dumps({"system_name": "rag_v2", "qa_pair_key": "q1", "question": "q?"}),
    ]
    orch = RagEvalOrchestrator(cfg)
    responses = orch.load_responses(jsonl_lines=rows)
    assert [r.system_name for r in responses] == ["rag_v1"]


def test_orchestrator_jsonl_requires_input_source():
    import pytest

    with pytest.raises(ValueError, match="jsonl_path or jsonl_lines"):
        RagEvalOrchestrator(RagEvalConfig(response_source="jsonl")).load_responses()


def test_orchestrator_arango_requires_gateway():
    import pytest

    with pytest.raises(ValueError, match="arango_gateway"):
        RagEvalOrchestrator(RagEvalConfig(response_source="arango")).load_responses()


def test_no_responses_yields_no_runs():
    goldens = [_golden("q1", ["sources/a"])]
    runs = RagEvalOrchestrator(RagEvalConfig(k_values=[1])).evaluate(goldens, [])
    assert runs == []
