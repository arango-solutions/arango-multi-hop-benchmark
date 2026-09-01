#!/usr/bin/env bash
# ============================================================================
# sync-requirements.sh
# ----------------------------------------------------------------------------
# Regenerate (or verify) `requirements.txt` from the canonical dependency list
# in `pyproject.toml` (`[project].dependencies`).
#
# Why this exists:
#   - Local dev + the Dockerfile install from `pyproject.toml` + `uv.lock`.
#   - The Arango BYOC build hook `scripts/prepareproject.sh` installs with
#     `pip install -r requirements.txt` into a complete, self-contained venv at
#     `/project/the_venv`. This sidesteps ServiceMaker's default
#     `prepareproject.sh`, which installs into the base image venv and then
#     relocates only "newly added" files to `/project/the_venv` — a diff-and-move
#     that drops compiled extensions (e.g. `pydantic_core._pydantic_core.so`)
#     and yields `ModuleNotFoundError` at runtime.
#
#   `requirements.txt` is a derived artefact; keep it in sync so it can't drift.
#
# Usage:
#   bash scripts/sync-requirements.sh           # rewrite requirements.txt
#   bash scripts/sync-requirements.sh --check   # exit 1 if out of sync (CI)
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYPROJECT="${REPO_ROOT}/pyproject.toml"
TARGET="${REPO_ROOT}/requirements.txt"

if [[ ! -f "${PYPROJECT}" ]]; then
    echo "ERROR: ${PYPROJECT} not found" >&2
    exit 2
fi

# Pick a Python with the stdlib `tomllib` (3.11+). Prefer the project venv,
# which is pinned to 3.12. `tomllib` is guaranteed on the BYOC 3.12 runtime.
pick_python() {
    for candidate in "${REPO_ROOT}/.venv/bin/python" python3 python; do
        if command -v "${candidate}" >/dev/null 2>&1 \
            && "${candidate}" -c 'import tomllib' >/dev/null 2>&1; then
            echo "${candidate}"
            return 0
        fi
    done
    return 1
}

PYTHON_BIN="$(pick_python)" || {
    echo "ERROR: need a Python 3.11+ interpreter with 'tomllib' on PATH (or .venv)." >&2
    exit 2
}

# Extract the [project].dependencies array. We deliberately use Python (already
# required to run this project) instead of `tomlq`/`yq` so this script has no
# extra prereqs.
GENERATED="$(PYPROJECT_PATH="${PYPROJECT}" "${PYTHON_BIN}" - <<'PY'
import os
import sys
import tomllib
from pathlib import Path

pyproject = Path(os.environ["PYPROJECT_PATH"])
with pyproject.open("rb") as fh:
    data = tomllib.load(fh)

deps = data.get("project", {}).get("dependencies", [])
if not deps:
    print(f"ERROR: no [project].dependencies in {pyproject}", file=sys.stderr)
    sys.exit(2)

header = (
    "# AUTO-GENERATED — do not edit by hand.\n"
    "# Regenerate with: bash scripts/sync-requirements.sh\n"
    "# Source of truth: pyproject.toml ([project].dependencies)\n"
    "#\n"
    "# Consumed by scripts/prepareproject.sh (Arango BYOC build hook). Local dev\n"
    "# and the Dockerfile install from pyproject.toml + uv.lock directly; this\n"
    "# file exists to give the BYOC venv a flat, pip-installable dependency list.\n"
)
print(header + "\n".join(deps))
PY
)"

case "${1:-}" in
    --check)
        if ! diff -u "${TARGET}" <(printf '%s\n' "${GENERATED}") > /dev/null 2>&1; then
            echo "ERROR: ${TARGET} is out of sync with ${PYPROJECT}." >&2
            echo "Run: bash scripts/sync-requirements.sh" >&2
            exit 1
        fi
        echo "OK: requirements.txt is in sync with pyproject.toml"
        ;;
    "")
        printf '%s\n' "${GENERATED}" > "${TARGET}"
        echo "Wrote ${TARGET}"
        ;;
    *)
        echo "Usage: $0 [--check]" >&2
        exit 2
        ;;
esac
