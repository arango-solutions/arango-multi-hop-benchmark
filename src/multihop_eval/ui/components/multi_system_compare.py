"""Side-by-side A/B comparison view for two or more `RagEvalRun`s.

Renders, in order:

  * A grouped bar chart of every retrieval + generation metric across every
    system, so eyeballing wins is one glance.
  * A delta table — for each metric, the best system and the gap to the
    runner-up. Useful for short status reports.

Kept in its own module so the RAG Eval tab itself stays focused on inputs
and per-system drill-downs.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from multihop_eval.rag_eval.models import RagEvalRun
from multihop_eval.ui.theme import avocado_color_scale


def _runs_to_long_df(runs: list[RagEvalRun]) -> pd.DataFrame:
    """Flatten runs into a long-format dataframe: (system, metric, group, value)."""
    rows: list[dict] = []
    for run in runs:
        for metric, value in run.metrics.retrieval.items():
            rows.append(
                {"system": run.system_name, "metric": metric, "group": "retrieval", "value": value}
            )
        for metric, value in run.metrics.generation.items():
            rows.append(
                {"system": run.system_name, "metric": metric, "group": "generation", "value": value}
            )
    return pd.DataFrame(rows)


def _build_delta_table(df: pd.DataFrame) -> pd.DataFrame:
    """For each (group, metric), compute the best system and its gap to second best."""
    rows: list[dict] = []
    for (group, metric), sub in df.groupby(["group", "metric"]):
        ordered = sub.sort_values("value", ascending=False).reset_index(drop=True)
        best = ordered.iloc[0]
        second = ordered.iloc[1] if len(ordered) > 1 else None
        rows.append(
            {
                "group": group,
                "metric": metric,
                "best_system": best["system"],
                "best_value": float(best["value"]),
                "runner_up": second["system"] if second is not None else None,
                "delta": float(best["value"] - second["value"]) if second is not None else None,
            }
        )
    return pd.DataFrame(rows).sort_values(["group", "metric"]).reset_index(drop=True)


def _grouped_bar_chart(df: pd.DataFrame, *, group: str) -> alt.Chart:
    sub = df[df["group"] == group]
    return (
        alt.Chart(sub)
        .mark_bar()
        .encode(
            x=alt.X("metric:N", sort="-y", title="metric"),
            y=alt.Y("value:Q", title="value"),
            color=alt.Color("system:N", title="system", scale=avocado_color_scale()),
            xOffset="system:N",
            tooltip=["system", "metric", alt.Tooltip("value:Q", format=".3f")],
        )
        .properties(height=320)
    )


def render_comparison(runs: list[RagEvalRun]) -> None:
    """Render the A/B chart + delta table for >=2 systems.

    Args:
        runs: Two or more `RagEvalRun`s. With fewer than two we render an
            info banner and bail — the call site is responsible for deciding
            when to invoke this function.
    """
    if len(runs) < 2:
        st.info("Load responses from at least two `system_name`s to enable comparison.")
        return

    st.subheader(f"Comparison across {len(runs)} systems")
    df = _runs_to_long_df(runs)
    if df.empty:
        st.warning("No metrics to compare yet — every run came back empty.")
        return

    cols = st.columns(2)
    with cols[0]:
        st.caption("Retrieval metrics")
        st.altair_chart(_grouped_bar_chart(df, group="retrieval"), use_container_width=True)
    with cols[1]:
        st.caption("Generation metrics")
        st.altair_chart(_grouped_bar_chart(df, group="generation"), use_container_width=True)

    st.caption("Best system per metric (delta to runner-up)")
    st.dataframe(_build_delta_table(df), use_container_width=True, hide_index=True)
