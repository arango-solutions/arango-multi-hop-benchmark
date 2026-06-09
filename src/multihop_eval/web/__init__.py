"""FastAPI web layer that serves the React/Vite SPA and the JSON API.

This package replaces the former Streamlit UI. A single FastAPI process
(`multihop_eval.web.service:app`) serves the built SPA from ``ui/dist`` and
the JSON API at the container root, satisfying the Arango BYOC contract
(port 8000, root path, Python 3.13).
"""

from __future__ import annotations
