#!/usr/bin/env bash
# Run the Streamlit UI locally on port 8000 — same contract as BYOC.
#
# Usage:
#   ./scripts/run_local.sh                # default: 0.0.0.0:8000 at /
#   PORT=8501 ./scripts/run_local.sh      # override port
#
# Requires: uv installed, `.env` populated (see .env.example).

set -euo pipefail

cd "$(dirname "$0")/.."

uv sync --extra dev

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

exec uv run python main.py
