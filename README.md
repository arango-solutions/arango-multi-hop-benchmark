# multi-hop-eval

Multi-hop QA dataset generation, validation, and rubric-based evaluation
against an ArangoDB graph corpus, packaged as an
[Arango BYOC](https://arango.ai/blog/deploy-your-code-your-way-introducing-arango-byoc/)
Streamlit service.

## What it does

Given clusters of related documents in ArangoDB, the service:

1. **Generates** multi-hop QA pairs whose answers require combining evidence
   from multiple documents (so they can't be answered by vector RAG over a
   single chunk).
2. **Validates** each candidate via a strict multi-hop check (does each cited
   doc add necessary, distinct evidence?) and a proof-verification loop.
3. **Scores** every accepted QA pair against a **user-defined rubric**
   (factuality, faithfulness, conciseness, multi-hop genuineness, persona-fit
   by default — fully editable from the UI).
4. **Persists** to an ArangoDB collection and exports Excel / JSON.
5. **Visualises** results in a Streamlit dashboard with KPIs, charts, and a
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
├── config.py                 # Pydantic Settings: Arango, LLM, Eval, AppConfig
├── personas.py               # Persona model + DEFAULT_PERSONAS
├── rubric.py                 # RubricField model + DEFAULT_RUBRIC
├── arango_gateway.py         # all ArangoDB I/O behind one class
├── llm_client.py             # OpenAI-compatible chat client + retries
├── prompts.py                # system prompts + builders (gen / multihop / verify / rubric)
├── subgraph.py               # pure subgraph builders (no I/O)
├── pipeline.py               # GenerationPipeline / ClusterProcessor / EvaluationOrchestrator
├── rubric_evaluator.py       # judge-LLM-driven rubric scorer
├── adhoc.py                  # AdhocEvaluator — validates user-supplied Q/A/proof
├── summary.py                # build_summary(RunResult) → KPIs + distributions
├── exporters/                # Excel + JSON writers (incl. rag_eval exporter)
├── rag_eval/                 # RAG-system evaluation feature
│   ├── models.py             #   RagResponse / RagEvalRun / RagMetricBundle
│   ├── qrels.py              #   golden proof_list → qrels (binary | graded)
│   ├── sources/              #   JSONL upload + Arango sink loaders
│   ├── metrics/              #   retrieval.py + generation.py (no-LLM scorers)
│   ├── pipeline.py           #   RagEvalOrchestrator (per-system aggregation)
│   └── langfuse_sink.py      #   optional human-annotation sink
└── ui/                       # Streamlit app: Configure / Run / Dashboard / Ad-hoc / RAG Eval tabs
```

## Quick start (local)

Prerequisites: [uv](https://docs.astral.sh/uv/) and Python 3.13.

```bash
cp .env.example .env
# Fill in ARANGO_HOST, ARANGO_DB, ARANGO_PASSWORD, LLM_API_KEY at minimum.

./scripts/run_local.sh
# → Streamlit UI at http://0.0.0.0:8000/
```

The same `main.py` that drives `run_local.sh` is the BYOC entrypoint, so what
you see locally is exactly what runs in the container.

## Running tests

```bash
uv sync --extra dev
uv run pytest          # all unit + integration tests
uv run ruff check .    # lint
```

## Containerising for Arango BYOC

This project is laid out so [ServiceMaker](https://github.com/arangodb/servicemaker)
can package it without modification. Per the Arango BYOC contract:

* The Streamlit service binds to `0.0.0.0:8000` and serves at the root path
  (`baseUrlPath=""`) — see [main.py](main.py).
* All dependencies live in `[project.dependencies]` of
  [pyproject.toml](pyproject.toml) (no `uv sync --extra` extras at runtime 
* Python 3.13 is required (`.python-version` and `pyproject.toml` agree).

### ServiceMaker workflow

```bash
# One-time: clone & build ServiceMaker
git clone https://github.com/arangodb/servicemaker.git
cd servicemaker
cargo build --release

# From the multi-hop-eval workspace root:
/path/to/servicemaker/target/release/servicemaker \
  --name multihop-eval \
  --project-home . \
  --port 8000

# The deployable artifact will be at:
#   target/<run-id>/<project-name>/project.tar.gz
# Upload that to the Container Manager along with:
#   - File name      : multihop-eval
#   - Version        : 1.0.0
#   - Service URL    : multihop-eval
```

If you're on Apple Silicon and ServiceMaker pulls an `amd64` base image,
build the base image natively first:

```bash
cd servicemaker/baseimages
docker build -f Dockerfile.py13base -t arangodb/py13base:latest .
```

### Manual containerisation

If you'd rather skip ServiceMaker:

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

* **Configure** — fill in Arango connection, LLM provider, evaluation knobs;
  edit the personas table; edit the rubric (add/remove fields, change scales
  and weights). Save persists into the session; "Load from env" reads
  `.env` / `./env`.
* **Run** — kicks off generation in a background thread; the live log streams
  events (cluster start, seed, accepted, rejected, pass done). Progress bar
  tracks `accepted/target` for the current cluster.
* **Dashboard** — switch between "this session's run" and the persisted
  ArangoDB collection. KPIs (total, accept rate, avg hops, weighted rubric),
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

## Configuration reference

All env vars are optional in the UI (you can fill everything in via the
Configure tab) but required for non-interactive runs.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARANGO_HOST` | — | https URL of the Arango cluster |
| `ARANGO_DB` | — | database name |
| `ARANGO_USERNAME` | `root` | |
| `ARANGO_PASSWORD` | — | |
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
