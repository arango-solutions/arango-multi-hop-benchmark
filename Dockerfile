# Multi-Hop Eval Streamlit service for Arango BYOC.
#
# BYOC requires:
#   - HTTP server on port 8000 at root path
#   - Python 3.13
#   - dependencies via uv from pyproject.toml (no `--extra` packages)
#
# We use the Arango-published base image so ServiceMaker can extend it
# without re-pulling. If you build locally on Apple Silicon, build the
# base image natively first:
#   docker build -f Dockerfile.py13base -t arangodb/py13base:latest \
#       baseimages/

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

# Now copy the application.
COPY main.py ./
COPY src ./src

EXPOSE 8000

# BYOC contract: serve on 0.0.0.0:8000 at /
CMD ["uv", "run", "python", "main.py"]
