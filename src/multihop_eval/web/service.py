"""FastAPI application: serves the static UI and the JSON API.

Architecture (mirrors the arango-cypher BYOC reference):

* API routes live at the container root (``/connection/*``, ``/config/*``,
  ``/run/*``, ``/health``).
* The no-build UI in ``static/`` is served at ``/`` (the BYOC service root),
  ``/frontend`` (the AMP proxy target) and ``/ui`` (local-dev convenience).
  Explicit route handlers are used instead of ``StaticFiles`` mounts so the
  AMP proxy doesn't trip over Starlette's trailing-slash 307 redirect.
* A catch-all registered *after* every API router resolves ``css/`` and
  ``js/`` when the UI is served at the service root, where relative asset
  URLs land on ``/css/styles.css`` rather than under a ``/ui`` prefix.

The platform proxy prefix (``/_service/uds/_global/<name>/``) is handled in
the browser (relative URLs + ``apiBase()``), so the container always sees
clean root paths.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

from multihop_eval.logging_setup import configure_logging
from multihop_eval.web.routers import adhoc as adhoc_router
from multihop_eval.web.routers import config as config_router
from multihop_eval.web.routers import connection as connection_router
from multihop_eval.web.routers import dashboard as dashboard_router
from multihop_eval.web.routers import rag_eval as rag_eval_router
from multihop_eval.web.routers import run as run_router

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(
    title="Multi-Hop Eval",
    description="Multi-hop QA dataset generation, validation, and evaluation.",
    version="1.0.0",
    root_path=os.getenv("ROOT_PATH", ""),
)

app.include_router(connection_router.router)
app.include_router(config_router.router)
app.include_router(run_router.router)
app.include_router(dashboard_router.router)
app.include_router(adhoc_router.router)
app.include_router(rag_eval_router.router)


@app.get("/health", include_in_schema=False)
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Static UI serving
# ---------------------------------------------------------------------------

_UI_DIR = Path(__file__).resolve().parents[3] / "static"
# Nothing in ``static/`` is content-hashed, so a stale cached script paired
# with a fresh index.html would silently break the UI after a redeploy.
_NO_CACHE = "no-cache, no-store, must-revalidate"

_SPA_PREFIXES = ("/ui", "/frontend")


def _api_prefixes(target_app: FastAPI) -> frozenset[str]:
    """First path segment of every route registered so far.

    Called before the SPA routes are added, so the result is exactly the API
    surface. The catch-all uses it to keep returning 404 for unknown API
    paths instead of silently answering them with the UI shell.
    """
    heads = set()
    for route in target_app.routes:
        path = getattr(route, "path", "")
        head = path.strip("/").split("/", 1)[0]
        if head and "{" not in head:
            heads.add(head)
    return frozenset(heads)


def mount_spa(target_app: FastAPI, ui_dir: Path) -> bool:
    """Register routes that serve ``ui_dir`` at ``/``, ``/ui`` and ``/frontend``.

    Explicit route handlers are used instead of a ``StaticFiles`` mount so the
    AMP proxy never trips over Starlette's trailing-slash 307 redirect. Returns
    ``True`` when the routes were registered (i.e. ``ui_dir`` exists), so the
    caller / tests can assert the UI is being served.
    """
    if not ui_dir.is_dir():
        return False

    ui_dir = ui_dir.resolve()
    api_prefixes = _api_prefixes(target_app)

    def index_response() -> FileResponse:
        return FileResponse(ui_dir / "index.html", headers={"Cache-Control": _NO_CACHE})

    def serve(relative_path: str) -> Response:
        file = (ui_dir / relative_path).resolve()
        # Guard against path traversal escaping the UI directory.
        if ui_dir in file.parents and file.is_file():
            return FileResponse(file, headers={"Cache-Control": _NO_CACHE})
        return index_response()

    @target_app.get("/", include_in_schema=False)
    def _root_index() -> FileResponse:
        return index_response()

    def spa_index() -> FileResponse:
        return index_response()

    def spa_asset(full_path: str) -> Response:
        return serve(full_path)

    for prefix in _SPA_PREFIXES:
        for path in (prefix, f"{prefix}/"):
            target_app.add_api_route(
                path, spa_index, methods=["GET", "HEAD"], include_in_schema=False
            )
        target_app.add_api_route(
            f"{prefix}/{{full_path:path}}",
            spa_asset,
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )

    # Registered last so every API route wins. This is what makes relative
    # asset URLs work when the UI is served at the service root.
    @target_app.api_route(
        "/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False
    )
    def _root_spa(full_path: str) -> Response:
        if full_path.split("/", 1)[0] in api_prefixes:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return serve(full_path)

    return True


mount_spa(app, _UI_DIR)
