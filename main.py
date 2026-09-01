"""BYOC entrypoint.

Per the Arango BYOC contract (see `.cursor/skills/arango-byoc/SKILL.md`):
  * The container must expose an HTTP server on port **8000**.
  * The application must handle requests at the root path (`/`).

A single FastAPI process (``multihop_eval.web.service:app``) serves both the
static UI (``static/``) and the JSON API on ``0.0.0.0:8000``. ``proxy_headers``
+ ``forwarded_allow_ips`` let it sit behind the Arango edge router without
losing the original scheme/host.

py12base runs ``python $(cat entrypoint)`` against a stock interpreter with no
pip and no site-packages of ours, so the bundled ``the_venv`` must be on
``sys.path`` *before* any third-party import. Every import below the path
setup is therefore deliberately deferred.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _prepend_bundled_site_packages() -> None:
    """Put the vendored ``the_venv`` site-packages ahead of everything else.

    The archive layout is ``/project/the_venv`` alongside
    ``/project/<name>/main.py``, but tolerate the venv sitting next to or
    inside this directory so the same entrypoint works when run from a
    checkout or a differently-shaped archive.
    """
    roots = (Path("/project/the_venv"), _DIR.parent / "the_venv", _DIR / "the_venv")
    seen: set[str] = set()
    paths: list[str] = []
    for root in roots:
        for candidate in sorted(root.glob("lib/python*/site-packages")):
            resolved = str(candidate.resolve())
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    for path in reversed(paths):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


_prepend_bundled_site_packages()

# The package uses a src-layout. When installed (e.g. ``uv sync``) it is
# importable directly, but BYOC runs ``python main.py`` against an environment
# that only has the dependencies, not the project itself.
_SRC = _DIR / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    import uvicorn

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
