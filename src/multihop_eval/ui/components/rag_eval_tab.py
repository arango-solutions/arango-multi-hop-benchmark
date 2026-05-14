"""RAG Eval tab — load responses, compute metrics, surface per-system results.

Sections, top to bottom:

  1. Golden source — fetch goldens from the configured QA collection (or
     reuse the in-session cache), then offer a JSONL download for hand-off
     to the RAG team.
  2. Configure run — relevance mode, K cut-offs, fuzz threshold, etc.
  3. Response source — JSONL upload or Arango collection; populates the
     orchestrator's response list.
  4. Compute — runs `RagEvalOrchestrator.evaluate(...)` synchronously and
     stashes the results in session state.
  5. Per-system results — one expander per system_name with KPI cards,
     metric tables, and a per-query drill-down.

Side-by-side A/B comparison across two or more systems lives in the
sibling `multi_system_compare` module so this tab stays focused.

Every input widget here exposes a `help=` tooltip — that's enforced by
`tests/unit/test_ui_rag_eval_tab_help.py`.
"""

from __future__ import annotations

import io
import json
import tempfile

import pandas as pd
import streamlit as st

from multihop_eval.clients.arango_gateway import ArangoGateway
from multihop_eval.config import (
    RAG_RELEVANCE_BINARY,
    RAG_RELEVANCE_GRADED,
    RAG_RESPONSE_SOURCE_ARANGO,
    RAG_RESPONSE_SOURCE_JSONL,
    AppConfig,
    RagEvalConfig,
)
from multihop_eval.exporters import export_rag_eval_to_excel
from multihop_eval.rag_eval.langfuse_sink import LangFuseSink
from multihop_eval.rag_eval.models import RagEvalRun, RagResponse
from multihop_eval.rag_eval.pipeline import RagEvalOrchestrator
from multihop_eval.rag_eval.sources.jsonl_source import load_responses as load_jsonl
from multihop_eval.ui.components.multi_system_compare import render_comparison
from multihop_eval.ui.state import (
    KEY_APP_CONFIG,
    KEY_RAG_EVAL_RUNS,
    KEY_RAG_GOLDENS_CACHE,
    KEY_RAG_LOAD_ERRORS,
)


def _goldens_section(app_config: AppConfig) -> list[dict] | None:
    """Render the golden-fetch + golden-export controls, return cached goldens."""
    st.subheader("Goldens")
    st.caption(
        "Multi-hop QA pairs are pulled from the configured QA collection and "
        "form the reference set. Download them as JSONL to send to the RAG team."
    )

    cached = st.session_state.get(KEY_RAG_GOLDENS_CACHE)
    cols = st.columns([2, 1, 2])
    fetch = cols[0].button(
        "Fetch goldens from Arango",
        help=(
            "Reads every row from the configured QA collection so they can be "
            "used as the reference set. Cached in this session — click again to refresh."
        ),
    )
    cols[1].metric("Cached", len(cached) if cached else 0)
    if fetch:
        try:
            gateway = ArangoGateway(app_config.arango)
            cached = gateway.fetch_goldens_with_keys()
            st.session_state[KEY_RAG_GOLDENS_CACHE] = cached
            st.success(f"Loaded {len(cached)} golden rows.")
        except Exception as exc:  # noqa: BLE001 - surface every error to the UI
            st.error(f"Failed to fetch goldens: {exc}")
            return None

    if cached:
        jsonl_bytes = _goldens_to_jsonl_bytes(cached)
        cols[2].download_button(
            "Download goldens JSONL",
            data=jsonl_bytes,
            file_name="goldens.jsonl",
            mime="application/jsonl",
            help=(
                "Download one JSON object per golden — fields: `qa_pair_key`, "
                "`question`, `answer`, and `proof`. Hand this file to the RAG "
                "team; they fill out `answer` + `retrieved_chunks` and ship it back."
            ),
        )
    return cached


def _goldens_to_jsonl_bytes(rows: list[dict]) -> bytes:
    """Serialise goldens to a JSONL blob suitable for the RAG team."""
    buf = io.StringIO()
    for row in rows:
        export = {
            "qa_pair_key": row.get("_key", ""),
            "question": row.get("question", ""),
            "answer": row.get("answer", ""),
            "proof": row.get("proof", []),
        }
        buf.write(json.dumps(export, ensure_ascii=False))
        buf.write("\n")
    return buf.getvalue().encode("utf-8")


