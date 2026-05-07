"""Configure tab — Arango / LLM / Eval / Personas / Rubric forms."""

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
    host = cols[0].text_input("Host", value=(prefill.host if prefill else "https://"))
    db = cols[1].text_input("Database", value=(prefill.db if prefill else ""))
    cols = st.columns(2)
    username = cols[0].text_input("Username", value=(prefill.username if prefill else "root"))
    password = cols[1].text_input(
        "Password",
        value=(prefill.password.get_secret_value() if prefill else ""),
        type="password",
    )
    with st.expander("Collection names (override only if your dataset differs)", expanded=False):
        cols = st.columns(2)
        sim = cols[0].text_input(
            "Similarity collection",
            value=(prefill.similarity_collection if prefill else "wtw_ingest_bench_similarities"),
        )
        rel = cols[1].text_input(
            "Relations collection",
            value=(prefill.relations_collection if prefill else "wtw_ingest_bench_corpus_relations"),
        )
        cols = st.columns(2)
        rags = cols[0].text_input(
            "RAGs collection",
            value=(prefill.rags_collection if prefill else "wtw_ingest_bench_rags"),
        )
        sources = cols[1].text_input(
            "Sources collection",
            value=(prefill.sources_collection if prefill else "wtw_ingest_bench_sources"),
        )
        cols = st.columns(2)
        domains = cols[0].text_input(
            "Domains collection",
            value=(prefill.domains_collection if prefill else "wtw_ingest_bench_domains"),
        )
        qa = cols[1].text_input(
            "QA collection (output)",
            value=(prefill.qa_collection if prefill else "qa_pairs_wtw_ingest_bench_v1"),
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
    )
    api_key = cols[1].text_input(
        "API key",
        value=(prefill.api_key.get_secret_value() if prefill else ""),
        type="password",
    )
    cols = st.columns(2)
    model = cols[0].text_input("Model", value=(prefill.model if prefill else "gpt-4.1"))
    temperature = cols[1].slider(
        "Temperature",
        min_value=0.0,
        max_value=2.0,
        value=float(prefill.temperature if prefill else 0.3),
        step=0.05,
    )
    cols = st.columns(3)
    max_tokens = cols[0].number_input(
        "Max tokens",
        min_value=64,
        max_value=128_000,
        value=int(prefill.max_tokens if prefill else 4000),
        step=128,
    )
    timeout_s = cols[1].number_input(
        "Timeout (s)",
        min_value=1,
        max_value=3600,
        value=int(prefill.timeout_s if prefill else 180),
    )
    retries = cols[2].number_input(
        "Retries",
        min_value=1,
        max_value=10,
        value=int(prefill.retries if prefill else 3),
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
        value="\n".join(prefill.target_clusters if prefill else ["cluster_wtw_ingest_0"]),
        height=110,
    )
    n_questions = cols[1].number_input(
        "Questions per cluster",
        min_value=1,
        max_value=10_000,
        value=int(prefill.n_questions if prefill else 50),
    )
    cols = st.columns(3)
    max_verify_rounds = cols[0].number_input(
        "Max verify rounds",
        min_value=1,
        max_value=10,
        value=int(prefill.max_verify_rounds if prefill else 3),
    )
    save_to_arango = cols[1].checkbox(
        "Save accepted rows to ArangoDB",
        value=bool(prefill.save_to_arango if prefill else True),
    )
    score_with_rubric = cols[2].checkbox(
        "Score with rubric (judge LLM)",
        value=bool(prefill.score_with_rubric if prefill else True),
    )

    st.markdown("**Hop distribution**")
    hop_dist_str = st.text_input(
        "Hop sizes (comma-separated, all >= 2)",
        value=",".join(str(h) for h in (prefill.hop_dist if prefill else [2, 3])),
    )
    hop_weights_str = st.text_input(
        "Weights (must sum to 1.0)",
        value=",".join(str(w) for w in (prefill.hop_dist_weights if prefill else [0.7, 0.3])),
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
            "label": st.column_config.TextColumn("Label", width="small"),
            "instruction": st.column_config.TextColumn("Instruction", width="large"),
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
            "name": st.column_config.TextColumn("Name", width="small"),
            "description": st.column_config.TextColumn("Description", width="large"),
            "scale_min": st.column_config.NumberColumn("Min", min_value=0, max_value=10, step=1),
            "scale_max": st.column_config.NumberColumn("Max", min_value=1, max_value=100, step=1),
            "weight": st.column_config.NumberColumn("Weight", min_value=0.1, max_value=10.0, step=0.1),
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
    save_clicked = cols[0].button("Save configuration", type="primary")
    load_env_clicked = cols[1].button("Load from env / .env")

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
