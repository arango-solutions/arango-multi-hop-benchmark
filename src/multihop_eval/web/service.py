"""FastAPI application: serves the React/Vite SPA and the JSON API.

Architecture (mirrors the arango-cypher BYOC reference):

* API routes live at the container root (``/connection/*``, ``/config/*``,
  ``/run/*``, ``/health``).
* The built SPA in ``ui/dist`` is served at ``/frontend`` (the AMP/BYOC proxy
  target) and ``/ui`` (local-dev convenience) with an SPA fallback. Explicit
  route handlers are used instead of ``StaticFiles`` mounts so the AMP proxy
  doesn't trip over Starlette's trailing-slash 307 redirect.
* Hashed Vite assets are served at ``/assets`` for builds that emit absolute
  asset URLs.

The platform proxy prefix (``/_service/uds/_global/<name>/``) is handled in
the browser (Vite ``base: "./"`` + ``apiBase()``), so the container always
sees clean root paths.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from multihop_eval.logging_setup import configure_logging
from multihop_eval.web.routers import config as config_router
from multihop_eval.web.routers import connection as connection_router
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


@app.get("/health", include_in_schema=False)
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Static SPA serving (only when ui/dist has been built)
# ---------------------------------------------------------------------------

_UI_DIR = Path(__file__).resolve().parents[3] / "ui" / "dist"
_HTML_NO_CACHE = "no-cache, no-store, must-revalidate"
_ASSET_IMMUTABLE = "public, max-age=31536000, immutable"


class _ImmutableAssets(StaticFiles):
    """StaticFiles that marks hashed assets immutable for a year."""

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = _ASSET_IMMUTABLE
        return resp


def mount_spa(target_app: FastAPI, ui_dir: Path) -> bool:
    """Register SPA routes that serve ``ui_dir`` at ``/``, ``/ui``, ``/frontend``.

    Explicit route handlers are used instead of a ``StaticFiles`` mount so the
    AMP proxy never trips over Starlette's trailing-slash 307 redirect. Returns
    ``True`` when the routes were registered (i.e. ``ui_dir`` exists), so the
    caller / tests can assert the SPA is being served.
    """
    if not ui_dir.is_dir():
        return False

    def index_response() -> FileResponse:
        return FileResponse(ui_dir / "index.html", headers={"Cache-Control": _HTML_NO_CACHE})

    def spa_serve(full_path: str) -> Response:
        file = (ui_dir / full_path).resolve()
        # Guard against path traversal escaping the dist dir.
        if ui_dir in file.parents and file.is_file():
            headers = {"Cache-Control": _HTML_NO_CACHE} if file.suffix == ".html" else None
            return FileResponse(file, headers=headers) if headers else FileResponse(file)
        return index_response()

    @target_app.get("/", include_in_schema=False)
    def _root_index() -> FileResponse:
        return index_response()

    @target_app.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
    @target_app.api_route("/ui/", methods=["GET", "HEAD"], include_in_schema=False)
    def _ui_index() -> FileResponse:
        return index_response()

    @target_app.api_route("/ui/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def _ui_spa(full_path: str) -> Response:
        return spa_serve(full_path)

    @target_app.api_route("/frontend", methods=["GET", "HEAD"], include_in_schema=False)
    @target_app.api_route("/frontend/", methods=["GET", "HEAD"], include_in_schema=False)
    def _frontend_index() -> FileResponse:
        return index_response()

    @target_app.api_route(
        "/frontend/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False
    )
    def _frontend_spa(full_path: str) -> Response:
        return spa_serve(full_path)

    assets_dir = ui_dir / "assets"
    if assets_dir.is_dir():
        target_app.mount("/assets", _ImmutableAssets(directory=str(assets_dir)), name="ui_assets")
    return True


mount_spa(app, _UI_DIR)
