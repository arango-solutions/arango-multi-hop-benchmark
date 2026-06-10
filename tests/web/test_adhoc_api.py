"""Ad-hoc router: config guard, happy path (fake evaluator), validation errors."""

from __future__ import annotations

from fastapi.testclient import TestClient

from multihop_eval.config import AppConfig
from multihop_eval.generation.adhoc import AdhocResult
from multihop_eval.web.routers import adhoc as adhoc_router
from multihop_eval.web.sessions import SESSION_HEADER, store

_REQUEST = {
    "question": "What links A and B?",
    "answer": "They both reference C.",
    "reasoning_chain": "A -> C <- B",
    "proof": [
        {"point": "A references C", "source_id": "sources/1"},
        {"point": "B references C", "source_id": "sources/2"},
    ],
    "sources": [
        {"_id": "sources/1", "content": "A talks about C."},
        {"_id": "sources/2", "content": "B talks about C."},
    ],
    "score_with_rubric": False,
}


def _configured_token(app_config: AppConfig) -> str:
    session = store.get_or_create(None)
    session.app_config = app_config
    return session.token


def test_evaluate_requires_config(client: TestClient) -> None:
    resp = client.post("/adhoc/evaluate", json=_REQUEST)
    assert resp.status_code == 409
    assert "Save a configuration" in resp.json()["detail"]


def test_evaluate_happy_path(client: TestClient, app_config: AppConfig, monkeypatch) -> None:
    class FakeEvaluator:
        def __init__(self, **_kwargs) -> None:  # noqa: ANN003
            pass

        def evaluate(self, **_kwargs) -> AdhocResult:  # noqa: ANN003
            return AdhocResult(
                multi_hop_pass=True,
                genuine_hop_count=2,
                multi_hop_reason="genuinely multi-hop",
                proof_verdict="pass",
                corrected_proof=[{"point": "A references C", "source_id": "sources/1"}],
            )

    monkeypatch.setattr(adhoc_router, "LLMClient", lambda cfg: object())
    monkeypatch.setattr(adhoc_router, "AdhocEvaluator", FakeEvaluator)

    token = _configured_token(app_config)
    resp = client.post("/adhoc/evaluate", json=_REQUEST, headers={SESSION_HEADER: token})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["multi_hop_pass"] is True
    assert body["proof_verdict"] == "pass"
    assert body["genuine_hop_count"] == 2


def test_evaluate_value_error_is_422(
    client: TestClient, app_config: AppConfig, monkeypatch
) -> None:
    class RaisingEvaluator:
        def __init__(self, **_kwargs) -> None:  # noqa: ANN003
            pass

        def evaluate(self, **_kwargs):  # noqa: ANN003
            raise ValueError("Need at least 2 source documents for multi-hop evaluation.")

    monkeypatch.setattr(adhoc_router, "LLMClient", lambda cfg: object())
    monkeypatch.setattr(adhoc_router, "AdhocEvaluator", RaisingEvaluator)

    token = _configured_token(app_config)
    bad = {**_REQUEST, "sources": [{"_id": "sources/1"}]}
    resp = client.post("/adhoc/evaluate", json=bad, headers={SESSION_HEADER: token})
    assert resp.status_code == 422
    assert "at least 2 source" in resp.json()["detail"]
