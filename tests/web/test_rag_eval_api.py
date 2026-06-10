"""RAG-eval router: connection guard, JSONL evaluation, export, validation."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from multihop_eval.web.sessions import SESSION_HEADER, STATUS_CONNECTED_MANUAL, store


def _connected_with_goldens(fake_arango) -> str:
    # Two goldens whose proof_list keys drive qrels.
    fake_arango.insert_qa_row(
        {
            "_key": "g1",
            "question": "q1",
            "proof_list": [{"point": "p", "source_id": "sources/1"}],
        }
    )
    fake_arango.insert_qa_row(
        {
            "_key": "g2",
            "question": "q2",
            "proof_list": [{"point": "p", "source_id": "sources/2"}],
        }
    )
    session = store.get_or_create(None)
    session.gateway = fake_arango
    session.conn_status = STATUS_CONNECTED_MANUAL
    return session.token


def _jsonl(*rows: dict) -> str:
    return "\n".join(json.dumps(r) for r in rows)


def test_evaluate_requires_connection(client: TestClient) -> None:
    resp = client.post("/rag_eval/evaluate", json={"response_source": "jsonl", "jsonl_text": ""})
    assert resp.status_code == 409


def test_evaluate_jsonl_missing_text_is_422(client: TestClient, fake_arango) -> None:
    token = _connected_with_goldens(fake_arango)
    resp = client.post(
        "/rag_eval/evaluate",
        json={"response_source": "jsonl"},
        headers={SESSION_HEADER: token},
    )
    assert resp.status_code == 422


def test_evaluate_jsonl_happy_path(client: TestClient, fake_arango) -> None:
    token = _connected_with_goldens(fake_arango)
    jsonl_text = _jsonl(
        {
            "system_name": "sys_a",
            "qa_pair_key": "g1",
            "question": "q1",
            "answer": "a1",
            "retrieved_chunks": [{"doc_id": "sources/1", "rank": 1}],
        },
        {
            "system_name": "sys_a",
            "qa_pair_key": "g2",
            "question": "q2",
            "answer": "a2",
            "retrieved_chunks": [{"doc_id": "sources/2", "rank": 1}],
        },
        # An invalid row to confirm errors are surfaced, not fatal.
        {"system_name": "sys_a", "question": "missing key"},
    )
    resp = client.post(
        "/rag_eval/evaluate",
        json={"response_source": "jsonl", "jsonl_text": jsonl_text},
        headers={SESSION_HEADER: token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_goldens"] == 2
    assert body["n_responses"] == 2
    assert body["n_systems"] == 1
    assert body["runs"][0]["system_name"] == "sys_a"
    assert len(body["load_errors"]) == 1


def test_export_requires_prior_run(client: TestClient) -> None:
    assert client.get("/rag_eval/export").status_code == 409


def test_export_after_run(client: TestClient, fake_arango) -> None:
    token = _connected_with_goldens(fake_arango)
    h = {SESSION_HEADER: token}
    jsonl_text = _jsonl(
        {
            "system_name": "sys_a",
            "qa_pair_key": "g1",
            "question": "q1",
            "answer": "a1",
            "retrieved_chunks": [{"doc_id": "sources/1", "rank": 1}],
        }
    )
    started = client.post(
        "/rag_eval/evaluate",
        json={"response_source": "jsonl", "jsonl_text": jsonl_text},
        headers=h,
    )
    assert started.status_code == 200, started.text

    js = client.get("/rag_eval/export", params={"fmt": "json"}, headers=h)
    assert js.status_code == 200
    assert "sys_a" in js.json()

    xl = client.get("/rag_eval/export", params={"fmt": "excel"}, headers=h)
    assert xl.status_code == 200
    assert xl.content[:2] == b"PK"


def test_evaluate_invalid_relevance_mode_is_422(client: TestClient, fake_arango) -> None:
    token = _connected_with_goldens(fake_arango)
    resp = client.post(
        "/rag_eval/evaluate",
        json={"response_source": "jsonl", "jsonl_text": "{}", "relevance_mode": "bogus"},
        headers={SESSION_HEADER: token},
    )
    assert resp.status_code == 422
