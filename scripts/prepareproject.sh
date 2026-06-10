#!/usr/bin/env bash
# ============================================================================
# prepareproject.sh — Arango BYOC build hook
# ----------------------------------------------------------------------------
# Build a COMPLETE, self-contained virtual environment at /project/the_venv so
# the runtime (base image scripts/entrypoint.sh) can import every dependency
# via PYTHONPATH=/project/the_venv/lib/python3.13/site-packages.
#
# Why a custom hook (vs ServiceMaker's default prepareproject.sh):
#   ServiceMaker's default installs deps into the base image venv
#   (/home/user/the_venv), then relocates only the "newly added" files (by
#   sha256 diff) into /project/the_venv. That diff-and-move silently drops
#   compiled native extensions, yielding at runtime:
#       ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'
#   Installing every wheel fresh into the target dir keeps compiled extensions
#   intact and is architecture-correct (the install runs inside the Linux base
#   image, never copied from a developer's macOS .venv).
#
# IMPORTANT: The arangodb/py13base image has NO system `python3` — only `uv`
# plus a uv-managed 3.13 venv at /home/user/the_venv. So we build the target
# venv with `uv` and pin it to Python 3.13 (matching the runtime + the
# PYTHONPATH the base image's entrypoint.sh exports). A `python3` path is kept
# as a fallback for non-Arango builders.
# ============================================================================
set -euo pipefail

echo "==> multihop-eval prepareproject.sh starting..."

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${VENV_PATH:-/project/the_venv}"
PYTHON_VERSION="${PYTHON_VERSION:-3.13}"
REQUIREMENTS="${REPO_ROOT}/requirements.txt"

if [[ ! -f "${REQUIREMENTS}" ]]; then
    echo "ERROR: ${REQUIREMENTS} not found. Run: bash scripts/sync-requirements.sh" >&2
    exit 1
fi

# Make uv available if the Arango base image installed it for `user`.
# shellcheck disable=SC1091
[[ -f /home/user/.local/bin/env ]] && . /home/user/.local/bin/env
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-3600}"

if command -v uv >/dev/null 2>&1; then
    echo "==> Building venv with uv (python ${PYTHON_VERSION}) at ${VENV_PATH}..."
    uv venv --python "${PYTHON_VERSION}" "${VENV_PATH}"
    # shellcheck disable=SC1091
    source "${VENV_PATH}/bin/activate"
    echo "==> uv pip install -r requirements.txt..."
    uv pip install -r "${REQUIREMENTS}"
else
    # Fallback for environments that ship a real python3 (e.g. other builders).
    PYBIN="$(command -v "python${PYTHON_VERSION}" || command -v python3 || true)"
    if [[ -z "${PYBIN}" ]]; then
        echo "ERROR: neither 'uv' nor a python interpreter found to build ${VENV_PATH}." >&2
        exit 1
    fi
    echo "==> Building venv with ${PYBIN} at ${VENV_PATH}..."
    "${PYBIN}" -m venv "${VENV_PATH}"
    # shellcheck disable=SC1091
    source "${VENV_PATH}/bin/activate"
    python -m pip install --upgrade pip
    python -m pip install -r "${REQUIREMENTS}"
fi

# Defensive: ServiceMaker-style relocation chokes on data files whose names
# contain spaces (e.g. scipy test fixtures). We don't depend on scipy, but
# strip any such files so they can't break a future build.
find "${VENV_PATH}/lib" -name "* *" -type f -delete 2>/dev/null || true

echo "==> Verifying critical imports resolve inside ${VENV_PATH}..."
python - <<'PY'
import importlib

for mod in ("uvicorn", "fastapi", "pydantic", "pydantic_core"):
    importlib.import_module(mod)
print("OK: uvicorn, fastapi, pydantic, pydantic_core all import.")
PY

echo "==> Dependencies installed successfully into ${VENV_PATH}."
