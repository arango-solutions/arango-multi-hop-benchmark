# multi-hop-eval

Multi-hop QA dataset generation, validation, and rubric-based evaluation
against an Arango graph corpus, packaged as an
[Arango BYOC](https://arango.ai/blog/deploy-your-code-your-way-introducing-arango-byoc/)
service: a no-build HTML/CSS/JS UI served by a FastAPI backend on a single
port.

> **No build step.** `static/` ships to the container exactly as it appears in
> the repo — hand-written CSS and native ES modules, no bundler and no Node.
> This is what BYOC requires: the platform extracts an archive over a stock
> `py12base` image and runs the entrypoint, so anything needing compilation
> would have to be prebuilt and committed.

## What it does

Given clusters of related documents in Arango, the service:

1. **Generates** multi-hop QA pairs whose answers require combining evidence
   from multiple documents (so they can't be answered by vector RAG over a
   single chunk).
2. **Validates** each candidate via a strict multi-hop check (does each cited
   doc add necessary, distinct evidence?) and a proof-verification loop.
3. **Scores** every accepted QA pair against a **user-defined rubric**
   (factuality, faithfulness, conciseness, multi-hop genuineness, persona-fit
   by default — fully editable from the UI).
4. **Persists** to an Arango collection and exports Excel / JSON.
5. **Visualises** results in a dashboard with KPIs, distribution charts, and a
   filterable QA table.

It also ships an **Ad-hoc** tab for validating an existing question / answer /
proof against pasted source documents — useful for spot-checking a single QA
pair without running the full pipeline.

A **RAG Eval** tab evaluates an external RAG system's answers against the
generated golden set. It computes retrieval metrics (Precision@K, Recall@K,
MRR, NDCG@K, HitRate@K, Chunk Overlap Rate, Exact Match) and rule-based
generation metrics (Groundedness, Source Diversity, Citation Coverage,
Length Consistency, ROUGE-L, Empty Retrieval Rate) — no LLM-as-judge, every
score is deterministic. Two or more `system_name`s in the same source are
rendered side-by-side for A/B comparison. Human-annotation metrics
(faithfulness / relevancy / hallucination / completeness / coherence) flow
through an optional LangFuse sink.

## Architecture

```text
src/multihop_eval/
├── config.py                 # Pydantic Settings: Arango / LLM / Eval / RagEval / LangFuse → AppConfig
├── logging_setup.py          # cross-cutting log configuration
├── clients/                  # external integrations
│   ├── arango_gateway.py     #   all ArangoDB I/O behind one class
│   └── llm_client.py         #   OpenAI-compatible chat client + retries
├── generation/               # the multi-hop QA generation feature
│   ├── models.py             #   AcceptedQA / RejectedQA / RunResult / RunEvent / ProofPoint
│   ├── personas.py           #   Persona model + DEFAULT_PERSONAS
│   ├── rubric.py             #   RubricField model + DEFAULT_RUBRIC
│   ├── prompts.py            #   system prompts + builders (gen / multihop / verify / rubric)
│   ├── subgraph.py           #   pure subgraph builders (no I/O)
│   ├── pipeline.py           #   GenerationPipeline / ClusterProcessor / EvaluationOrchestrator
│   ├── rubric_evaluator.py   #   judge-LLM-driven rubric scorer
│   ├── adhoc.py              #   AdhocEvaluator — validates user-supplied Q/A/proof
│   ├── summary.py            #   build_summary(RunResult) -> KPIs + distributions
│   └── run_control.py        #   cooperative pause/stop coordinator
├── rag_eval/                 # the RAG-system evaluation feature
│   ├── models.py             #   RagResponse / RagEvalRun / RagMetricBundle
│   ├── qrels.py              #   golden proof_list -> qrels (binary | graded)
│   ├── sources/              #   JSONL upload + Arango sink loaders
│   ├── metrics/              #   retrieval.py + generation.py (no-LLM scorers)
│   ├── pipeline.py           #   RagEvalOrchestrator (per-system aggregation)
│   └── langfuse_sink.py      #   optional human-annotation sink
├── exporters/                # Excel + JSON writers (generation + rag_eval)
└── web/                      # FastAPI: static UI serving + JSON API
    ├── service.py            #   app, /health, UI routes (/, /ui, /frontend)
    ├── sessions.py           #   per-client session registry (X-Arango-Session)
    ├── run_manager.py        #   background run thread + queue + SSE generator
    ├── schemas.py            #   request/response models
    └── routers/              #   connection / config / run endpoints

static/                       # the UI, served verbatim (no build step)
├── index.html
├── css/styles.css            #   hand-written CSS, light/dark via :root.dark
└── js/
    ├── api.js                #   apiBase() prefix-strip + X-Arango-Session
    ├── dom.js                #   el()/replace() helpers, no framework
    ├── app.js                #   tab shell, theme toggle, shared state
    └── tabs/                 #   one module per tab
```

## Quick start (local)

Prerequisites: [uv](https://docs.astral.sh/uv/) and Python 3.12. No Node.

```bash
cp .env.example .env
# Fill in ARANGO_HOST, ARANGO_DB, ARANGO_PASSWORD, LLM_API_KEY at minimum.

./scripts/run_local.sh
# → UI at http://0.0.0.0:8000/
```

The same `main.py` that drives `run_local.sh` is the BYOC entrypoint, so what
you see locally is exactly what runs in the container.

### Frontend edits

There is no frontend build. Edit a file under `static/` and reload the
browser. For backend autoreload:

```bash
uv run uvicorn multihop_eval.web.service:app --reload --port 8000
```

## Running tests

```bash
uv sync --extra dev
uv run pytest          # all unit + integration tests
uv run ruff check .    # lint
```

## Packaging for Arango BYOC

The platform does **not** build an image. It starts stock `py12base`,
downloads your archive, extracts it into `/project`, and runs
`python $(cat entrypoint)`. So the archive must already contain every
dependency, compiled for Linux.

```bash
./scripts/package_byoc.sh
# → dist/multihop-eval.tar.gz (~44 MB)
```

Then in **Control Panel → Container Manager → Packages**:

| Field | Value |
| --- | --- |
| Package | `dist/multihop-eval.tar.gz` |
| Version | a **new** semantic version (the platform keys packages by name/version) |
| Base image | `py12base` |
| Service URL | `multihop-eval` |

After uploading, confirm the reported download size matches the file on disk —
a stale ~100 KB package means the old version is still being served.

The service is then reachable at:

* DB-scoped: `https://<endpoint>:8529/_service/uds/_db/<db>/multihop-eval/`
* Global: `https://<endpoint>:8529/_service/uds/_global/multihop-eval/`

### How the archive is built

[scripts/package_byoc.sh](scripts/package_byoc.sh) is a thin wrapper around
the `arango-byoc` skill's packer at
[.cursor/skills/arango-byoc/scripts/pack.sh](.cursor/skills/arango-byoc/scripts/pack.sh).
It stages only `main.py`, `pyproject.toml`, `src/` and `static/`, then lets
the skill packer vendor the wheels and write the tarball:

```text
entrypoint                                  # /project/multihop-eval/main.py
the_venv/lib/python3.12/site-packages/      # cp312 manylinux wheels
multihop-eval/{main.py,pyproject.toml,src/,static/}
```

Requires `uv`. Does **not** require Docker or Node.

Three constraints are easy to get wrong and are pinned by tests in
[tests/unit/test_byoc_packaging.py](tests/unit/test_byoc_packaging.py):

* **Wheels target `manylinux_2_28`**, not the skill's default
  `manylinux_2_17`. Current numpy/pandas/rapidfuzz publish no cp312
  `manylinux_2_17` wheels, so uv would build them from source and emit macOS
  binaries that fail with `invalid ELF header` in the pod.
* **`main.py` prepends `the_venv` to `sys.path` before importing anything
  third-party.** py12base has no pip and none of our site-packages, so a
  top-level `import uvicorn` dies with `ModuleNotFoundError: pydantic_core`.
* **All runtime dependencies live in `[project.dependencies]`** of
  [pyproject.toml](pyproject.toml) — `uv` does not install optional extras
  groups when vendoring.

The UI side of the contract is pinned by
[tests/unit/test_static_assets.py](tests/unit/test_static_assets.py): every
URL under `static/` must be relative, because the browser sits at
`/_service/uds/_db/<db>/<app>/` while the container only ever sees the path
with that prefix stripped. A single leading slash sends the request to the
Arango coordinator instead of the service.

### Running as a container

The BYOC path above does not use Docker. If you want to run the service as a
container anyway:

```bash
docker build -t multihop-eval:1.0.0 .
docker run --rm -p 8000:8000 \
  -e ARANGO_HOST=https://… \
  -e ARANGO_DB=… \
  -e ARANGO_PASSWORD=… \
  -e LLM_API_KEY=sk-… \
  multihop-eval:1.0.0
```

## UI walkthrough

* **Configure** — connect to Arango (auto-detected AMP path or manual
  host/db/user/password), pick the database from a live list, pick each
  collection role from a selectbox with doc-count hints, multi-select
  target cluster ids from the chosen domains collection, set LLM
  provider + evaluation knobs, and edit the personas + rubric tables.
  Save persists into the session; "Load from env" reads `.env` / `./env`.
* **Run** — kicks off generation in a background thread; the live log streams
  events (cluster start, seed, accepted, rejected, pass done). Progress bar
  tracks `accepted/target` for the current cluster.
* **Dashboard** — switch between "this session's run" and the persisted
  Arango collection. KPIs (total, accept rate, avg hops, weighted rubric),
  distribution charts, filterable table, Excel/JSON downloads.
* **Ad-hoc** — paste a Q/A/proof + source docs, run multi-hop and proof
  verification only. Optionally also score with the configured rubric.
* **RAG Eval** — fetch goldens, configure relevance grading (binary or
  graded) and K cut-offs, upload responses as JSONL or read them from an
  Arango sink, compute metrics for one-or-many `system_name`s, and download
  the result as Excel or JSON. When LangFuse is configured, an extra panel
  appears for pushing traces and pulling annotator scores.

### RAG response JSONL schema

One JSON object per line, one line per (system, question):

```json
{
  "system_name": "rag_v2",
  "qa_pair_key": "1234567",
  "question": "...",
  "answer": "Foo bar [sources/abc].",
  "retrieved_chunks": [
    {"doc_id": "sources/abc", "rank": 1, "score": 0.92, "text": "..."},
    {"doc_id": "sources/xyz", "rank": 2, "score": 0.81, "text": "..."}
  ],
  "metadata": {"latency_ms": 1200}
}
```

* `qa_pair_key` must match a golden `_key` — use the **Download goldens
  JSONL** button on the RAG Eval tab to hand the right keys to the RAG team.
* `text` is optional. When present it powers groundedness; when missing,
  groundedness falls back to matching against the `doc_id` strings (lower
  signal but never zero by construction).
* The Arango sink uses the same shape, with `_key = "{system_name}__{qa_pair_key}"`
  so re-runs upsert instead of duplicating.

## AMP auto-connect

When the service is deployed inside the
[Arango Managed Platform](https://arango.ai/blog/deploy-your-code-your-way-introducing-arango-byoc/)
the kube-arangodb auth sidecar injects three pieces of context into the
container:

| Env var | Meaning |
| --- | --- |
| `ARANGO_DEPLOYMENT_ENDPOINT` (alias `ARANGODB_ENDPOINT`) | Internal HTTPS endpoint of the deployment, e.g. `https://deployment.default.svc:8529`. |
| `ARANGO_TOKEN` | **Path** to a JWT file — rotated by the sidecar with a short TTL. The app reads the current value on every connection (and on `refresh_token()`), so rotation is invisible. |
| `ARANGO_DEPLOYMENT_CA` *(optional)* | Path to the deployment's CA PEM for TLS verification. |
| `ARANGO_DEPLOYMENT_NAME` *(optional)* | Deployment name — surfaced in the connection-status banner. |

On start the Configure tab calls `detect_amp()`; when the contract above
is satisfied (or `AMP=true` is set to force the path locally), the
status pill flips to **Connected via AMP** and a database picker
appears — populated by listing every database the JWT can read (default
`_system`). Switching the database rebuilds the gateway with the same
auth, then the collection selectboxes and the cluster-id multi-select
all refresh from the live database.

If the AMP env vars are not present (or the token file is not yet
readable and `AMP` is not set), the panel falls back to the classic
host / database / username / password form — exactly as the manual
local-dev workflow has always worked.

## Configuration reference

All env vars are optional in the UI (you can fill everything in via the
Configure tab) but required for non-interactive runs.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARANGO_HOST` | — | https URL of the Arango cluster (manual path) |
| `ARANGO_DB` | — | database name |
| `ARANGO_USERNAME` | `root` | |
| `ARANGO_PASSWORD` | — | password (only required when `auth_mode='password'`) |
| `ARANGO_DEPLOYMENT_ENDPOINT` | — | AMP endpoint injected by the sidecar |
| `ARANGO_TOKEN` | — | path to the rotating JWT file (AMP path) |
| `ARANGO_DEPLOYMENT_CA` | — | optional CA PEM path for AMP TLS |
| `AMP` | `false` | explicit override to force the AMP UI path |
| `ARANGO_*_COLLECTION` | dataset defaults | override collection names |
| `LLM_API_URL` | OpenAI v1 chat | any OpenAI-compatible endpoint |
| `LLM_API_KEY` | — | |
| `LLM_MODEL` | `gpt-4.1` | |
| `LLM_TEMPERATURE` | `0.3` | |
| `LLM_MAX_TOKENS` | `4000` | |
| `LANGFUSE_ENABLED` | `false` | flip to `true` to surface the LangFuse panel |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | self-host? point this at it |
| `LANGFUSE_PUBLIC_KEY` | — | LangFuse public key (set only when enabled) |
| `LANGFUSE_SECRET_KEY` | — | LangFuse secret key (set only when enabled) |

See [src/multihop_eval/config.py](src/multihop_eval/config.py) for the full
list and validation rules.
