#!/usr/bin/env bash
# ============================================================================
# package-arango-manual.sh
# ----------------------------------------------------------------------------
# Build the Arango BYOC deployment tarball (project.tar.gz).
#
# The Arango platform extracts this tarball on top of the base image at
# /project and runs `python <entrypoint>` — it never installs dependencies at
# runtime (see servicemaker baseimages/scripts/entrypoint.sh). So the tarball
# MUST contain a complete /project/the_venv. That venv must be built inside the
# Linux base image (NOT copied from a macOS .venv, or compiled extensions like
# pydantic_core._pydantic_core won't load).
#
# This script builds Dockerfile.byoc (which runs scripts/prepareproject.sh to
# create /project/the_venv with uv) and then extracts /project into the
# tarball with the layout the runtime expects:
#     the_venv/      -> /project/the_venv          (deps, on PYTHONPATH)
#     entrypoint     -> /project/entrypoint        (first token: main.py)
#     main.py, src/, ui/dist, pyproject.toml, ...  -> /project/...
#
# Options:
#   OUT=<path>                  # output tarball (default: ./project.tar.gz)
#   PLATFORM=linux/amd64        # build/extract for a specific arch (default:
#                               # host arch). Use linux/amd64 if the cluster is
#                               # x86_64 and you build on Apple Silicon.
#   IMAGE_TAG=multihop-eval-byoc:local
#   KEEP_IMAGE=1                # don't remove the builder image afterwards
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

OUT="${OUT:-${1:-${REPO_ROOT}/project.tar.gz}}"
IMAGE_TAG="${IMAGE_TAG:-multihop-eval-byoc:local}"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is required to build a Linux-correct /project/the_venv." >&2
    exit 1
fi

PLATFORM_ARGS=()
if [[ -n "${PLATFORM:-}" ]]; then
    PLATFORM_ARGS+=("--platform" "${PLATFORM}")
    echo "==> Building for platform ${PLATFORM}"
fi

# Keep requirements.txt in lockstep with pyproject before building.
echo "==> Syncing requirements.txt from pyproject.toml..."
bash "${REPO_ROOT}/scripts/sync-requirements.sh"

echo "==> Building BYOC image ${IMAGE_TAG} (this compiles the venv inside the base image)..."
docker build ${PLATFORM_ARGS[@]+"${PLATFORM_ARGS[@]}"} -f "${REPO_ROOT}/Dockerfile.byoc" -t "${IMAGE_TAG}" "${REPO_ROOT}"

# Extract /project from the built image. Running tar inside the container keeps
# Linux permissions/symlinks intact and avoids host (macOS) tar quirks. We
# exclude VCS/test/cache cruft; the_venv + source + entrypoint are included.
echo "==> Extracting /project into ${OUT}..."
docker run --rm ${PLATFORM_ARGS[@]+"${PLATFORM_ARGS[@]}"} --entrypoint tar "${IMAGE_TAG}" \
    czf - -C /project \
    --exclude='./scripts/sync-requirements.sh' \
    . > "${OUT}"

if [[ ! -s "${OUT}" ]]; then
    echo "ERROR: produced tarball is empty: ${OUT}" >&2
    exit 1
fi

if [[ "${KEEP_IMAGE:-0}" != "1" ]]; then
    docker image rm "${IMAGE_TAG}" >/dev/null 2>&1 || true
fi

SIZE="$(du -h "${OUT}" | cut -f1)"
echo "==> Wrote ${OUT} (${SIZE})"
echo "    Contents (top level):"
tar tzf "${OUT}" | sed 's#^\./##' | awk -F/ 'NF>0 && $1!="" {print $1}' | sort -u | sed 's/^/      /'
