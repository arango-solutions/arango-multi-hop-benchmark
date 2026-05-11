"""Streamlit entrypoint for the multi-hop eval app.

Tabs:
  * Configure — Arango / LLM / Eval / Personas / Rubric
  * Run        — kick off a generation pass with live progress
  * Dashboard  — KPIs, charts, table, downloads
  * Ad-hoc     — validate an arbitrary Q/A/proof/sources
  * RAG Eval   — load RAG-system responses and compute retrieval +
                 rule-based generation metrics for one or many systems

Served on port 8000 at the root path so it satisfies the Arango BYOC
contract (see `.cursor/skills/package-for-arango-byoc-skill.md`).
"""

from __future__ import annotations

import streamlit as st

from multihop_eval.logging_setup import configure_logging
from multihop_eval.ui.components.adhoc_form import render_adhoc_tab
from multihop_eval.ui.components.config_form import render_config_form
from multihop_eval.ui.components.rag_eval_tab import render_rag_eval_tab
from multihop_eval.ui.components.run_progress import render_run_tab
from multihop_eval.ui.components.summary_dashboard import render_dashboard_tab
from multihop_eval.ui.state import init_session_state

st.set_page_config(
    page_title="Multi-Hop Eval",
    page_icon=":crystal_ball:",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    configure_logging("INFO")
    init_session_state(st)

    st.title("Multi-Hop QA Eval")
    st.caption(
        "Generate, validate, and rubric-score multi-hop QA pairs against an "
        "ArangoDB graph corpus. Configure connection + rubric, run a pass, "
        "and review results — all in one place."
    )

    tab_configure, tab_run, tab_dashboard, tab_adhoc, tab_rag_eval = st.tabs(
        ["Configure", "Run", "Dashboard", "Ad-hoc", "RAG Eval"]
    )
    with tab_configure:
        render_config_form()
    with tab_run:
        render_run_tab()
    with tab_dashboard:
        render_dashboard_tab()
    with tab_adhoc:
        render_adhoc_tab()
    with tab_rag_eval:
        render_rag_eval_tab()


main()
