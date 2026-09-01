---
name: arango-byoc
description: Packages Python HTTP services as Arango Container Manager Bring Your Own Code (BYOC) `.tar.gz` archives for py12base (entrypoint path file, manylinux the_venv wheels, port 8000). Use when the user mentions BYOC, Bring Your Own Code, Container Manager, ServiceMaker, py12base, FileManager, `/_service/uds/`, or deploying a custom service onto the Arango Contextual Data Platform.
---

# Arango Container Manager BYOC

Pack a **Python HTTP service** as a `.tar.gz` and upload it under Control Panel → Container Manager → **Packages**. The platform does **not** build your image. It starts stock **`py12base`**, downloads the archive, extracts into `/project`, and runs `python $(cat entrypoint)`.

BYOContainer (a Docker image URL) is a different path — do not use this skill for that.

## When to use

- User wants to deploy *this* or *another* Python service to Arango Container Manager
- Logs show `No entrypoint found, running bash instead...` or `No module named pip`
- Packaging FastAPI/Starlette/uvicorn for `py12base`

## Non-negotiable runtime contract

`py12base` `/scripts/entrypoint.sh` (verified):

1. `cd /project`
2. `curl` `ARCHIVE_FILE` → `project.tar.gz` and `tar xzvf`
3. `test -e entrypoint` then `ENTRYPOINT=$(cat entrypoint)` (a **path string**, not a script)
4. `exec python $ENTRYPOINT`

Also required:

- Listen on **`0.0.0.0:8000`**
- Handle **`/`** (platform strips `/_service/uds/_db/<db>/<app>/`)
- **No `python -m pip`** — the venv has uv, not pip
- Extra deps live in **`the_venv/lib/python3.12/site-packages`** (set as `PYTHONPATH`)

## Archive layout (ServiceMaker zipper.sh)

```
entrypoint                         # one line: /project/<name>/<script.py>
the_venv/lib/python3.12/site-packages/   # manylinux cp312 wheels
<name>/                            # project source (pyproject.toml, code, static/)
```

`entrypoint` must be a **top-level file**, sibling of `<name>/`, not inside it.

## Pack workflow

Copy this checklist:

```
- [ ] Service is Python 3.12 HTTP on 8000, serves /
- [ ] pyproject.toml lists runtime deps in the main `dependencies` array (no extras groups)
- [ ] Entrypoint prepends bundled the_venv site-packages (see examples.md)
- [ ] UI fetch/asset URLs are relative (no leading `/api` or `/style.css`)
- [ ] Arango calls use ARANGO_DEPLOYMENT_ENDPOINT + inbound JWT (see examples.md)
- [ ] Run pack.sh; confirm tar has `entrypoint` + `the_venv/` + linux `.so` files
- [ ] Upload new version; download size must match the new archive (not an old ~100 KB package)
```

**Pack** (from this skill directory, or after copying the skill into a repo):

```bash
.cursor/skills/arango-byoc/scripts/pack.sh \
  --project ./myservice \
  --name myservice \
  --entrypoint main.py \
  --out dist/myservice.tar.gz
```

Requires **`uv`** on the pack machine. Wheels are `x86_64-manylinux_2_17` / CPython 3.12 (typical platform nodes). For arm64 clusters pass `--platform aarch64-manylinux_2_17`.

Never tar with macOS `tar -czf` (writes `LIBARCHIVE.xattr.com.apple.provenance`). `pack.sh` uses Python `tarfile.GNU_FORMAT`.

Never pack `.env`, tests, or `.venv`.

## Deploy

1. Control Panel → Container Manager → Packages
2. Upload the `.tar.gz`; **new semantic version** (platform keys packages by name/version)
3. Base image **`py12base`**
4. Service URL path (e.g. `myservice`)
5. Scope to the target database (or global)

URLs:

- DB-scoped: `https://<endpoint>:8529/_service/uds/_db/<db>/<app>/`
- Global: `https://<endpoint>:8529/_service/uds/_global/<app>/`

## Auth inside the cluster

| Context | Endpoint | Auth |
|---|---|---|
| BYOC pod | `ARANGO_DEPLOYMENT_ENDPOINT` (injected) | inbound `Authorization: Bearer` (forward it) and/or `ARANGO_TOKEN` file |
| Local | `.env` `ARANGO_ENDPOINT` | Basic `ARANGO_USER` / `ARANGO_PASSWORD` |

Do not bake secrets into the tarball.

## Known failures

| Log / symptom | Cause | Fix |
|---|---|---|
| `No entrypoint found, running bash instead...` | Archive has only `<name>/`, no top-level `entrypoint` file | Re-pack with `pack.sh` |
| `No module named pip` | Runtime `pip install`; py12base has no pip | Vendor `the_venv` at pack time |
| Download ~100 KB after you packed ~10 MB | UI still serving an old version | Bump version; confirm FileManager size |
| `invalid ELF` / `wrong architecture` | Packed amd64 wheels on arm64 (or reverse) | Re-pack with matching `--platform` |
| UI loads, `/api/...` 404 on coordinator | Absolute `/api` or `/style.css` in the browser | Relative URLs + `serviceBase` from `location.pathname` |
| `LIBARCHIVE.xattr.com.apple.provenance` | macOS tar xattrs | Use `pack.sh` (Python tarfile) |

## Introducing this skill to another project

Copy the whole `arango-byoc/` directory into the other repo at **both**:

- `.cursor/skills/arango-byoc/` (Cursor)
- `.claude/skills/arango-byoc/` (Claude Code)

Keep the two copies identical.

## Additional resources

- FastAPI entrypoint, pyproject, JWT client, relative URLs: [examples.md](examples.md)
- Packer: [scripts/pack.sh](scripts/pack.sh) (execute it; do not reimplement)
- Platform docs: https://docs.arango.ai/platform-suite/container-manager/
- ServiceMaker (optional local image build, not required for Packages upload): https://github.com/arangodb/servicemaker
