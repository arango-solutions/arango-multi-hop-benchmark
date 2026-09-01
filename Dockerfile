# Multi-Hop Eval service.
#
# A single FastAPI process serves the static UI and the JSON API on port 8000
# at the root path — the same contract the BYOC archive satisfies.
#
# This image is for running the service as a container. Deploying to Arango
# Container Manager does NOT use it: that path uploads a .tar.gz built by
# scripts/package_byoc.sh, which the platform extracts over stock py12base.
#
# BYOC requires:
#   - HTTP server on port 8000 at root path
#   - Python 3.12
#   - dependencies via uv from pyproject.toml (no `--extra` packages)

FROM arangodb/py12base:latest

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Install only deps first so source changes don't bust the dep layer.
COPY pyproject.toml ./
COPY README.md ./
RUN uv sync --no-dev

# Application code and the no-build UI.
COPY main.py ./
COPY src ./src
COPY static ./static

EXPOSE 8000

# BYOC contract: serve on 0.0.0.0:8000 at /
CMD ["uv", "run", "python", "main.py"]
