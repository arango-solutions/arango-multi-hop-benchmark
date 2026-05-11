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

Stop flow:

    User clicks "Stop"     ─▶ control.pause()  (worker blocks at next checkpoint)
                              show_stop_modal = True
                              ↓
                          Confirmation modal renders
                              ↓
    Confirm                ─▶ control.request_stop()  → worker exits gracefully
    Cancel                 ─▶ control.resume()         → worker continues
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
from multihop_eval.run_control import RunControl
from multihop_eval.ui.state import (
    KEY_RUN_EVENTS,
    KEY_RUN_RESULT,
    KEY_RUN_STATUS,
    KEY_RUN_THREAD,
    KEY_SHOW_STOP_MODAL,
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

    def runner(cfg: AppConfig, on_event, control: RunControl):
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
        return orchestrator.run(on_event=on_event, control=control)

    return runner


@st.dialog("Stop the run?")
def _stop_run_dialog(control: RunControl) -> None:
    """Confirmation modal shown after the user clicks Stop.

    The run was already paused at the moment we opened this dialog, so the
    pipeline is blocked at its next checkpoint. We commit (request stop) or
    revert (resume) here, then close the modal via `st.rerun()`.
    """
    st.write("Are you sure you want to stop the current run?")
    st.caption(
        "The run is paused while you decide. Any in-flight LLM call will "
        "finish before the pipeline exits."
    )
    cols = st.columns(2)
    if cols[0].button("Confirm stop", type="primary", use_container_width=True):
        control.request_stop()
        st.session_state[KEY_SHOW_STOP_MODAL] = False
        st.session_state[KEY_RUN_STATUS] = "stopping"
        st.rerun()
    if cols[1].button("Cancel", use_container_width=True):
        control.resume()
        st.session_state[KEY_SHOW_STOP_MODAL] = False
        st.session_state[KEY_RUN_STATUS] = "running"
        st.rerun()


def render_run_tab() -> None:
    cfg: AppConfig | None = st.session_state.get("app_config")
    if cfg is None:
        st.warning("Configure the app first (Configure tab) before running.")
        return

    handle: RunHandle | None = st.session_state.get(KEY_RUN_THREAD)
    status: str = st.session_state.get(KEY_RUN_STATUS, "idle")
    modal_open: bool = bool(st.session_state.get(KEY_SHOW_STOP_MODAL, False))

    cols = st.columns([1, 1, 1, 3])
    run_disabled = status in {"running", "paused", "stopping"}
    stop_disabled = status not in {"running"} or handle is None
    reset_disabled = status in {"running", "paused", "stopping"}

    if cols[0].button("Run", type="primary", disabled=run_disabled):
        runner = _build_runner(cfg)
        new_handle = start_run(cfg, runner)
        st.session_state[KEY_RUN_THREAD] = new_handle
        st.session_state[KEY_RUN_STATUS] = "running"
        st.session_state[KEY_RUN_EVENTS] = []
        st.session_state[KEY_RUN_RESULT] = None
        st.session_state[KEY_SHOW_STOP_MODAL] = False
        st.rerun()

    if cols[1].button("Stop", disabled=stop_disabled):
        # Pause the worker right away; modal will let the user commit/revert.
        if handle is not None:
            handle.control.pause()
        st.session_state[KEY_SHOW_STOP_MODAL] = True
        st.session_state[KEY_RUN_STATUS] = "paused"
        st.rerun()

    if cols[2].button("Reset", disabled=reset_disabled):
        st.session_state[KEY_RUN_THREAD] = None
        st.session_state[KEY_RUN_STATUS] = "idle"
        st.session_state[KEY_RUN_EVENTS] = []
        st.session_state[KEY_RUN_RESULT] = None
        st.session_state[KEY_SHOW_STOP_MODAL] = False
        st.rerun()

    cols[3].caption(f"Status: **{status}**")

    if handle is None or status == "idle":
        st.info("Click Run to start a generation pass against the configured cluster(s).")
        return

    new_events = handle.drain_queue()
    if new_events:
        st.session_state[KEY_RUN_EVENTS] = list(handle.events)

    # Open the stop confirmation modal if requested. While the modal is open
    # the worker is paused, so we don't poll/rerun — Streamlit will rerun
    # naturally when the user interacts with the dialog.
    if modal_open:
        _render_progress_and_log(
            handle.events, finished=False, result=None, finished_label="paused"
        )
        _stop_run_dialog(handle.control)
        return

    if handle.status == "done":
        st.session_state[KEY_RUN_STATUS] = "done"
        st.session_state[KEY_RUN_RESULT] = handle.result
        _render_progress_and_log(
            handle.events, finished=True, result=handle.result, finished_label="done"
        )
        st.success(
            f"Run complete. {len(handle.result.accepted) if handle.result else 0} accepted. "
            "Open the Dashboard tab for charts and downloads."
        )
        return

    if handle.status == "stopped":
        st.session_state[KEY_RUN_STATUS] = "stopped"
        st.session_state[KEY_RUN_RESULT] = handle.result
        _render_progress_and_log(
            handle.events, finished=True, result=handle.result, finished_label="stopped"
        )
        accepted_count = len(handle.result.accepted) if handle.result else 0
        st.warning(
            f"Run stopped by user. {accepted_count} accepted before stopping. "
            "Partial results are available on the Dashboard tab."
        )
        return

    if handle.status == "error":
        st.session_state[KEY_RUN_STATUS] = "error"
        st.error(f"Run failed: {handle.error}")
        _render_progress_and_log(
            handle.events, finished=True, result=None, finished_label="error"
        )
        return

    _render_progress_and_log(
        handle.events, finished=False, result=None, finished_label="done"
    )
    time.sleep(POLL_INTERVAL_S)
    st.rerun()


def _render_progress_and_log(
    events: list[RunEvent],
    *,
    finished: bool,
    result: RunResult | None,
    finished_label: str = "done",
) -> None:
    accepted, target = progress_from_events(events)
    if not finished:
        st.progress(min(1.0, accepted / max(1, target)), text=f"{accepted}/{target}")
    else:
        st.progress(1.0, text=finished_label)

    st.markdown("**Live log (most recent first):**")
    log_lines = [event_to_log_line(e) for e in events]
    tail = list(reversed(log_lines[-LOG_TAIL_LINES:]))
    st.code("\n".join(tail) or "(no events yet)", language="text")
    # `result` is reserved for future summary panels (e.g. accept-rate by
    # cluster) when a run is finished — currently unused but kept on the
    # signature so callers don't have to change when we add it.
    _ = result
