"""Static-UI serving contract for the FastAPI service.

Builds a throwaway ``static/`` tree in a tmp dir and registers the UI routes
on a fresh app via :func:`mount_spa`, so the tests are deterministic and
independent of the real ``static/`` directory.

The critical BYOC property covered here is that relative asset URLs resolve
whether the UI is reached at the service root, at ``/ui`` or at ``/frontend``:
the browser sits behind ``/_service/uds/_db/<db>/<app>/``, and the container
only ever sees the path with that prefix stripped.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from multihop_eval.web.service import app as real_app
from multihop_eval.web.service import mount_spa

INDEX_HTML = "<!doctype html><html><body><div id='root'>UI-MARKER</div></body></html>"
STYLES_CSS = ":root { --bg: #fdf7df; }"
APP_JS = "export const marker = 'app-js';"

NO_CACHE = "no-cache, no-store, must-revalidate"


def _make_static(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "css").mkdir(parents=True)
    (root / "js" / "tabs").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (root / "css" / "styles.css").write_text(STYLES_CSS, encoding="utf-8")
    (root / "js" / "app.js").write_text(APP_JS, encoding="utf-8")
    (root / "js" / "tabs" / "run.js").write_text("export const t = 1;", encoding="utf-8")
    return root


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A fresh app with only the UI routes registered."""
    app = FastAPI()
    assert mount_spa(app, _make_static(tmp_path)) is True
    return TestClient(app)


def test_health_always_available() -> None:
    resp = TestClient(real_app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_mount_spa_returns_false_when_dir_missing(tmp_path: Path) -> None:
    assert mount_spa(FastAPI(), tmp_path / "does-not-exist") is False


def test_real_static_dir_is_served() -> None:
    """The shipped static/ tree must actually be wired up, not just present."""
    resp = TestClient(real_app).get("/")
    assert resp.status_code == 200
    assert "Multi-Hop Eval" in resp.text


@pytest.mark.parametrize("path", ["/", "/ui", "/ui/", "/frontend", "/frontend/"])
def test_index_served_with_no_cache(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200, path
    assert "UI-MARKER" in resp.text, path
    assert resp.headers["cache-control"] == NO_CACHE, path


@pytest.mark.parametrize(
    "path",
    [
        # Served at the service root, relative URLs land here.
        "/css/styles.css",
        # Served at /ui/ or /frontend/, they land under the prefix.
        "/ui/css/styles.css",
        "/frontend/css/styles.css",
    ],
)
def test_css_resolves_under_every_mount(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200, path
    assert "--bg" in resp.text, path
    assert resp.headers["content-type"].startswith("text/css"), path


@pytest.mark.parametrize(
    "path",
    ["/js/app.js", "/ui/js/app.js", "/frontend/js/app.js", "/js/tabs/run.js"],
)
def test_js_modules_resolve_under_every_mount(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200, path
    assert "export" in resp.text, path
    # ES modules are rejected by browsers unless served as a JavaScript type.
    assert "javascript" in resp.headers["content-type"], path


def test_static_assets_are_not_cached(client: TestClient) -> None:
    """Unhashed filenames mean a stale cached bundle would break the UI."""
    for path in ("/css/styles.css", "/js/app.js"):
        assert client.get(path).headers["cache-control"] == NO_CACHE, path


@pytest.mark.parametrize(
    "path", ["/frontend/some/client/route", "/ui/nope", "/not-a-real-path"]
)
def test_unknown_paths_fall_back_to_index(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200, path
    assert "UI-MARKER" in resp.text, path


@pytest.mark.parametrize(
    "path",
    [
        "/../pyproject.toml",
        "/ui/../../pyproject.toml",
        "/frontend/../../../etc/passwd",
    ],
)
def test_path_traversal_is_refused(client: TestClient, path: str) -> None:
    resp = client.get(path)
    # Either the client/router rejects the path outright, or we fall back to
    # the UI shell — never the file outside the static tree.
    assert resp.status_code in (200, 404), path
    if resp.status_code == 200:
        assert "UI-MARKER" in resp.text, path
        assert "[project]" not in resp.text, path


def test_head_requests_are_supported(client: TestClient) -> None:
    for path in ("/ui", "/frontend", "/css/styles.css"):
        assert client.head(path).status_code == 200, path


# ---------------------------------------------------------------------------
# The catch-all must not swallow the API surface
# ---------------------------------------------------------------------------


def test_unknown_api_paths_still_404_rather_than_serving_the_ui() -> None:
    """A typo'd API route must not silently return the UI shell with a 200."""
    resp = TestClient(real_app).get("/connection/does-not-exist")
    assert resp.status_code == 404
    assert "UI-MARKER" not in resp.text
    assert "<!doctype html" not in resp.text.lower()


@pytest.mark.parametrize("path", ["/health", "/connection/status", "/config"])
def test_api_routes_win_over_the_catch_all(path: str) -> None:
    resp = TestClient(real_app).get(path)
    assert resp.status_code == 200, path
    assert resp.headers["content-type"].startswith("application/json"), path
