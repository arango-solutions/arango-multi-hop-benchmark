"""Ad-hoc tab — paste Q/A/proof/sources, run validation only."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from multihop_eval.adhoc import AdhocEvaluator
from multihop_eval.config import AppConfig
from multihop_eval.llm_client import LLMClient


def _editable_table(label: str, default_rows: list[dict], columns: dict) -> pd.DataFrame:
    return st.data_editor(
        pd.DataFrame(default_rows),
        num_rows="dynamic",
        column_config=columns,
        use_container_width=True,
        key=label,
    )


def render_adhoc_tab() -> None:
    cfg: AppConfig | None = st.session_state.get("app_config")
    if cfg is None:
        st.warning("Configure the app first (Configure tab) — the LLM key is needed.")
        return

    st.caption(
        "Validate an existing question / answer / proof against pasted source documents. "
        "No data is written to ArangoDB."
    )

    cols = st.columns(2)
    question = cols[0].text_area("Question", height=120)
    answer = cols[1].text_area("Answer", height=120)
    reasoning_chain = st.text_input("Reasoning chain (optional)", value="")
    persona_label = st.text_input("Persona label (for rubric only)", value="ad_hoc")

    st.markdown("**Source documents (at least 2):**")
    sources_df = _editable_table(
        "adhoc_sources",
        default_rows=[
            {"_id": "src/example_a", "content": ""},
            {"_id": "src/example_b", "content": ""},
        ],
        columns={
            "_id": st.column_config.TextColumn("Source _id"),
            "content": st.column_config.TextColumn("Content", width="large"),
        },
    )

    st.markdown("**Proof points:**")
    proof_df = _editable_table(
        "adhoc_proof",
        default_rows=[
            {"point": "", "source_id": "src/example_a"},
            {"point": "", "source_id": "src/example_b"},
        ],
        columns={
            "point": st.column_config.TextColumn("Point", width="large"),
            "source_id": st.column_config.TextColumn("Source _id"),
        },
    )

    score_with_rubric = st.checkbox(
        "Also score with the configured rubric (judge LLM)",
        value=cfg.eval.score_with_rubric and bool(cfg.eval.rubric_fields),
    )

    if not st.button("Run validation", type="primary"):
        return

    sources = [
        {"_id": str(r["_id"]).strip(), "content": str(r["content"]).strip()}
        for _, r in sources_df.iterrows()
        if str(r.get("_id") or "").strip() and str(r.get("content") or "").strip()
    ]
    proof = [
        {"point": str(r["point"]).strip(), "source_id": str(r["source_id"]).strip()}
        for _, r in proof_df.iterrows()
        if str(r.get("point") or "").strip() and str(r.get("source_id") or "").strip()
    ]

    if len(sources) < 2:
        st.error("Provide at least two source documents.")
        return
    if not proof:
        st.error("Provide at least one proof point.")
        return
    if not question.strip() or not answer.strip():
        st.error("Question and answer are required.")
        return

    with st.spinner("Running multi-hop check + proof verification…"):
        try:
            llm = LLMClient(cfg.llm)
            evaluator = AdhocEvaluator(
                llm=llm,
                rubric_fields=cfg.eval.rubric_fields if score_with_rubric else None,
                max_verify_rounds=cfg.eval.max_verify_rounds,
            )
            result = evaluator.evaluate(
                question=question,
                answer=answer,
                reasoning_chain=reasoning_chain,
                proof=proof,
                sources=sources,
                persona_label=persona_label,
                score_with_rubric=score_with_rubric,
            )
        except Exception as exc:
            st.error(f"Evaluation failed: {exc}")
            return

    st.markdown("### Results")
    cols = st.columns(3)
    cols[0].metric("Multi-hop", "PASS" if result.multi_hop_pass else "FAIL")
    cols[1].metric("Genuine hops", result.genuine_hop_count)
    cols[2].metric("Proof verdict", result.proof_verdict.upper())
    if result.multi_hop_reason:
        st.caption(result.multi_hop_reason)

    st.markdown("**Corrected proof:**")
    st.json(result.corrected_proof)

    if result.rubric_scores:
        st.markdown("**Rubric scores:**")
        st.json(result.rubric_scores)
        if result.rubric_weighted_score is not None:
            st.metric("Weighted aggregate (0..1)", f"{result.rubric_weighted_score:.3f}")

    st.download_button(
        "Download result (.json)",
        data=json.dumps(result.to_dict(), indent=2).encode("utf-8"),
        file_name="adhoc_result.json",
        mime="application/json",
    )


# Silence unused warning if `Any` is imported but only referenced by docstrings.
_unused: Any = None
