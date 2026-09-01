"""Connection router: connect/disconnect/discovery against a fake gateway."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from multihop_eval.web.sessions import SESSION_HEADER

ARANGO_401 = "[HTTP 401][ERR 11] not authorized to execute this request"


@pytest.fixture
def refusing_gateway(patch_gateway):
    """Make the fake gateway reject the connection with Arango's own message."""
    patch_gateway.connection_error = ARANGO_401
    yield patch_gateway
    patch_gateway.connection_error = None


def _connect_body() -> dict[str, str]:
    return {
        "mode": "password",
        "host": "https://arango.example.com",
        "db": "ingest_bench_db",
        "username": "root",
        "password": "secret",
    }


def test_failed_connect_surfaces_the_real_arango_error(
    client: TestClient, refusing_gateway
) -> None:
    """Regression: the router used to replace the 401 with 'Ping failed'.

    That forced the user to read the server log to learn why the connection
    was rejected.
    """
    body = client.post("/connection/connect", json=_connect_body()).json()

    assert body["status"] == "error"
    assert body["error"] == ARANGO_401
    assert "Ping failed" not in body["error"]


def test_failed_test_endpoint_surfaces_the_real_arango_error(
    client: TestClient, patch_gateway, connect_manual
) -> None:
    token = connect_manual(client)
    # The credentials stop working after connecting (e.g. a rotated JWT).
    patch_gateway.connection_error = ARANGO_401
    try:
        body = client.post("/connection/test", headers={SESSION_HEADER: token}).json()
    finally:
        patch_gateway.connection_error = None

    assert body["status"] == "error"
    assert body["error"] == ARANGO_401


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
