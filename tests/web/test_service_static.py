"""Static SPA-serving contract for the FastAPI service.

Builds a throwaway ``ui/dist`` in a tmp dir and registers the SPA routes on a
fresh app via :func:`mount_spa`, so the test is deterministic regardless of
whether the real frontend has been built.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from multihop_eval.web.service import app as real_app
from multihop_eval.web.service import mount_spa

INDEX_HTML = "<!doctype html><html><body><div id='root'>SPA-MARKER</div></body></html>"


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log('hi')", encoding="utf-8")
    return dist


def _client_with_spa(dist: Path) -> TestClient:
    app = FastAPI()
    assert mount_spa(app, dist) is True
    return TestClient(app)


def test_health_always_available() -> None:
    resp = TestClient(real_app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_mount_spa_returns_false_when_dir_missing(tmp_path: Path) -> None:
    assert mount_spa(FastAPI(), tmp_path / "does-not-exist") is False


def test_frontend_serves_index_with_no_cache(tmp_path: Path) -> None:
    client = _client_with_spa(_make_dist(tmp_path))
    for path in ("/frontend", "/frontend/", "/ui", "/ui/", "/"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "SPA-MARKER" in resp.text, path
        assert resp.headers["cache-control"] == "no-cache, no-store, must-revalidate"


def test_frontend_spa_fallback_for_unknown_route(tmp_path: Path) -> None:
    client = _client_with_spa(_make_dist(tmp_path))
    resp = client.get("/frontend/some/client/route")
    assert resp.status_code == 200
    assert "SPA-MARKER" in resp.text


def test_assets_served_immutable(tmp_path: Path) -> None:
    client = _client_with_spa(_make_dist(tmp_path))
    resp = client.get("/assets/index-abc123.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
