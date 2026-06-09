# Multi-Hop Eval service for Arango BYOC.
#
# A single FastAPI process serves the React/Vite SPA and the JSON API on
# port 8000 at the root path.
#
# BYOC requires:
#   - HTTP server on port 8000 at root path
#   - Python 3.13
#   - dependencies via uv from pyproject.toml (no `--extra` packages)
#
# Stage 1 builds the SPA with Node; stage 2 is the Arango-published Python
# base image (so ServiceMaker can extend it without re-pulling). If you build
# locally on Apple Silicon, build the base image natively first:
#   docker build -f Dockerfile.py13base -t arangodb/py13base:latest baseimages/

# ---------------------------------------------------------------------------
# Stage 1: build the React/Vite SPA into ui/dist
# ---------------------------------------------------------------------------
FROM node:20-slim AS ui-build

WORKDIR /ui

# Install deps first so source changes don't bust the npm layer.
COPY ui/package.json ui/package-lock.json ./
RUN npm ci

COPY ui/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python backend (serves the built SPA + API)
# ---------------------------------------------------------------------------
FROM arangodb/py13base:latest

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Install only deps first so source changes don't bust the dep layer.
COPY pyproject.toml ./
COPY README.md ./
RUN uv sync --no-dev

# Application code.
COPY main.py ./
COPY src ./src

# Built SPA — service.py serves it from <repo>/ui/dist when present.
COPY --from=ui-build /ui/dist ./ui/dist

EXPOSE 8000

# BYOC contract: serve on 0.0.0.0:8000 at /
CMD ["uv", "run", "python", "main.py"]
