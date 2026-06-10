"""Shared fixtures for the web-API tests.

These swap the real :class:`ArangoGateway` (which would open a live socket) for
an in-memory fake, and reset the process-wide session store between tests so
state never leaks across cases.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from multihop_eval.clients.arango_gateway import CollectionInfo
from multihop_eval.web import service, sessions
from multihop_eval.web.routers import connection as connection_router
from multihop_eval.web.sessions import (
    SESSION_HEADER,
    STATUS_CONNECTED_MANUAL,
)


class FakeGateway:
    """Mimics the ArangoGateway surface the connection/config routers touch."""

    def __init__(self, config, *, client=None) -> None:  # noqa: ARG002 - signature parity
        self.config = config

    def ping(self) -> bool:
        return True

    def list_databases(self) -> list[str]:
        return ["_system", "ingest_bench_db"]

    def list_collections(self, *, include_system: bool = False) -> list[CollectionInfo]:  # noqa: ARG002
        return [
            CollectionInfo(name="multihop_eval_sources", doc_count=120, kind="document", system=False),
            CollectionInfo(name="multihop_eval_domains", doc_count=3, kind="document", system=False),
        ]

    def list_cluster_ids(self, domains_collection: str) -> list[str]:  # noqa: ARG002
        return ["cluster_0", "cluster_1"]


@pytest.fixture(autouse=True)
def _clean_sessions():
    sessions.store.clear()
    yield
    sessions.store.clear()


@pytest.fixture
def patch_gateway(monkeypatch) -> type[FakeGateway]:
    monkeypatch.setattr(connection_router, "ArangoGateway", FakeGateway)
    return FakeGateway


@pytest.fixture
def client() -> TestClient:
    return TestClient(service.app)


@pytest.fixture
def fake_arango_with_qa(fake_arango):
    """A connected session whose gateway has one persisted QA row; yields token."""
    fake_arango.insert_qa_row(
        {
            "cluster_id": "cluster_0",
            "partition_id": "p0",
            "hop_count": 3,
            "persona": "analyst",
            "reasoning_chain": "a -> b -> c",
            "question": "Persisted question?",
            "answer": "Persisted answer.",
            "proof": "- [sources/1]\n  point",
            "rubric_scores": {"factuality": {"score": 5, "justification": "great"}},
            "rubric_weighted_score": 5.0,
        }
    )
    session = sessions.store.get_or_create(None)
    session.gateway = fake_arango
    session.conn_status = STATUS_CONNECTED_MANUAL
    return session.token


@pytest.fixture
def connect_manual():
    """Return a helper that connects in password mode and yields the token."""

    def _connect(client: TestClient) -> str:
        resp = client.post(
            "/connection/connect",
            json={
                "mode": "password",
                "host": "https://arango.example.com",
                "db": "ingest_bench_db",
                "username": "root",
                "password": "secret",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "connected_manual"
        token = resp.headers[SESSION_HEADER]
        assert token
        return token

    return _connect
