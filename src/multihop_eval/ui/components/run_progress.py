"""Run tab — kicks off a background run, streams events, then summarises.

Architecture:

    User clicks "Run"  ─▶ start_run() spawns a daemon thread
                          │
                          ▼
                       Orchestrator runs, pushes RunEvents into a Queue
                          │
                          ▼
    Streamlit polls every ~POLL_INTERVAL_S, drains the queue, redraws.

We never block on the queue — `RunHandle.drain_queue` is non-blocking — so
the UI stays responsive even when the orchestrator is making slow LLM calls.
"""

from __future__ import annotations

import time

import streamlit as st

from multihop_eval.arango_gateway import ArangoGateway
from multihop_eval.config import AppConfig
from multihop_eval.llm_client import LLMClient
from multihop_eval.models import RunEvent, RunResult
from multihop_eval.pipeline import EvaluationOrchestrator
from multihop_eval.rubric_evaluator import RubricEvaluator
from multihop_eval.ui.state import (
    KEY_RUN_EVENTS,
    KEY_RUN_RESULT,
    KEY_RUN_STATUS,
    KEY_RUN_THREAD,
    RunHandle,
    event_to_log_line,
    progress_from_events,
    start_run,
)

POLL_INTERVAL_S = 0.5
LOG_TAIL_LINES = 80


def _build_runner(config: AppConfig):
    """Closure that constructs the orchestrator and runs it.

    Uses the *real* `ArangoGateway` and `LLMClient` — this is the BYOC happy
    path. Tests bypass this function and use fakes directly.
    """

    def runner(cfg: AppConfig, on_event):
        gateway = ArangoGateway(cfg.arango)
        llm = LLMClient(cfg.llm)
        rubric_eval = (
            RubricEvaluator(llm, cfg.eval.rubric_fields)
            if cfg.eval.score_with_rubric and cfg.eval.rubric_fields
            else None
        )
        orchestrator = EvaluationOrchestrator(
            gateway=gateway,
            llm=llm,
            eval_config=cfg.eval,
            rubric_evaluator=rubric_eval,
        )
        return orchestrator.run(on_event=on_event)

    return runner


def render_run_tab() -> None:
    cfg: AppConfig | None = st.session_state.get("app_config")
    if cfg is None:
        st.warning("Configure the app first (Configure tab) before running.")
        return

    handle: RunHandle | None = st.session_state.get(KEY_RUN_THREAD)
    status: str = st.session_state.get(KEY_RUN_STATUS, "idle")

    cols = st.columns([1, 1, 3])
    run_disabled = status == "running"
    if cols[0].button("Run", type="primary", disabled=run_disabled):
        runner = _build_runner(cfg)
        new_handle = start_run(cfg, runner)
        st.session_state[KEY_RUN_THREAD] = new_handle
        st.session_state[KEY_RUN_STATUS] = "running"
        st.session_state[KEY_RUN_EVENTS] = []
        st.session_state[KEY_RUN_RESULT] = None
        st.rerun()

    if cols[1].button("Reset", disabled=run_disabled):
        st.session_state[KEY_RUN_THREAD] = None
        st.session_state[KEY_RUN_STATUS] = "idle"
        st.session_state[KEY_RUN_EVENTS] = []
        st.session_state[KEY_RUN_RESULT] = None
        st.rerun()

    cols[2].caption(f"Status: **{status}**")

    if handle is None or status == "idle":
        st.info("Click Run to start a generation pass against the configured cluster(s).")
        return

    new_events = handle.drain_queue()
    if new_events:
        st.session_state[KEY_RUN_EVENTS] = list(handle.events)

    if handle.status == "done":
        st.session_state[KEY_RUN_STATUS] = "done"
        st.session_state[KEY_RUN_RESULT] = handle.result
        _render_progress_and_log(handle.events, finished=True, result=handle.result)
        st.success(
            f"Run complete. {len(handle.result.accepted) if handle.result else 0} accepted. "
            "Open the Dashboard tab for charts and downloads."
        )
        return

    if handle.status == "error":
        st.session_state[KEY_RUN_STATUS] = "error"
        st.error(f"Run failed: {handle.error}")
        _render_progress_and_log(handle.events, finished=True, result=None)
        return

    _render_progress_and_log(handle.events, finished=False, result=None)
    time.sleep(POLL_INTERVAL_S)
    st.rerun()


def _render_progress_and_log(
    events: list[RunEvent],
    *,
    finished: bool,
    result: RunResult | None,
) -> None:
    accepted, target = progress_from_events(events)
    if not finished:
        st.progress(min(1.0, accepted / max(1, target)), text=f"{accepted}/{target}")
    else:
        st.progress(1.0, text="done" if result is not None else "stopped")

    st.markdown("**Live log (most recent first):**")
    log_lines = [event_to_log_line(e) for e in events]
    tail = list(reversed(log_lines[-LOG_TAIL_LINES:]))
    st.code("\n".join(tail) or "(no events yet)", language="text")
