"""BYOC entrypoint.

Per the Arango BYOC contract (see `.cursor/skills/package-for-arango-byoc-skill.md`):
  * The container must expose an HTTP server on port **8000**.
  * The application must handle requests at the root path (`/`).

A single FastAPI process (``multihop_eval.web.service:app``) serves both the
React/Vite SPA (built into ``ui/dist``) and the JSON API on ``0.0.0.0:8000``.
``proxy_headers`` + ``forwarded_allow_ips`` let it sit behind the Arango edge
router without losing the original scheme/host.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

# The package lives under ``src/`` (src-layout). When the project is installed
# (e.g. ``uv sync``) it's importable directly, but ServiceMaker/BYOC may run
# ``python main.py`` against a venv that only has the dependencies installed and
# not the project itself. Put ``src`` on the path so the import string passed to
# uvicorn resolves regardless of how the environment was provisioned.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")  # noqa: S104 — BYOC requires binding to all interfaces

    uvicorn.run(
        "multihop_eval.web.service:app",
        host=host,
        port=port,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
