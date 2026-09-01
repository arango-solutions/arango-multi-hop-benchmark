#!/usr/bin/env bash
# Pack a Python HTTP service for Arango Container Manager BYOC (py12base).
#
# Usage:
#   pack.sh --project DIR --name NAME [--entrypoint main.py] [--out FILE]
#           [--platform x86_64-manylinux_2_17] [--workdir DIR]
#
# Writes a tarball with:
#   entrypoint          # /project/NAME/ENTRYPOINT
#   the_venv/           # uv-cross-compiled cp312 wheels
#   NAME/               # project source
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT=""
NAME=""
ENTRYPOINT="main.py"
OUT=""
WORKDIR=""
PLATFORM="${BYOC_PLATFORM:-x86_64-manylinux_2_17}"
PY_VER="${BYOC_PYTHON_VERSION:-3.12}"
UV="${UV:-uv}"
PY="${PY:-python3}"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# //;s/^#//'
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --entrypoint) ENTRYPOINT="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$PROJECT" && -n "$NAME" ]] || usage
PROJECT="$(cd "$PROJECT" && pwd)"
[[ -f "$PROJECT/pyproject.toml" ]] || { echo "error: $PROJECT/pyproject.toml missing" >&2; exit 1; }
[[ -f "$PROJECT/$ENTRYPOINT" ]] || { echo "error: $PROJECT/$ENTRYPOINT missing" >&2; exit 1; }

if ! command -v "$UV" >/dev/null 2>&1; then
  echo "error: uv is required to vendor Linux $PY_VER wheels (py12base has no pip)." >&2
  echo "       install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

OUT="${OUT:-$PWD/dist/${NAME}.tar.gz}"
OUT="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUT")"
WORKDIR="${WORKDIR:-$(dirname "$OUT")}"
mkdir -p "$WORKDIR"

STAGE="$WORKDIR/$NAME"
VENV_STAGE="$WORKDIR/the_venv"
SITE="$VENV_STAGE/lib/python$PY_VER/site-packages"
ENTRY_FILE="$WORKDIR/entrypoint"

rm -rf "$STAGE" "$VENV_STAGE"
mkdir -p "$STAGE" "$SITE"

# Copy source; never ship secrets, tests, or a host venv.
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.env' --exclude '.env.*' --exclude '.venv' --exclude 'venv' \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
    --exclude 'test_*.py' --exclude 'tests' --exclude 'screenshot.sh' \
    "$PROJECT/" "$STAGE/"
else
  cp -R "$PROJECT/." "$STAGE/"
  find "$STAGE" \( -name '.env' -o -name '__pycache__' -o -name 'test_*.py' \) -prune -exec rm -rf {} + 2>/dev/null || true
fi

if [[ -f "$STAGE/.env" ]]; then
  echo "error: .env must not be packed into the BYOC archive" >&2
  exit 1
fi

echo "vendoring $PLATFORM / cp${PY_VER//./} wheels into the_venv ..."
"$UV" pip install \
  --target "$SITE" \
  --python-version "$PY_VER" \
  --python-platform "$PLATFORM" \
  --no-compile \
  -r "$PROJECT/pyproject.toml"

if [[ ! -d "$SITE/fastapi" ]]; then
  echo "warning: fastapi/ not in $SITE (ok if this service does not use FastAPI)" >&2
fi
if [[ -z "$(ls -A "$SITE" 2>/dev/null)" ]]; then
  echo "error: $SITE is empty after uv pip install" >&2
  exit 1
fi

printf '%s\n' "/project/${NAME}/${ENTRYPOINT}" > "$ENTRY_FILE"

export COPYFILE_DISABLE=1
if [[ -x "$PY" ]] || command -v "$PY" >/dev/null 2>&1; then
  :
else
  PY=python3
fi
"$PY" "$SKILL_DIR/scripts/pack_tar.py" "$OUT" "$ENTRY_FILE" "$VENV_STAGE" "$STAGE"

echo "wrote $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes)"
echo "layout: entrypoint -> /project/${NAME}/${ENTRYPOINT}  +  the_venv ($PLATFORM)  +  ${NAME}/"
echo "upload: Control Panel → Container Manager → Packages  (bump the version)"
echo "deploy: base image py12base"
