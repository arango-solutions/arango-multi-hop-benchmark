"""FastAPI web layer that serves the static UI and the JSON API.

This package replaces the former Streamlit UI. A single FastAPI process
(`multihop_eval.web.service:app`) serves the no-build UI from ``static/`` and
the JSON API at the container root, satisfying the Arango BYOC contract
(port 8000, root path, Python 3.12).
"""

from __future__ import annotations
