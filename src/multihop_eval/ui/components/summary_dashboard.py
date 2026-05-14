"""Dashboard tab — KPI cards, charts, filterable table, downloads."""

from __future__ import annotations

import io
import json
import tempfile

import altair as alt
import pandas as pd
import streamlit as st

from multihop_eval.clients.arango_gateway import ArangoGateway
from multihop_eval.exporters import export_to_excel, export_to_json
from multihop_eval.exporters.json_exporter import export_run_to_json
from multihop_eval.generation.models import AcceptedQA, ProofPoint, RubricScore, RunResult
from multihop_eval.generation.summary import build_summary


def _accepted_to_dataframe(rows: list[AcceptedQA]) -> pd.DataFrame:
    records = []
    for r in rows:
        rec = {
            "cluster_id": r.cluster_id,
            "partition_id": r.partition_id,
            "hop_count": r.hop_count,
            "persona": r.persona,
            "question": r.question,
            "answer": r.answer,
            "proof_count": len(r.proof_list),
            "rubric_weighted_score": r.rubric_weighted_score,
        }
        for fname, score in r.rubric_scores.items():
            rec[f"rubric.{fname}"] = score.score
        records.append(rec)
    return pd.DataFrame(records)


def _kpi_cards(summary, accepted_count: int) -> None:
    cols = st.columns(5)
    cols[0].metric("Accepted", accepted_count)
    cols[1].metric("Rejected", summary.total_rejected)
    cols[2].metric(
        "Accept rate",
        f"{summary.accept_rate * 100:.1f}%" if summary.total_accepted + summary.total_rejected else "—",
    )
    cols[3].metric(
        "Avg hops",
        f"{summary.avg_hop_count:.2f}" if summary.avg_hop_count is not None else "—",
    )
    cols[4].metric(
        "Weighted rubric",
        f"{summary.avg_weighted_rubric:.2f}"
        if summary.avg_weighted_rubric is not None
        else "—",
        help="Average normalised (0..1) weighted score across all rubric fields.",
    )


def _bar_chart(data: dict, x_label: str, y_label: str, *, sort: str = "-y") -> alt.Chart:
    df = pd.DataFrame({x_label: list(data.keys()), y_label: list(data.values())})
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{x_label}:N", sort=sort),
            y=alt.Y(f"{y_label}:Q"),
            tooltip=[x_label, y_label],
        )
        .properties(height=240)
    )


