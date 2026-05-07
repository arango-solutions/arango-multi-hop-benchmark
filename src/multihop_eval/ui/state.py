"""Streamlit session-state helpers + background-run plumbing.

Streamlit reruns the script on every interaction, so all long-lived state
(the in-progress run, its event queue, its result, ...) lives in
`st.session_state` keyed by the helpers in this module.

The orchestrator runs in a background thread; it pushes `RunEvent`s into a
`queue.Queue` that the UI drains on every poll cycle. We never block the
main Streamlit thread on a queue.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from multihop_eval.config import AppConfig
from multihop_eval.models import RunEvent, RunResult

# Streamlit session-state keys — keep them in one place to avoid typos.
KEY_APP_CONFIG = "app_config"
KEY_RUN_THREAD = "run_thread"
KEY_RUN_QUEUE = "run_queue"
KEY_RUN_RESULT = "run_result"
KEY_RUN_ERROR = "run_error"
KEY_RUN_EVENTS = "run_events"
KEY_RUN_STATUS = "run_status"  # 'idle' | 'running' | 'done' | 'error'


@dataclass
class RunHandle:
    """Container for the in-flight run (thread + queue + accumulator).

    Stored on `st.session_state` as a single value so we don't pollute the
    namespace with five keys per run.
    """

    thread: threading.Thread
    event_queue: queue.Queue[RunEvent]
    events: list[RunEvent] = field(default_factory=list)
    result: RunResult | None = None
    error: BaseException | None = None
    status: str = "running"

    def drain_queue(self, max_events: int = 200) -> list[RunEvent]:
        """Pull up to `max_events` events off the queue without blocking."""
        new_events: list[RunEvent] = []
        for _ in range(max_events):
            try:
                ev = self.event_queue.get_nowait()
            except queue.Empty:
                break
            new_events.append(ev)
            self.events.append(ev)
        return new_events


def start_run(
    app_config: AppConfig,
    runner: Callable[[AppConfig, Callable[[RunEvent], None]], RunResult],
) -> RunHandle:
    """Spawn a daemon thread that calls `runner(app_config, on_event)`.

    `runner` is the seam tests and the UI both use — it can be a lambda that
    builds the orchestrator and calls `.run(on_event=...)` or any other
    function with the same signature.
    """
    q: queue.Queue[RunEvent] = queue.Queue()
    handle = RunHandle(thread=None, event_queue=q)  # type: ignore[arg-type]

    def _push(ev: RunEvent) -> None:
        q.put_nowait(ev)

    def _target() -> None:
        try:
            handle.result = runner(app_config, _push)
            handle.status = "done"
        except BaseException as exc:  # pragma: no cover - happy path tested
            handle.error = exc
            handle.status = "error"

    t = threading.Thread(target=_target, daemon=True)
    handle.thread = t
    t.start()
    return handle


def event_to_log_line(ev: RunEvent) -> str:
    """Render a `RunEvent` as one human-readable log line for the UI."""
    p = ev.payload
    ts = ev.ts.strftime("%H:%M:%S")
    if ev.kind == "cluster_start":
        return (
            f"{ts}  Cluster {p['cluster_id']}: docs={p['doc_count']} "
            f"target={p['target']}{' [TOP-UP]' if p.get('topup') else ''}"
        )
    if ev.kind == "seed":
        return (
            f"{ts}  Seed {p['seed_idx']} ({p['seed_doc_id'][-20:]}) | "
            f"nbrs={p['neighbors']} size={p['target_size']} | "
            f"{p['accepted']}/{p['target']} (global {p['global_so_far']})"
        )
    if ev.kind == "accepted":
        q = p["question"]
        return (
            f"{ts}  ACCEPTED [{p['hop_count']}-hop, {p['persona']}] "
            f"{p['accepted']}/{p['target']}: {q[:80]}"
        )
    if ev.kind == "rejected":
        return f"{ts}  rejected ({p['reason']}): seed={p['seed_doc_id'][-20:]}"
    if ev.kind == "pass_done":
        return f"{ts}  Pass {p['pass']} done — {p['total_accepted']} accepted so far."
    if ev.kind == "run_done":
        return (
            f"{ts}  RUN COMPLETE — accepted={p['total_accepted']} "
            f"rejected={p['total_rejected']} duration={p['duration_s']:.1f}s"
        )
    if ev.kind == "error":
        return f"{ts}  error in {p.get('stage','?')}: {p.get('error','')}"
    return f"{ts}  {ev.kind}: {p}"


def progress_from_events(events: list[RunEvent]) -> tuple[int, int]:
    """Best-effort (accepted, target) for a progress bar.

    Returns the most recent `accepted/target` we saw on a `seed` or
    `accepted` event. Falls back to (0, 1) so the bar exists even if no
    events have arrived yet.
    """
    for ev in reversed(events):
        if ev.kind in ("accepted", "seed"):
            try:
                return int(ev.payload["accepted"]), max(1, int(ev.payload["target"]))
            except (KeyError, TypeError, ValueError):
                continue
    return 0, 1


def init_session_state(st_module: Any) -> None:
    """Initialise default session-state values if not yet set.

    Takes the `streamlit` module as argument so this helper stays unit-testable
    without importing streamlit at module scope.
    """
    defaults: dict[str, Any] = {
        KEY_APP_CONFIG: None,
        KEY_RUN_THREAD: None,
        KEY_RUN_RESULT: None,
        KEY_RUN_ERROR: None,
        KEY_RUN_EVENTS: [],
        KEY_RUN_STATUS: "idle",
    }
    for k, v in defaults.items():
        if k not in st_module.session_state:
            st_module.session_state[k] = v
