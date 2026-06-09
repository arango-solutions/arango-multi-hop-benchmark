"""Connection router: connect/disconnect/discovery against a fake gateway."""

from __future__ import annotations

from fastapi.testclient import TestClient

from multihop_eval.web.sessions import SESSION_HEADER


def test_connect_password_mode_succeeds(client: TestClient, patch_gateway, connect_manual) -> None:
    token = connect_manual(client)
    # Re-using the token returns the same connected session.
    status = client.get("/connection/status", headers={SESSION_HEADER: token}).json()
    assert status["status"] == "connected_manual"
    assert status["db"] == "ingest_bench_db"


def test_connect_password_mode_requires_host(client: TestClient, patch_gateway) -> None:
    resp = client.post("/connection/connect", json={"mode": "password", "db": "x"})
    assert resp.status_code == 400
    assert "host is required" in resp.json()["detail"]


def test_databases_collections_clusters(client: TestClient, patch_gateway, connect_manual) -> None:
    token = connect_manual(client)
    h = {SESSION_HEADER: token}

    dbs = client.get("/connection/databases", headers=h).json()
    assert dbs["databases"] == ["_system", "ingest_bench_db"]

    cols = client.get("/connection/collections", headers=h).json()
    names = [c["name"] for c in cols["collections"]]
    assert "multihop_eval_sources" in names
    assert cols["collections"][0]["doc_count"] == 120

    clusters = client.get(
        "/connection/clusters",
        params={"domains_collection": "multihop_eval_domains"},
        headers=h,
    ).json()
    assert clusters["clusters"] == ["cluster_0", "cluster_1"]


def test_discovery_requires_connection(client: TestClient, patch_gateway) -> None:
    # Fresh session (no connect) → 409 from _require_gateway.
    resp = client.get("/connection/databases")
    assert resp.status_code == 409


def test_disconnect_clears_state(client: TestClient, patch_gateway, connect_manual) -> None:
    token = connect_manual(client)
    h = {SESSION_HEADER: token}
    resp = client.post("/connection/disconnect", headers=h)
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"
    # Discovery now fails because the gateway is gone.
    assert client.get("/connection/databases", headers=h).status_code == 409