def _configure_run(cfg: RagEvalConfig) -> RagEvalConfig:
    """Render the eval-knobs form and return an updated `RagEvalConfig`."""
    st.subheader("Evaluation knobs")
    cols = st.columns(3)
    relevance_mode = cols[0].radio(
        "Relevance grading",
        options=[RAG_RELEVANCE_BINARY, RAG_RELEVANCE_GRADED],
        index=0 if cfg.relevance_mode == RAG_RELEVANCE_BINARY else 1,
        help=(
            "Binary: every doc in `proof_list` gets grade 1. Graded: earlier "
            "hops get higher grades, so NDCG penalises systems that retrieve "
            "later-hop docs first."
        ),
    )
    k_values_str = cols[1].text_input(
        "K cut-offs (comma-separated)",
        value=", ".join(str(k) for k in cfg.k_values),
        help=(
            "Cut-offs for P@K, R@K, NDCG@K, HitRate@K. Typical: 1, 3, 5, 10. "
            "Smaller K stresses ranking; larger K stresses recall."
        ),
    )
    length_z = cols[2].number_input(
        "Length anomaly z-threshold",
        min_value=0.5,
        max_value=5.0,
        step=0.1,
        value=float(cfg.length_z_threshold),
        help=(
            "A response's answer is flagged as a length outlier when "
            "|z(len(answer))| exceeds this. 2.0 is the conventional cut-off."
        ),
    )

    cols = st.columns(3)
    fuzz_threshold = cols[0].slider(
        "Groundedness fuzz threshold",
        min_value=0,
        max_value=100,
        value=int(cfg.groundedness_fuzz_threshold),
        help=(
            "rapidfuzz `partial_ratio` cutoff (0..100) above which an answer "
            "sentence is considered grounded in the retrieved-chunk text."
        ),
    )
    empty_min_score = cols[1].number_input(
        "Empty-retrieval min score (0 = ignore)",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        value=float(cfg.empty_retrieval_min_score or 0.0),
        help=(
            "If > 0, responses whose top chunk score is below this floor are "
            "treated as 'empty retrieval'. Set to 0 to ignore the floor and "
            "count any non-empty chunk list as a hit."
        ),
    )
    system_filter_str = cols[2].text_input(
        "Only evaluate systems (comma-separated; blank = all)",
        value=", ".join(cfg.system_filter),
        help=(
            "Restrict evaluation to a subset of `system_name`s present in the "
            "responses. Leave blank to evaluate every system found."
        ),
    )

    try:
        parsed_k = [int(k.strip()) for k in k_values_str.split(",") if k.strip()]
    except ValueError:
        st.error("K cut-offs must be a comma-separated list of integers.")
        parsed_k = list(cfg.k_values)
    system_filter = [s.strip() for s in system_filter_str.split(",") if s.strip()]
    return cfg.model_copy(
        update={
            "relevance_mode": relevance_mode,
            "k_values": parsed_k,
            "length_z_threshold": length_z,
            "groundedness_fuzz_threshold": fuzz_threshold,
            "empty_retrieval_min_score": empty_min_score or None,
            "system_filter": system_filter,
        }
    )


