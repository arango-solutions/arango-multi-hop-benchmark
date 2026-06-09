"""Unit tests for the server-side run plumbing (thread, queue, SSE).

These cover the helpers that moved out of the old Streamlit ``ui/state.py``
plus the new SSE serialisation, exercising the fake-runner seam that
``start_run`` exposes (no real Arango/LLM needed).
"""

from __future__ import annotations

import asyncio
import queue
from datetime import UTC, datetime

from multihop_eval.generation.models import AcceptedQA, RunEvent, RunResult
from multihop_eval.generation.run_control import RunControl
from multihop_eval.web.run_manager import (
    RunHandle,
    event_to_dict,
    event_to_log_line,
    progress_from_events,
    run_result_summary,
    run_status_dict,
    sse_event_stream,
    start_run,
)


def _accepted() -> AcceptedQA:
    return AcceptedQA(
        cluster_id="cluster_0",
        partition_id="p",
        hop_count=2,
        persona="analyst",
        reasoning_chain="because",
        question="q?",
        answer="a",
        proof_list=[],
    )


def _result(n_accepted: int = 1) -> RunResult:
    now = datetime.now(UTC)
    return RunResult(
        accepted=[_accepted() for _ in range(n_accepted)],
        rejected=[],
        cluster_targets={"cluster_0": 1},
        cluster_achieved={"cluster_0": n_accepted},
        started_at=now,
        finished_at=now,
    )


def test_event_to_log_line_accepted() -> None:
    ev = RunEvent(
        kind="accepted",
        payload={"hop_count": 2, "persona": "analyst", "accepted": 1, "target": 5, "question": "Why?"},
    )
    line = event_to_log_line(ev)
    assert "ACCEPTED" in line
    assert "1/5" in line


def test_progress_from_events_uses_latest() -> None:
    events = [
        RunEvent(kind="seed", payload={"accepted": 1, "target": 10}),
        RunEvent(kind="accepted", payload={"accepted": 3, "target": 10}),
    ]
    assert progress_from_events(events) == (3, 10)
    assert progress_from_events([]) == (0, 1)


def test_event_to_dict_is_json_safe() -> None:
    ev = RunEvent(kind="tick", payload={"x": 1})
    d = event_to_dict(ev)
    assert d["kind"] == "tick"
    assert d["payload"] == {"x": 1}
    assert isinstance(d["ts"], str)


def test_run_result_summary() -> None:
    assert run_result_summary(None) is None
    summary = run_result_summary(_result(n_accepted=2))
    assert summary is not None
    assert summary["accepted"] == 2
    assert summary["accept_rate"] == 1.0


def test_run_status_dict_idle_when_no_handle() -> None:
    assert run_status_dict(None)["status"] == "idle"


def test_start_run_completes_done() -> None:
    def runner(cfg, on_event, control):  # noqa: ANN001, ARG001
        on_event(RunEvent(kind="tick", payload={}))
        return _result()

    handle = start_run("cfg", runner)  # type: ignore[arg-type]
    handle.thread.join(timeout=5)  # type: ignore[union-attr]
    assert handle.status == "done"
    drained = handle.drain_queue()
    assert any(e.kind == "tick" for e in drained)


def test_start_run_stopped_when_stop_requested() -> None:
    def runner(cfg, on_event, control: RunControl):  # noqa: ANN001, ARG001
        control.request_stop()
        return _result()

    handle = start_run("cfg", runner)  # type: ignore[arg-type]
    handle.thread.join(timeout=5)  # type: ignore[union-attr]
    assert handle.status == "stopped"


def test_start_run_error_captured() -> None:
    def runner(cfg, on_event, control):  # noqa: ANN001, ARG001
        raise RuntimeError("boom")

    handle = start_run("cfg", runner)  # type: ignore[arg-type]
    handle.thread.join(timeout=5)  # type: ignore[union-attr]
    assert handle.status == "error"
    assert isinstance(handle.error, RuntimeError)


def test_sse_event_stream_yields_events_and_terminal_status() -> None:
    q: queue.Queue[RunEvent] = queue.Queue()
    q.put(RunEvent(kind="tick", payload={"n": 1}))
    handle = RunHandle(thread=None, event_queue=q)
    handle.status = "done"
    handle.result = _result()

    async def _collect() -> list[str]:
        return [chunk async for chunk in sse_event_stream(handle)]

    chunks = asyncio.run(_collect())
    body = "".join(chunks)
    assert body.count("data:") >= 2  # the tick event + terminal status
    assert '"kind": "tick"' in body
    assert '"kind": "status"' in body
    assert '"status": "done"' in body