def _result_to_excel_bytes(rows: list[AcceptedQA]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        export_to_excel(rows, tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read()


def _result_to_json_bytes(result: RunResult) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        export_run_to_json(result, tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read()


def _rows_to_json_bytes(rows: list[AcceptedQA]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        export_to_json(rows, tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read()


def _arango_to_accepted(rows_from_arango: list[dict]) -> list[AcceptedQA]:
    out: list[AcceptedQA] = []
    for d in rows_from_arango:
        rubric = {
            k: RubricScore(
                score=float(v.get("score", 0)),
                justification=str(v.get("justification", "")),
            )
            for k, v in (d.get("rubric_scores") or {}).items()
            if isinstance(v, dict)
        }
        proof = [
            ProofPoint(point=p.get("point", ""), source_id=p.get("source_id", ""))
            for p in (d.get("proof") or [])
        ]
        out.append(
            AcceptedQA(
                cluster_id=d.get("cluster_id", ""),
                partition_id=d.get("partition_id", ""),
                hop_count=int(d.get("hop_count", 0) or 0),
                persona=d.get("persona", ""),
                reasoning_chain=d.get("reasoning_chain", ""),
                question=d.get("question", ""),
                answer=d.get("answer", ""),
                proof_list=proof,
                rubric_scores=rubric,
                rubric_weighted_score=d.get("rubric_weighted_score"),
            )
        )
    return out


def render_dashboard_tab() -> None:
    result: RunResult | None = st.session_state.get("run_result")
    cfg = st.session_state.get("app_config")

    source_options = ["This session's run"] + (
        ["ArangoDB QA collection"] if cfg is not None else []
    )
    source = st.radio("Data source", source_options, horizontal=True)

    if source == "This session's run":
        if result is None:
            st.info("No run yet — kick one off in the Run tab.")
            return
        accepted = result.accepted
        full_result = result
    else:
        if cfg is None:
            st.warning("Configure ArangoDB first.")
            return
        try:
            gateway = ArangoGateway(cfg.arango)
            arango_rows = gateway.fetch_qa_rows(limit=1000)
        except Exception as exc:
            st.error(f"Could not fetch from ArangoDB: {exc}")
            return
        accepted = _arango_to_accepted(arango_rows)
        full_result = None

    if not accepted:
        st.info("No accepted QA rows to display.")
        return

    summary = (
        build_summary(full_result) if full_result is not None else _summary_for_rows_only(accepted)
    )

    st.markdown("### Overview")
    _kpi_cards(summary, accepted_count=len(accepted))

    if summary.duration_s is not None:
        st.caption(f"Run duration: {summary.duration_s:.1f}s")

    st.markdown("### Distributions")
    cols = st.columns(2)
    if summary.hop_distribution:
        with cols[0]:
            st.markdown("**Hop count**")
            st.altair_chart(
                _bar_chart(
                    {str(k): v for k, v in sorted(summary.hop_distribution.items())},
                    "hops",
                    "count",
                    sort=None,
                ),
                use_container_width=True,
            )
    if summary.persona_distribution:
        with cols[1]:
            st.markdown("**Persona**")
            st.altair_chart(
                _bar_chart(summary.persona_distribution, "persona", "count"),
                use_container_width=True,
            )

    cols = st.columns(2)
    if summary.cluster_coverage:
        with cols[0]:
            st.markdown("**Cluster coverage**")
            st.altair_chart(
                _bar_chart(summary.cluster_coverage, "cluster", "count"),
                use_container_width=True,
            )
    if summary.rubric_means:
        with cols[1]:
            st.markdown("**Rubric per-field mean (raw scale)**")
            st.altair_chart(
                _bar_chart(
                    {k: round(v, 3) for k, v in summary.rubric_means.items()},
                    "field",
                    "mean_score",
                ),
                use_container_width=True,
            )

    if summary.rejection_breakdown:
        st.markdown("**Rejections by reason**")
        st.altair_chart(
            _bar_chart(summary.rejection_breakdown, "reason", "count"),
            use_container_width=True,
        )

    st.markdown("### Accepted QA pairs")
    df = _accepted_to_dataframe(accepted)
    cols = st.columns([2, 2, 2, 4])
    persona_filter = cols[0].multiselect(
        "Persona", sorted(df["persona"].unique().tolist()), default=[]
    )
    cluster_filter = cols[1].multiselect(
        "Cluster", sorted(df["cluster_id"].unique().tolist()), default=[]
    )
    hop_filter = cols[2].multiselect(
        "Hop count", sorted(df["hop_count"].unique().tolist()), default=[]
    )
    search = cols[3].text_input("Search question text", "")

    filtered = df.copy()
    if persona_filter:
        filtered = filtered[filtered["persona"].isin(persona_filter)]
    if cluster_filter:
        filtered = filtered[filtered["cluster_id"].isin(cluster_filter)]
    if hop_filter:
        filtered = filtered[filtered["hop_count"].isin(hop_filter)]
    if search.strip():
        filtered = filtered[filtered["question"].str.contains(search.strip(), case=False, na=False)]

    st.dataframe(filtered, use_container_width=True, height=420)

    st.markdown("### Downloads")
    cols = st.columns(3)
    cols[0].download_button(
        "Excel (.xlsx)",
        data=_result_to_excel_bytes(accepted),
        file_name="multihop_eval.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    cols[1].download_button(
        "Accepted rows (.json)",
        data=_rows_to_json_bytes(accepted),
        file_name="multihop_eval_rows.json",
        mime="application/json",
    )
    if full_result is not None:
        cols[2].download_button(
            "Full run (.json)",
            data=_result_to_json_bytes(full_result),
            file_name="multihop_eval_run.json",
            mime="application/json",
        )

    with st.expander("Inspect a single QA row"):
        if filtered.empty:
            st.caption("No rows match the current filters.")
        else:
            idx = st.number_input(
                "Row index in filtered table",
                min_value=0,
                max_value=len(filtered) - 1,
                value=0,
            )
            row_idx = filtered.index[int(idx)]
            qa = accepted[row_idx]
            st.markdown(f"**Question:** {qa.question}")
            st.markdown(f"**Answer:** {qa.answer}")
            st.markdown("**Proof:**")
            for p in qa.proof_list:
                st.markdown(f"- `{p.source_id}` — {p.point}")
            if qa.rubric_scores:
                st.markdown("**Rubric scores:**")
                st.json(
                    {
                        k: {"score": v.score, "justification": v.justification}
                        for k, v in qa.rubric_scores.items()
                    }
                )


def _summary_for_rows_only(rows: list[AcceptedQA]):
    """Build a Summary when we only have accepted rows (e.g. from Arango)."""
    from datetime import UTC, datetime

    fake = RunResult(
        accepted=rows,
        rejected=[],
        cluster_targets={r.cluster_id: 0 for r in rows},
        cluster_achieved={r.cluster_id: 1 for r in rows},
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    return build_summary(fake)


# Imported lazily to keep the unused symbol shadow out of `from-imports`.
_ = json  # silence linters about the unused import on some setups.
_ = io