def _response_source_section(
    cfg: RagEvalConfig, app_config: AppConfig
) -> tuple[RagEvalConfig, list[dict]] | None:
    """Render the source-selector. Returns (updated_cfg, parsed_responses) or None."""
    st.subheader("RAG responses")
    source = st.radio(
        "Source",
        options=[RAG_RESPONSE_SOURCE_JSONL, RAG_RESPONSE_SOURCE_ARANGO],
        format_func=lambda v: "JSONL upload" if v == RAG_RESPONSE_SOURCE_JSONL else "Arango collection",
        index=0 if cfg.response_source == RAG_RESPONSE_SOURCE_JSONL else 1,
        horizontal=True,
        help=(
            "JSONL upload is the ad-hoc path — fastest to try. Arango collection "
            "is the persisted path; the RAG team writes responses to a collection "
            "that this app reads on demand."
        ),
    )
    cfg = cfg.model_copy(update={"response_source": source})

    responses: list[dict] = []
    if source == RAG_RESPONSE_SOURCE_JSONL:
        uploaded = st.file_uploader(
            "Upload responses JSONL",
            type=["jsonl", "json", "txt"],
            help=(
                "One JSON object per line. Required fields per row: `system_name`, "
                "`qa_pair_key`, `question`, `retrieved_chunks` (a list of "
                "`{doc_id, rank, score?, text?}`), `answer`."
            ),
        )
        if uploaded is None:
            return cfg, []
        text = uploaded.getvalue().decode("utf-8", errors="replace")
        result = load_jsonl(text.splitlines())
        if result.errors:
            st.session_state[KEY_RAG_LOAD_ERRORS] = [
                f"line {e.line_number}: {e.message}" for e in result.errors[:50]
            ]
            st.warning(
                f"{len(result.errors)} row(s) failed to parse; "
                f"{len(result.responses)} loaded successfully."
            )
        else:
            st.session_state[KEY_RAG_LOAD_ERRORS] = []
        responses = [r.model_dump() for r in result.responses]
        st.caption(
            f"Loaded {len(responses)} responses across "
            f"{len({r['system_name'] for r in responses})} system(s)."
        )
    else:  # Arango
        coll = st.text_input(
            "Arango response collection",
            value=cfg.response_arango_collection,
            help=(
                "Name of the Arango collection holding the RAG responses. The "
                "collection's rows must match the same shape as the JSONL contract."
            ),
        )
        cfg = cfg.model_copy(update={"response_arango_collection": coll})
        if st.button(
            "Load responses from Arango",
            help="Read every response row from the named collection.",
        ):
            try:
                gateway = ArangoGateway(app_config.arango)
                orch = RagEvalOrchestrator(cfg)
                responses_list = orch.load_responses(arango_gateway=gateway)
                responses = [r.model_dump() for r in responses_list]
                st.session_state["_rag_arango_responses"] = responses
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to load Arango responses: {exc}")
        else:
            responses = st.session_state.get("_rag_arango_responses", [])
    return cfg, responses


def _render_system_block(run: RagEvalRun) -> None:
    """Render the per-system KPI cards + drill-down."""
    with st.expander(
        f"System: {run.system_name} — {run.n_responses} responses "
        f"({run.n_matched_goldens} matched goldens)",
        expanded=True,
    ):
        retrieval = run.metrics.retrieval
        generation = run.metrics.generation
        cols = st.columns(5)
        cols[0].metric("MRR", _fmt(retrieval.get("mrr")))
        cols[1].metric(
            "Groundedness",
            _fmt(generation.get("groundedness")),
            help="Fraction of answer sentences supported by retrieved chunk text.",
        )
        cols[2].metric(
            "Citation coverage",
            _fmt(generation.get("citation_coverage")),
            help="Fraction of cited doc ids that the system actually retrieved.",
        )
        cols[3].metric(
            "ROUGE-L F1",
            _fmt(generation.get("rouge_l_f1")),
            help="Mean ROUGE-L F1 against the golden answer.",
        )
        cols[4].metric(
            "Empty retrieval rate",
            _fmt(generation.get("empty_retrieval_rate")),
            help="Fraction of responses where retrieval returned nothing useful.",
        )

        st.write("Retrieval metrics")
        st.dataframe(_dict_to_df(retrieval), use_container_width=True)
        st.write("Generation metrics")
        st.dataframe(_dict_to_df(generation), use_container_width=True)
        st.write("Per-query drill-down")
        st.dataframe(
            pd.DataFrame(run.metrics.per_query), use_container_width=True, hide_index=True
        )


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if isinstance(value, int | float) else "—"


def _dict_to_df(d: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        sorted(([k, v] for k, v in d.items()), key=lambda kv: kv[0]),
        columns=["metric", "value"],
    )


