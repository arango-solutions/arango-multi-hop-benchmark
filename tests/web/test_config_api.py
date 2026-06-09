"""Config router: defaults, save (with Arango creds from the live gateway),
secret redaction, and validation errors."""

from __future__ import annotations

from fastapi.testclient import TestClient

from multihop_eval.web.sessions import SESSION_HEADER

VALID_LLM = {
    "api_url": "https://api.openai.com/v1/chat/completions",
    "api_key": "sk-secret",
    "model": "gpt-4.1",
    "temperature": 0.3,
    "max_tokens": 4000,
    "timeout_s": 180,
    "retries": 3,
}

VALID_EVAL = {
    "target_clusters": ["cluster_0"],
    "n_questions": 5,
    "hop_dist": [2, 3],
    "hop_dist_weights": [0.7, 0.3],
    "max_verify_rounds": 3,
    "save_to_arango": True,
    "score_with_rubric": True,
    "personas": [{"label": "analyst", "instruction": "Write as an analyst asking a question."}],
    "rubric_fields": [
        {
            "name": "factuality",
            "description": "Is every claim supported by the cited documents?",
            "scale_min": 1,
            "scale_max": 5,
            "weight": 1.0,
        }
    ],
}


def test_get_config_returns_defaults(client: TestClient) -> None:
    resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved"] is None
    assert "sources_collection" in body["defaults"]["collections"]
    assert body["defaults"]["personas"]  # non-empty


def test_save_requires_connection(client: TestClient) -> None:
    resp = client.post(
        "/config",
        json={"collections": {}, "llm": VALID_LLM, "eval": VALID_EVAL},
    )
    assert resp.status_code == 409


def test_save_config_persists_and_redacts_secrets(
    client: TestClient, patch_gateway, connect_manual
) -> None:
    token = connect_manual(client)
    h = {SESSION_HEADER: token}
    resp = client.post(
        "/config",
        headers=h,
        json={
            "collections": {"sources_collection": "my_sources"},
            "llm": VALID_LLM,
            "eval": VALID_EVAL,
        },
    )
    assert resp.status_code == 200, resp.text
    saved = resp.json()["saved"]
    assert saved is not None
    # Credentials come from the live gateway; collection override applied.
    assert saved["arango"]["sources_collection"] == "my_sources"
    assert saved["arango"]["db"] == "ingest_bench_db"
    # Secrets must be redacted.
    assert saved["llm"]["api_key"] == "***"
    assert saved["arango"]["password"] == "***"

    # GET now returns the saved config too.
    again = client.get("/config", headers=h).json()
    assert again["saved"]["llm"]["model"] == "gpt-4.1"


def test_save_config_validation_error_is_422(
    client: TestClient, patch_gateway, connect_manual
) -> None:
    token = connect_manual(client)
    bad_eval = {**VALID_EVAL, "hop_dist_weights": [0.5, 0.4]}  # sums to 0.9
    resp = client.post(
        "/config",
        headers={SESSION_HEADER: token},
        json={"collections": {}, "llm": VALID_LLM, "eval": bad_eval},
    )
    assert resp.status_code == 422
    assert any("hop_dist_weights" in d for d in resp.json()["detail"])
