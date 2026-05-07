"""BYOC entrypoint.

Per the Arango BYOC contract (see `.cursor/skills/package-for-arango-byoc-skill.md`):
  * The container must expose an HTTP server on port **8000**.
  * The application must handle requests at the root path (`/`).

Streamlit is launched directly on `0.0.0.0:8000` with `baseUrlPath=""` so the
container manager can route requests at `/` straight to the UI without a
reverse proxy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from streamlit.web import cli as stcli


def _resolve_streamlit_app() -> str:
    here = Path(__file__).resolve().parent
    return str(here / "src" / "multihop_eval" / "ui" / "streamlit_app.py")


def main() -> int:
    port = int(os.getenv("PORT", "8000"))
    address = os.getenv("HOST", "0.0.0.0")  # noqa: S104 — BYOC requires binding to all interfaces
    base_path = os.getenv("STREAMLIT_BASE_PATH", "")

    sys.argv = [
        "streamlit",
        "run",
        _resolve_streamlit_app(),
        f"--server.port={port}",
        f"--server.address={address}",
        f"--server.baseUrlPath={base_path}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
