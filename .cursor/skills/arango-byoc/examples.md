# BYOC service templates

Copy these into the service you are packing. Names (`api.py`, `main.py`) can change; `--entrypoint` must match.

## pyproject.toml

```toml
[project]
name = "myservice"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "starlette>=1.3.1",
]

[build-system]
requires = ["setuptools>=75.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
py-modules = ["main", "api"]
```

Put every runtime package in `dependencies`. ServiceMaker/`uv sync` does not install optional extras groups (`[project.optional-dependencies]`).

## main.py (the file named in `entrypoint`)

py12base `exec python`s this path. Prepend bundled wheels **before** importing FastAPI. Do not call `pip`.

```python
from __future__ import annotations

import os
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))


def _prepend_bundled_site_packages() -> None:
    roots = (Path("/project/the_venv"), _DIR.parent / "the_venv", _DIR / "the_venv")
    seen: set[str] = set()
    paths: list[str] = []
    for root in roots:
        for p in sorted(root.glob("lib/python*/site-packages")):
            s = str(p.resolve())
            if s not in seen:
                seen.add(s)
                paths.append(s)
    for s in reversed(paths):
        if s in sys.path:
            sys.path.remove(s)
        sys.path.insert(0, s)


_prepend_bundled_site_packages()
from api import app  # noqa: E402


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
```

## Minimal FastAPI app

Register `/health` **before** mounting `StaticFiles` at `/`.

```python
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI(title="myservice")


class BindAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # stash request.headers.get("authorization") on a ContextVar
        # and send it as Authorization to Arango (see JWT below)
        return await call_next(request)


app.add_middleware(BindAuth)


@app.get("/health")
def health():
    return {"status": "ok"}
```

Listen via `main.py` on port 8000. Local: `uvicorn api:app --port 8080` is fine.

## Arango from the pod

Prefer `ARANGO_DEPLOYMENT_ENDPOINT`. JWT: inbound `Authorization: Bearer` (platform proxy) or `ARANGO_TOKEN` (file path or string). Skip TLS verify for the internal endpoint unless `ARANGO_VERIFY_SSL` is set.

Local fallback: `.env` `ARANGO_ENDPOINT` + Basic auth. Never pack `.env`.

Database name: `ARANGO_DB` or `db_name`, not a hardcoded coordinator hostname.

## Browser UI behind the service prefix

The container sees `/`. The browser is at `/_service/uds/_db/<db>/<app>/`.

- HTML: `href="style.css"` not `href="/style.css"`
- JS:

```javascript
const serviceBase = (() => {
  const p = location.pathname;
  if (p.endsWith('/')) return p;
  const leaf = p.slice(p.lastIndexOf('/') + 1);
  if (leaf.includes('.')) return p.slice(0, p.lastIndexOf('/') + 1);
  return p + '/';
})();
const j = (u) => fetch(serviceBase + u.replace(/^\//, ''), { credentials: 'same-origin' })
  .then((r) => { if (!r.ok) throw new Error(u + ' ' + r.status); return r.json(); });
// j('api/years')  — no leading slash
```

## Worked example

FinReflectKG time-travel demo in this repo: `demo/` packed by `scripts/package_byoc.sh` (thin wrapper around `pack.sh`).
