#!/usr/bin/env bash
# Run the FastAPI service (React SPA + JSON API) locally on port 8000 —
# the same contract as BYOC.
#
# Usage:
#   ./scripts/run_local.sh                 # build SPA if needed, serve at :8000
#   PORT=8080 ./scripts/run_local.sh       # override port
#   FORCE_UI_BUILD=1 ./scripts/run_local.sh  # rebuild the SPA first
#
# The built SPA is served at http://localhost:8000/ui (and /frontend).
#
# For hot-reload development, run two terminals instead:
#   1) uv run uvicorn multihop_eval.web.service:app --reload --port 8000
#   2) cd ui && npm run dev      # http://localhost:5173 (proxies API to :8000)
#
# Requires: uv installed, Node.js 18+, `.env` populated (see .env.example).

set -euo pipefail

cd "$(dirname "$0")/.."

uv sync --extra dev

# Build the SPA if it hasn't been built yet (or when FORCE_UI_BUILD=1).
if [ ! -d ui/dist ] || [ "${FORCE_UI_BUILD:-0}" = "1" ]; then
  echo "Building the React/Vite SPA into ui/dist ..."
  (cd ui && npm install && npm run build)
fi

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
export PORT HOST

exec uv run python main.py
