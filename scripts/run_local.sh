#!/usr/bin/env bash
# Run the FastAPI service (static UI + JSON API) locally on port 8000 —
# the same contract as BYOC.
#
# Usage:
#   ./scripts/run_local.sh              # serve at :8000
#   PORT=8080 ./scripts/run_local.sh    # override port
#
# The UI is served at http://localhost:8000/ (and /ui, /frontend). There is
# no build step: static/ ships exactly as it appears in the repo, so editing
# a file under static/ and reloading the browser is the whole dev loop.
#
# For backend hot-reload:
#   uv run uvicorn multihop_eval.web.service:app --reload --port 8000
#
# Requires: uv installed, `.env` populated (see .env.example).

set -euo pipefail

cd "$(dirname "$0")/.."

uv sync --extra dev

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
export PORT HOST

exec uv run python main.py
