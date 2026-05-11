"""Configure tab — Arango / LLM / Eval / Personas / Rubric forms.

Every widget exposes a `help=` argument so Streamlit renders a small "ⓘ"
icon next to its label; hovering pops a one-or-two-sentence description of
what the parameter does. Help strings are kept inline with the widget so
the explanation stays next to the field it documents.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.personas import DEFAULT_PERSONAS, Persona
from multihop_eval.rubric import DEFAULT_RUBRIC, RubricField


def _arango_form(prefill: ArangoConfig | None) -> dict[str, Any]:
    cols = st.columns(2)
    host = cols[0].text_input(
        "Host",
        value=(prefill.host if prefill else "https://"),
        help=(
            "Base URL of your ArangoDB cluster, including scheme. "
            "Example: `https://my-cluster.arangodb.cloud`."
        ),
    )
    db = cols[1].text_input(
        "Database",
        value=(prefill.db if prefill else ""),
        help=(
            "Name of the database holding the corpus collections (sources, "
            "similarities, etc.). The QA output collection will be created in "
            "this same database if it doesn't already exist."
        ),
    )
    cols = st.columns(2)
    username = cols[0].text_input(
        "Username",
        value=(prefill.username if prefill else "root"),
        help="ArangoDB user with read access to the corpus and write access to the QA collection.",
    )
    password = cols[1].text_input(
        "Password",
        value=(prefill.password.get_secret_value() if prefill else ""),
        type="password",
        help="ArangoDB user password. Kept in session memory only; never written to disk.",
    )
    with st.expander("Collection names (override only if your dataset differs)", expanded=False):
        cols = st.columns(2)
        sim = cols[0].text_input(
            "Similarity collection",
            value=(prefill.similarity_collection if prefill else "multihop_eval_similarities"),
            help=(
                "Edge collection of document-to-document similarities. Each edge has "
                "`_from`, `_to` (source `_id`s) and `similarity_score`. Used to traverse "
                "between related documents when building a subgraph."
            ),
        )
        rel = cols[1].text_input(
            "Relations collection",
            value=(prefill.relations_collection if prefill else "multihop_eval_corpus_relations"),
            help=(
                "Edge collection that maps each source document to its cluster: "
                "`_from` = source `_id`, `_to` = cluster (domain) `_id`."
            ),
        )
        cols = st.columns(2)
        rags = cols[0].text_input(
            "RAGs collection",
            value=(prefill.rags_collection if prefill else "multihop_eval_rags"),
            help=(
                "Collection mapping clusters to a `rag_partition_id`. The partition id "
                "is tagged onto every generated QA pair so downstream RAG benchmarks can "
                "filter by partition."
            ),
        )
        sources = cols[1].text_input(
            "Sources collection",
            value=(prefill.sources_collection if prefill else "multihop_eval_sources"),
            help=(
                "Collection containing the raw source documents. Each document must "
                "expose `content` and `filename` fields."
            ),
        )
        cols = st.columns(2)
        domains = cols[0].text_input(
            "Domains collection",
            value=(prefill.domains_collection if prefill else "multihop_eval_domains"),
            help=(
                "Collection whose `_id`s are referenced as cluster ids by the relations "
                "edges (e.g. `domains/cluster_0`)."
            ),
        )
        qa = cols[1].text_input(
            "QA collection (output)",
            value=(prefill.qa_collection if prefill else "qa_pairs_multihop_eval_v1"),
            help=(
                "Collection that accepted QA pairs are written to. Created automatically "
                "on first run if it doesn't exist."
            ),
        )
    return {
        "host": host,
        "db": db,
        "username": username,
        "password": password,
        "similarity_collection": sim,
        "relations_collection": rel,
        "rags_collection": rags,
        "sources_collection": sources,
        "domains_collection": domains,
        "qa_collection": qa,
    }


def _llm_form(prefill: LLMConfig | None) -> dict[str, Any]:
    cols = st.columns(2)
    api_url = cols[0].text_input(
        "API URL",
        value=(prefill.api_url if prefill else "https://api.openai.com/v1/chat/completions"),
        help=(
            "OpenAI-compatible chat-completions endpoint. Works with OpenAI, Azure "
            "OpenAI, vLLM, OpenRouter, Together, and any other server that speaks the "
            "`/v1/chat/completions` schema."
        ),
    )
    api_key = cols[1].text_input(
        "API key",
        value=(prefill.api_key.get_secret_value() if prefill else ""),
        type="password",
        help="Bearer token sent in the `Authorization` header. Treated as a secret.",
    )
    cols = st.columns(2)
    model = cols[0].text_input(
        "Model",
        value=(prefill.model if prefill else "gpt-4.1"),
        help="Model identifier passed to the chat endpoint (e.g. `gpt-4.1`, `gpt-4o-mini`).",
    )
    temperature = cols[1].slider(
        "Temperature",
        min_value=0.0,
        max_value=2.0,
        value=float(prefill.temperature if prefill else 0.3),
        step=0.05,
        help=(
            "Sampling temperature for the generator LLM. Lower (0.0–0.3) gives more "
            "deterministic, on-topic questions; higher gives more variety. The "
            "multi-hop and proof-verification judges always run at temperature 0.0."
        ),
    )
    cols = st.columns(3)
    max_tokens = cols[0].number_input(
        "Max tokens",
        min_value=64,
        max_value=128_000,
        value=int(prefill.max_tokens if prefill else 4000),
        step=128,
        help=(
            "Hard cap on the LLM's output tokens per call. Increase if generations get "
            "truncated; decrease to save cost."
        ),
    )
    timeout_s = cols[1].number_input(
        "Timeout (s)",
        min_value=1,
        max_value=3600,
        value=int(prefill.timeout_s if prefill else 180),
        help="Per-HTTP-request timeout. Raise this if you see timeouts on long contexts.",
    )
    retries = cols[2].number_input(
        "Retries",
        min_value=1,
        max_value=10,
        value=int(prefill.retries if prefill else 3),
        help=(
            "Number of attempts on transient failures (5xx, timeouts) with exponential "
            "backoff. Context-length errors are surfaced immediately without retry so "
            "the pipeline can shrink the subgraph."
        ),
    )
    return {
        "api_url": api_url,
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
        "max_tokens": int(max_tokens),
        "timeout_s": int(timeout_s),
        "retries": int(retries),
    }


def _eval_form(prefill: EvalConfig | None) -> dict[str, Any]:
    cols = st.columns(2)
    clusters_str = cols[0].text_area(
        "Target clusters (one per line)",
        value="\n".join(prefill.target_clusters if prefill else ["cluster_0"]),
        height=110,
        help=(
            "One cluster id per line. The generator processes each cluster in order, "
            "aiming to produce `Questions per cluster` accepted QA pairs from it. "
            "Cluster ids without a `/` are auto-prefixed with the domains collection."
        ),
    )
    n_questions = cols[1].number_input(
        "Questions per cluster",
        min_value=1,
        max_value=10_000,
        value=int(prefill.n_questions if prefill else 50),
        help=(
            "How many accepted QA pairs to aim for in each cluster. The pipeline runs "
            "a Pass 1 over decimated seeds, then a Pass 2 top-up over fresh seeds to "
            "hit this target."
        ),
    )
    cols = st.columns(3)
    max_verify_rounds = cols[0].number_input(
        "Max verify rounds",
        min_value=1,
        max_value=10,
        value=int(prefill.max_verify_rounds if prefill else 3),
        help=(
            "Number of times the proof-verification LLM may correct its own output "
            "before the candidate is rejected. 3 is a sensible default."
        ),
    )
    save_to_arango = cols[1].checkbox(
        "Save accepted rows to ArangoDB",
        value=bool(prefill.save_to_arango if prefill else True),
        help=(
            "When on, every accepted QA pair is inserted into the QA collection in "
            "real time. The Dashboard tab's Excel and JSON downloads work whether "
            "this is on or off."
        ),
    )
    score_with_rubric = cols[2].checkbox(
        "Score with rubric (judge LLM)",
        value=bool(prefill.score_with_rubric if prefill else True),
        help=(
            "When on, every accepted QA pair is scored against the rubric defined "
            "below by an additional judge-LLM call. Adds one LLM call per accepted row."
        ),
    )

    st.markdown("**Hop distribution**")
    hop_dist_str = st.text_input(
        "Hop sizes (comma-separated, all ≥ 2)",
        value=",".join(str(h) for h in (prefill.hop_dist if prefill else [2, 3])),
        help=(
            "How many documents a question should require to answer. `2,3` means most "
            "generated questions will need 2 or 3 documents combined. Values must be "
            "integers ≥ 2 (a 1-hop is a single-doc question, which isn't multi-hop)."
        ),
    )
    hop_weights_str = st.text_input(
        "Weights (must sum to 1.0)",
        value=",".join(str(w) for w in (prefill.hop_dist_weights if prefill else [0.7, 0.3])),
        help=(
            "Probability weights for each hop size, in the same order as 'Hop sizes'. "
            "Example: `0.7,0.3` means 70% of subgraphs target the first hop size, 30% "
            "the second. Must be non-negative and sum to exactly 1.0."
        ),
    )

    return {
        "target_clusters": [c.strip() for c in clusters_str.splitlines() if c.strip()],
        "n_questions": int(n_questions),
        "hop_dist": [int(x) for x in hop_dist_str.split(",") if x.strip()],
        "hop_dist_weights": [float(x) for x in hop_weights_str.split(",") if x.strip()],
        "max_verify_rounds": int(max_verify_rounds),
        "save_to_arango": save_to_arango,
        "score_with_rubric": score_with_rubric,
    }


def _persona_editor(prefill: list[Persona]) -> list[Persona]:
    st.caption(
        "Edit the personas the question generator imitates. Each row is one "
        "persona; add or remove rows as needed."
    )
    df = pd.DataFrame([{"label": p.label, "instruction": p.instruction} for p in prefill])
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "label": st.column_config.TextColumn(
                "Label",
                width="small",
                help=(
                    "Short slug stored on every QA row (alphanumerics, underscores, or "
                    "hyphens only). Surfaces as the persona dimension in the Dashboard."
                ),
            ),
            "instruction": st.column_config.TextColumn(
                "Instruction",
                width="large",
                help=(
                    "Prompt fragment injected into the generator as 'Write as a …'. "
                    "Each persona steers the produced questions toward a different "
                    "style or audience."
                ),
            ),
        },
        key="persona_editor",
    )
    out: list[Persona] = []
    for _, row in edited.iterrows():
        label = (row.get("label") or "").strip()
        instruction = (row.get("instruction") or "").strip()
        if not label or not instruction:
            continue
        out.append(Persona(label=label, instruction=instruction))
    return out


def _rubric_editor(prefill: list[RubricField]) -> list[RubricField]:
    st.caption(
        "Define the criteria the judge LLM should score every accepted QA "
        "pair on. Higher weight = stronger influence on the weighted aggregate."
    )
    df = pd.DataFrame(
        [
            {
                "name": f.name,
                "description": f.description,
                "scale_min": f.scale_min,
                "scale_max": f.scale_max,
                "weight": f.weight,
            }
            for f in prefill
        ]
    )
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name": st.column_config.TextColumn(
                "Name",
                width="small",
                help=(
                    "Short identifier (alphanumerics, underscores, or hyphens). Becomes "
                    "the JSON key the judge LLM must return for this criterion."
                ),
            ),
            "description": st.column_config.TextColumn(
                "Description",
                width="large",
                help=(
                    "Tell the judge LLM exactly what this criterion means and how to "
                    "score it. The clearer this is, the more consistent the scores."
                ),
            ),
            "scale_min": st.column_config.NumberColumn(
                "Min",
                min_value=0,
                max_value=10,
                step=1,
                help="Minimum integer score for this field (inclusive).",
            ),
            "scale_max": st.column_config.NumberColumn(
                "Max",
                min_value=1,
                max_value=100,
                step=1,
                help=(
                    "Maximum integer score for this field (inclusive). Each field's "
                    "score is normalised to 0..1 before the weighted aggregate is "
                    "computed, so different fields can use different scales."
                ),
            ),
            "weight": st.column_config.NumberColumn(
                "Weight",
                min_value=0.1,
                max_value=10.0,
                step=0.1,
                help=(
                    "Relative importance in the weighted aggregate. A field with "
                    "weight 2.0 counts twice as much as one with weight 1.0."
                ),
            ),
        },
        key="rubric_editor",
    )
    out: list[RubricField] = []
    for _, row in edited.iterrows():
        name = (row.get("name") or "").strip()
        description = (row.get("description") or "").strip()
        if not name or not description:
            continue
        try:
            out.append(
                RubricField(
                    name=name,
                    description=description,
                    scale_min=int(row.get("scale_min") or 1),
                    scale_max=int(row.get("scale_max") or 5),
                    weight=float(row.get("weight") or 1.0),
                )
            )
        except ValidationError as exc:
            st.warning(f"Skipping invalid rubric row {name!r}: {exc.errors()[0]['msg']}")
    return out


def render_config_form() -> AppConfig | None:
    """Render the full config form. Returns the assembled `AppConfig` once
    the user clicks Save (and validation succeeds), else `None`.
    """
    existing: AppConfig | None = st.session_state.get("app_config")
    arango_prefill = existing.arango if existing else None
    llm_prefill = existing.llm if existing else None
    eval_prefill = existing.eval if existing else None
    personas_prefill = (
        existing.eval.personas if existing else list(DEFAULT_PERSONAS)
    )
    rubric_prefill = (
        existing.eval.rubric_fields if existing else list(DEFAULT_RUBRIC)
    )

    with st.expander("ArangoDB connection", expanded=existing is None):
        arango_data = _arango_form(arango_prefill)
    with st.expander("LLM provider", expanded=existing is None):
        llm_data = _llm_form(llm_prefill)
    with st.expander("Evaluation parameters", expanded=existing is None):
        eval_data = _eval_form(eval_prefill)

    st.subheader("Personas")
    personas = _persona_editor(personas_prefill)

    st.subheader("Evaluation rubric")
    rubric_fields = _rubric_editor(rubric_prefill)

    cols = st.columns([1, 1, 4])
    save_clicked = cols[0].button(
        "Save configuration",
        type="primary",
        help=(
            "Persist these values to the current session. They're picked up by the "
            "Run and Ad-hoc tabs immediately."
        ),
    )
    load_env_clicked = cols[1].button(
        "Load from env / .env",
        help=(
            "Replace the form with values read from environment variables and the "
            "`.env` (or `env`) file at the project root. See `.env.example` for the "
            "set of supported variables."
        ),
    )

    if load_env_clicked:
        try:
            cfg = AppConfig.from_env()
            st.session_state["app_config"] = cfg
            st.success("Loaded configuration from environment.")
            st.rerun()
        except ValidationError as exc:
            st.error(f"Could not load config from env: {exc}")
        return None

    if not save_clicked:
        return existing

    try:
        cfg = AppConfig(
            arango=ArangoConfig(**arango_data),  # type: ignore[arg-type]
            llm=LLMConfig(**llm_data),  # type: ignore[arg-type]
            eval=EvalConfig(
                **eval_data,
                personas=personas,
                rubric_fields=rubric_fields,
            ),
        )
    except ValidationError as exc:
        st.error("Configuration is invalid:")
        for err in exc.errors():
            st.error(f"  • {' / '.join(str(p) for p in err['loc'])}: {err['msg']}")
        return None

    st.session_state["app_config"] = cfg
    st.success("Configuration saved for this session.")
    safe = cfg.to_safe_dict()
    with st.expander("Configuration preview (secrets redacted)"):
        st.code(json.dumps(safe, indent=2, default=str), language="json")
    return cfg
