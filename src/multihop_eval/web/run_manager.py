"""Server-side run plumbing: background thread, event queue, and SSE stream.

This module holds the non-UI threading helpers that used to live in the
Streamlit ``ui/state.py``. The orchestrator runs in a background daemon
thread; it pushes :class:`RunEvent`s into a :class:`queue.Queue` that the
SSE endpoint drains and forwards to the browser as Server-Sent Events.

We never block the event loop on the queue — :meth:`RunHandle.drain_queue`
is non-blocking — so the SSE generator stays responsive even while the
orchestrator is making slow LLM calls.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from multihop_eval.clients.arango_gateway import ArangoGateway
from multihop_eval.clients.llm_client import LLMClient
from multihop_eval.config import AppConfig
from multihop_eval.generation.models import RunEvent, RunResult
from multihop_eval.generation.pipeline import EvaluationOrchestrator
from multihop_eval.generation.rubric_evaluator import RubricEvaluator
from multihop_eval.generation.run_control import RunControl

# How long the SSE generator sleeps between queue drains while a run is live.
SSE_POLL_INTERVAL_S = 0.25


@dataclass
class RunHandle:
    """Container for the in-flight run (thread + queue + accumulator).

    ``control`` is the cooperative pause/stop coordinator the API uses to
    ask the pipeline to stop (when the user clicks Stop).
    """

    thread: threading.Thread | None
    event_queue: queue.Queue[RunEvent]
    control: RunControl = field(default_factory=RunControl)
    events: list[RunEvent] = field(default_factory=list)
    result: RunResult | None = None
    error: BaseException | None = None
    status: str = "running"  # 'running' | 'done' | 'stopped' | 'error'

    def drain_queue(self, max_events: int = 200) -> list[RunEvent]:
        """Pull up to ``max_events`` events off the queue without blocking."""
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
    runner: Callable[[AppConfig, Callable[[RunEvent], None], RunControl], RunResult],
) -> RunHandle:
    """Spawn a daemon thread that calls ``runner(app_config, on_event, control)``.

    ``runner`` is the seam tests and the API both use — it can be a lambda
    that builds the orchestrator and calls ``.run(on_event=..., control=...)``
    or any other function with the same signature.
    """
    q: queue.Queue[RunEvent] = queue.Queue()
    control = RunControl()
    handle = RunHandle(thread=None, event_queue=q, control=control)

    def _push(ev: RunEvent) -> None:
        q.put_nowait(ev)

    def _target() -> None:
        try:
            handle.result = runner(app_config, _push, control)
            handle.status = "stopped" if control.is_stop_requested else "done"
        except BaseException as exc:  # pragma: no cover - happy path tested
            handle.error = exc
            handle.status = "error"

    t = threading.Thread(target=_target, daemon=True)
    handle.thread = t
    t.start()
    return handle


def build_runner(
    config: AppConfig,
) -> Callable[[AppConfig, Callable[[RunEvent], None], RunControl], RunResult]:
    """Closure that constructs the orchestrator and runs it.

    Uses the *real* ``ArangoGateway`` and ``LLMClient`` — this is the BYOC
    happy path. Tests bypass this function and pass fakes to ``start_run``
    directly.
    """

    def runner(cfg: AppConfig, on_event, control: RunControl) -> RunResult:
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


def event_to_log_line(ev: RunEvent) -> str:
    """Render a :class:`RunEvent` as one human-readable log line."""
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
    if ev.kind == "run_stopped":
        return (
            f"{ts}  RUN STOPPED — accepted={p['total_accepted']} "
            f"rejected={p['total_rejected']} duration={p['duration_s']:.1f}s"
        )
    if ev.kind == "error":
        return f"{ts}  error in {p.get('stage', '?')}: {p.get('error', '')}"
    return f"{ts}  {ev.kind}: {p}"


def progress_from_events(events: list[RunEvent]) -> tuple[int, int]:
    """Best-effort ``(accepted, target)`` for a progress bar.

    Returns the most recent ``accepted/target`` we saw on a ``seed`` or
    ``accepted`` event. Falls back to ``(0, 1)`` so the bar exists even if
    no events have arrived yet.
    """
    for ev in reversed(events):
        if ev.kind in ("accepted", "seed"):
            try:
                return int(ev.payload["accepted"]), max(1, int(ev.payload["target"]))
            except (KeyError, TypeError, ValueError):
                continue
    return 0, 1


def event_to_dict(ev: RunEvent) -> dict[str, Any]:
    """Serialise a :class:`RunEvent` for transport over SSE."""
    return {
        "kind": ev.kind,
        "ts": ev.ts.isoformat(),
        "line": event_to_log_line(ev),
        "payload": ev.payload,
    }


def run_result_summary(result: RunResult | None) -> dict[str, Any] | None:
    """Compact, JSON-safe summary of a finished run for the Run tab."""
    if result is None:
        return None
    duration = (result.finished_at - result.started_at).total_seconds()
    return {
        "accepted": len(result.accepted),
        "rejected": len(result.rejected),
        "accept_rate": result.accept_rate,
        "duration_s": duration,
        "cluster_targets": dict(result.cluster_targets),
        "cluster_achieved": dict(result.cluster_achieved),
    }


def run_status_dict(handle: RunHandle | None) -> dict[str, Any]:
    """Snapshot of the current run for ``GET /run/status``."""
    if handle is None:
        return {"status": "idle", "accepted": 0, "target": 0, "summary": None, "error": None}
    accepted, target = progress_from_events(handle.events)
    return {
        "status": handle.status,
        "accepted": accepted,
        "target": target,
        "summary": run_result_summary(handle.result),
        "error": str(handle.error) if handle.error else None,
        "log": [event_to_log_line(e) for e in handle.events],
    }


async def sse_event_stream(handle: RunHandle) -> AsyncIterator[str]:
    """Yield Server-Sent Events for a run until it finishes.

    Each ``RunEvent`` becomes a ``data:`` line carrying the JSON produced by
    :func:`event_to_dict`. When the worker thread finishes and the queue is
    drained, a terminal ``status`` event is emitted and the stream closes.
    """

    def _sse(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, default=str)}\n\n"

    # Replay any events that arrived before the client connected.
    for ev in list(handle.events):
        yield _sse(event_to_dict(ev))

    while True:
        new_events = handle.drain_queue()
        for ev in new_events:
            yield _sse(event_to_dict(ev))

        thread_done = handle.thread is None or not handle.thread.is_alive()
        if thread_done and handle.event_queue.empty():
            # Drain one last time in case events landed between checks.
            for ev in handle.drain_queue():
                yield _sse(event_to_dict(ev))
            yield _sse(
                {
                    "kind": "status",
                    "status": handle.status,
                    "summary": run_result_summary(handle.result),
                    "error": str(handle.error) if handle.error else None,
                }
            )
            return

        await asyncio.sleep(SSE_POLL_INTERVAL_S)
