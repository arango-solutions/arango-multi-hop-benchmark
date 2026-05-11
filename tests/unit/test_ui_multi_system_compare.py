"""Unit tests for the pure helpers in `ui/components/multi_system_compare`.

The Streamlit-rendering function `render_comparison` itself isn't tested
because it requires an active Streamlit script context; the helpers it
depends on (`_runs_to_long_df`, `_build_delta_table`) are pure pandas
transforms and tested here.
"""

from __future__ import annotations

import pytest

from multihop_eval.rag_eval.models import RagEvalRun, RagMetricBundle
from multihop_eval.ui.components.multi_system_compare import (
    _build_delta_table,
    _runs_to_long_df,
)


def _run(
    *,
    system_name: str,
    retrieval: dict[str, float],
    generation: dict[str, float],
) -> RagEvalRun:
    return RagEvalRun(
        system_name=system_name,
        n_responses=10,
        n_matched_goldens=10,
        metrics=RagMetricBundle(retrieval=retrieval, generation=generation),
    )


def test_runs_to_long_df_includes_every_metric_per_system():
    runs = [
        _run(
            system_name="rag_a",
            retrieval={"precision@1": 0.9, "mrr": 0.8},
            generation={"rouge_l_f1": 0.5},
        ),
        _run(
            system_name="rag_b",
            retrieval={"precision@1": 0.4, "mrr": 0.3},
            generation={"rouge_l_f1": 0.7},
        ),
    ]
    df = _runs_to_long_df(runs)
    # 2 systems x 3 metrics = 6 rows
    assert len(df) == 6
    assert set(df["system"]) == {"rag_a", "rag_b"}
    assert set(df["metric"]) == {"precision@1", "mrr", "rouge_l_f1"}
    assert set(df["group"]) == {"retrieval", "generation"}


def test_runs_to_long_df_empty_runs_yield_empty_df():
    df = _runs_to_long_df([])
    assert df.empty


def test_delta_table_marks_best_and_gap_to_runner_up():
    runs = [
        _run(system_name="rag_a", retrieval={"mrr": 0.9}, generation={"rouge_l_f1": 0.5}),
        _run(system_name="rag_b", retrieval={"mrr": 0.6}, generation={"rouge_l_f1": 0.8}),
    ]
    long_df = _runs_to_long_df(runs)
    delta = _build_delta_table(long_df)
    mrr_row = delta[delta["metric"] == "mrr"].iloc[0]
    rouge_row = delta[delta["metric"] == "rouge_l_f1"].iloc[0]
    assert mrr_row["best_system"] == "rag_a"
    assert mrr_row["runner_up"] == "rag_b"
    assert mrr_row["delta"] == pytest.approx(0.3)
    assert rouge_row["best_system"] == "rag_b"
    assert rouge_row["delta"] == pytest.approx(0.3)


def test_delta_table_handles_single_system_gracefully():
    runs = [
        _run(system_name="solo", retrieval={"mrr": 0.5}, generation={"rouge_l_f1": 0.5}),
    ]
    df = _runs_to_long_df(runs)
    delta = _build_delta_table(df)
    # Best system named, runner-up + delta are None.
    assert (delta["runner_up"].isna()).all()
    assert (delta["delta"].isna()).all()
    assert set(delta["best_system"]) == {"solo"}