def render_rag_eval_tab() -> None:
    """Entry point — wired into `streamlit_app.main()`."""
    app_config: AppConfig | None = st.session_state.get(KEY_APP_CONFIG)
    if app_config is None:
        st.info(
            "Save an `AppConfig` on the **Configure** tab first — we need Arango "
            "credentials to fetch goldens."
        )
        return

    st.header("RAG Eval")
    st.caption(
        "Compute retrieval + rule-based generation metrics for one or more RAG "
        "systems against the multi-hop golden set. No LLM-as-judge — every score "
        "here is deterministic and cheap."
    )

    cfg = app_config.rag_eval
    goldens = _goldens_section(app_config) or []

    cfg = _configure_run(cfg)
    source_outcome = _response_source_section(cfg, app_config)
    if source_outcome is None:
        return
    cfg, raw_responses = source_outcome

    # Persist any config tweaks back to the AppConfig so they survive reruns.
    st.session_state[KEY_APP_CONFIG] = app_config.model_copy(update={"rag_eval": cfg})

    compute_disabled = not raw_responses or not goldens
    if st.button(
        "Compute metrics",
        disabled=compute_disabled,
        help=(
            "Build qrels from the golden proof_lists, then compute every "
            "configured retrieval + generation metric for each `system_name`. "
            "Requires both goldens and responses to be loaded."
        ),
    ):
        orch = RagEvalOrchestrator(cfg)
        # `raw_responses` came from `model_dump()` so we round-trip through pydantic.
        parsed = [RagResponse.model_validate(r) for r in raw_responses]
        runs = orch.evaluate(goldens, parsed)
        st.session_state[KEY_RAG_EVAL_RUNS] = {r.system_name: r for r in runs}
        st.session_state["_rag_parsed_responses"] = parsed
        st.success(f"Evaluated {len(runs)} system(s).")

    runs_by_system: dict[str, RagEvalRun] = st.session_state.get(KEY_RAG_EVAL_RUNS, {})
    if not runs_by_system:
        st.info("No evaluation runs yet — click **Compute metrics** above.")
        return

    st.divider()
    _render_download_buttons(list(runs_by_system.values()))
    st.divider()
    if len(runs_by_system) >= 2:
        render_comparison(list(runs_by_system.values()))
        st.divider()

    for system_name in sorted(runs_by_system):
        _render_system_block(runs_by_system[system_name])

    if app_config.langfuse.is_configured():
        st.divider()
        _render_langfuse_panel(app_config)


def _render_download_buttons(runs: list[RagEvalRun]) -> None:
    """Two side-by-side download buttons for Excel + JSON exports."""
    cols = st.columns(2)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        export_rag_eval_to_excel(runs, tmp.name)
        with open(tmp.name, "rb") as fh:
            xlsx_bytes = fh.read()
    cols[0].download_button(
        "Download Excel",
        data=xlsx_bytes,
        file_name="rag_eval.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help=(
            "One sheet per evaluated system, plus a Summary tab. Each system "
            "sheet has retrieval metrics, generation metrics, and the "
            "per-query drill-down side by side."
        ),
    )
    json_bytes = json.dumps(
        {r.system_name: json.loads(r.model_dump_json()) for r in runs},
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")
    cols[1].download_button(
        "Download JSON",
        data=json_bytes,
        file_name="rag_eval.json",
        mime="application/json",
        help=(
            "Single JSON file keyed by system_name; matches the in-memory "
            "RagEvalRun schema. Handy for notebooks."
        ),
    )


def _render_langfuse_panel(app_config: AppConfig) -> None:
    """Push / pull LangFuse traces & scores. Rendered only when configured."""
    st.subheader("LangFuse")
    st.caption(
        "Push the evaluated responses to LangFuse so annotators can score them "
        "for faithfulness, relevancy, hallucination, completeness, and coherence "
        "in the LangFuse UI. Pull those scores back here when ready."
    )
    sink = LangFuseSink(app_config.langfuse)
    parsed = st.session_state.get("_rag_parsed_responses", [])
    cols = st.columns(2)
    if cols[0].button(
        "Push responses to LangFuse",
        disabled=not parsed,
        help=(
            "Creates one LangFuse trace per evaluated response so annotators "
            "can rate them. Requires a successful compute run first."
        ),
    ):
        result = sink.push_responses(parsed)
        if result.skipped_reason:
            st.warning(f"LangFuse push skipped: {result.skipped_reason}")
        else:
            st.success(f"Pushed {result.pushed} trace(s) to LangFuse.")
    if cols[1].button(
        "Pull annotator scores",
        help=(
            "Fetch any scores annotators have applied in LangFuse since the "
            "last sync; shown below as a raw table."
        ),
    ):
        result = sink.pull_scores()
        if result.skipped_reason:
            st.warning(f"LangFuse pull skipped: {result.skipped_reason}")
        elif not result.pulled_scores:
            st.info("No scores returned by LangFuse yet.")
        else:
            st.dataframe(pd.DataFrame(result.pulled_scores), use_container_width=True)
