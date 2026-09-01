#!/usr/bin/env bash
# ============================================================================
# package_byoc.sh — build the Arango Container Manager BYOC archive.
# ----------------------------------------------------------------------------
# Thin wrapper around the arango-byoc skill's pack.sh. The skill packer does
# the real work (vendoring Linux wheels into the_venv, writing the entrypoint
# path file, producing a GNU tar without macOS xattrs); this script only
# decides *what* goes in and pins the platform settings this service needs.
#
# Why a staging copy instead of `--project .`:
#   pack.sh rsyncs the whole project directory and its exclude list does not
#   cover .git, dist/, .pytest_cache, .ruff_cache or uv.lock. Copying only the
#   four things the service actually needs keeps the archive honest and makes
#   it impossible to leak a stray .env.
#
# Two platform settings differ from the skill defaults:
#   * Python 3.12 — matches py12base, whose entrypoint.sh exports
#     PYTHONPATH=/project/the_venv/lib/python3.12/site-packages.
#   * manylinux_2_28 rather than the skill's default manylinux_2_17 — current
#     numpy/pandas/rapidfuzz publish no cp312 manylinux_2_17 wheels, so uv
#     would fall back to building them from source and emit macOS binaries.
#
# Usage:
#   ./scripts/package_byoc.sh                       # -> dist/multihop-eval.tar.gz
#   OUT=/tmp/x.tar.gz ./scripts/package_byoc.sh     # custom output path
#   BYOC_PLATFORM=aarch64-manylinux_2_28 ./scripts/package_byoc.sh   # arm64
#
# Requires: uv. Does NOT require Docker or Node.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

NAME="${NAME:-multihop-eval}"
ENTRYPOINT="main.py"
OUT="${OUT:-${REPO_ROOT}/dist/${NAME}.tar.gz}"
PLATFORM="${BYOC_PLATFORM:-x86_64-manylinux_2_28}"
PYTHON_VERSION="${BYOC_PYTHON_VERSION:-3.12}"

PACK="${REPO_ROOT}/.cursor/skills/arango-byoc/scripts/pack.sh"
if [[ ! -x "${PACK}" ]]; then
    echo "ERROR: skill packer not found or not executable: ${PACK}" >&2
    exit 1
fi

# pack.sh uses "$(dirname "$OUT")/$NAME" as its own scratch directory, so the
# staging source must live somewhere else or the packer deletes its own input.
STAGE_ROOT="${REPO_ROOT}/dist/byoc-src"
STAGE="${STAGE_ROOT}/${NAME}"

echo "==> Staging service source into ${STAGE#"${REPO_ROOT}/"} ..."
rm -rf "${STAGE_ROOT}"
mkdir -p "${STAGE}"
cp main.py pyproject.toml README.md "${STAGE}/"
cp -R src static "${STAGE}/"

# Defensive: bytecode and secrets must never reach the archive.
find "${STAGE}" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
if find "${STAGE}" -name '.env*' -print -quit | grep -q .; then
    echo "ERROR: refusing to package a .env file" >&2
    exit 1
fi

echo "==> Packing (python ${PYTHON_VERSION}, ${PLATFORM}) ..."
BYOC_PYTHON_VERSION="${PYTHON_VERSION}" "${PACK}" \
    --project "${STAGE}" \
    --name "${NAME}" \
    --entrypoint "${ENTRYPOINT}" \
    --platform "${PLATFORM}" \
    --out "${OUT}"

rm -rf "${STAGE_ROOT}"

echo "==> Verifying archive layout ..."
MEMBERS="$(tar tzf "${OUT}")"
require() {
    if ! grep -q "$1" <<<"${MEMBERS}"; then
        echo "ERROR: archive is missing ${2:-$1}" >&2
        exit 1
    fi
}
refuse() {
    if grep -q "$1" <<<"${MEMBERS}"; then
        echo "ERROR: archive must not contain ${2:-$1}" >&2
        exit 1
    fi
}
require "^entrypoint$" "the top-level entrypoint file"
require "^the_venv/lib/python${PYTHON_VERSION}/site-packages/fastapi/" "vendored fastapi"
require "^${NAME}/${ENTRYPOINT}$" "${NAME}/${ENTRYPOINT}"
require "^${NAME}/static/index.html$" "the static UI"
require "^${NAME}/src/multihop_eval/" "the service source"
refuse "LIBARCHIVE" "macOS xattr entries"
refuse "\.env" "a .env file"

echo
echo "==> Wrote ${OUT} ($(du -h "${OUT}" | cut -f1))"
echo "    entrypoint -> $(tar xzf "${OUT}" -O entrypoint)"
echo
echo "Deploy: Control Panel → Container Manager → Packages"
echo "  * upload this .tar.gz under a NEW semantic version"
echo "  * base image: py12base"
echo "  * confirm the reported download size matches the file above"
