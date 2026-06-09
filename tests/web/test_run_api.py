"""Run router: start/stop/status guards + SSE streaming with a fake runner."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from multihop_eval.config import AppConfig
from multihop_eval.generation.models import RunEvent, RunResult
from multihop_eval.web import sessions
from multihop_eval.web.routers import run as run_router
from multihop_eval.web.sessions import SESSION_HEADER, STATUS_CONNECTED_MANUAL, store


def _result() -> RunResult:
    now = datetime.now(UTC)
    return RunResult(
        accepted=[],
        rejected=[],
        cluster_targets={"cluster_0": 1},
        cluster_achieved={"cluster_0": 0},
        started_at=now,
        finished_at=now,
    )


@pytest.fixture
def connected_token(app_config: AppConfig) -> str:
    """A session that is connected and has a saved config (no real gateway)."""
    session = store.get_or_create(None)
    session.conn_status = STATUS_CONNECTED_MANUAL
    session.gateway = object()  # presence not used; is_connected() checks status
    session.app_config = app_config
    return session.token


def test_start_requires_config(client: TestClient) -> None:
    # Fresh session: no config, not connected → 409.
    assert client.post("/run/start").status_code == 409


def test_start_requires_connection(client: TestClient, app_config: AppConfig) -> None:
    session = store.get_or_create(None)
    session.app_config = app_config  # config but not connected
    resp = client.post("/run/start", headers={SESSION_HEADER: session.token})
    assert resp.status_code == 409
    assert "Connect to ArangoDB" in resp.json()["detail"]


def test_start_status_and_sse_stream(
    client: TestClient, connected_token: str, monkeypatch
) -> None:
    def fake_runner(cfg, on_event, control):  # noqa: ANN001, ARG001
        on_event(
            RunEvent(
                kind="accepted",
                payload={"hop_count": 2, "persona": "analyst", "accepted": 1, "target": 1, "question": "q?"},
            )
        )
        return _result()

    monkeypatch.setattr(run_router, "build_runner", lambda cfg: fake_runner)

    h = {SESSION_HEADER: connected_token}
    start = client.post("/run/start", headers=h)
    assert start.status_code == 200, start.text

    # Let the (fast) worker finish.
    for _ in range(50):
        status = client.get("/run/status", headers=h).json()
        if status["status"] in {"done", "stopped", "error"}:
            break
        time.sleep(0.05)
    assert status["status"] == "done"

    # SSE replays the queued event(s) then a terminal status event.
    resp = client.get("/run/events", params={"session": connected_token})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "ACCEPTED" in resp.text
    assert '"kind": "status"' in resp.text


def test_double_start_is_conflict(
    client: TestClient, connected_token: str, monkeypatch
) -> None:
    release = threading.Event()

    def blocking_runner(cfg, on_event, control):  # noqa: ANN001, ARG001
        on_event(RunEvent(kind="tick", payload={}))
        release.wait(timeout=5)
        return _result()

    monkeypatch.setattr(run_router, "build_runner", lambda cfg: blocking_runner)

    h = {SESSION_HEADER: connected_token}
    assert client.post("/run/start", headers=h).status_code == 200
    # A second start while the first is still running → 409.
    second = client.post("/run/start", headers=h)
    assert second.status_code == 409
    assert "already in progress" in second.json()["detail"]

    # Release and let it wind down so the daemon thread doesn't linger.
    release.set()
    session = sessions.store.get(connected_token)
    assert session is not None and session.run is not None
    session.run.thread.join(timeout=5)  # type: ignore[union-attr]


def test_stop_without_run_is_conflict(client: TestClient) -> None:
    assert client.post("/run/stop").status_code == 409
