"""Tests for `multihop_eval.ui.state` — the queue/thread + log helpers."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.models import (
    AcceptedQA,
    ProofPoint,
    RunEvent,
    RunResult,
)
from multihop_eval.personas import DEFAULT_PERSONAS
from multihop_eval.rubric import DEFAULT_RUBRIC
from multihop_eval.ui.state import (
    event_to_log_line,
    progress_from_events,
    start_run,
)


def _cfg() -> AppConfig:
    return AppConfig(
        arango=ArangoConfig(host="https://x.example.com", db="d", password="p"),  # type: ignore[arg-type]
        llm=LLMConfig(api_key="sk"),  # type: ignore[arg-type]
        eval=EvalConfig(
            personas=list(DEFAULT_PERSONAS),
            rubric_fields=list(DEFAULT_RUBRIC),
        ),
    )


def test_progress_from_events_uses_most_recent_seed_or_accepted():
    events = [
        RunEvent(kind="cluster_start", payload={"cluster_id": "c", "doc_count": 4, "target": 5}),
        RunEvent(kind="seed", payload={"seed_idx": 1, "seed_doc_id": "s", "neighbors": 1, "target_size": 2, "accepted": 1, "target": 5, "global_so_far": 1}),
        RunEvent(kind="accepted", payload={"hop_count": 2, "question": "q", "persona": "p", "accepted": 2, "target": 5, "global_so_far": 2}),
    ]
    accepted, target = progress_from_events(events)
    assert accepted == 2
    assert target == 5


def test_progress_from_events_falls_back_to_zero_when_no_data():
    accepted, target = progress_from_events([])
    assert accepted == 0
    assert target >= 1


def test_event_to_log_line_renders_each_kind():
    samples = [
        RunEvent(kind="cluster_start", payload={"cluster_id": "c", "doc_count": 5, "target": 3, "topup": False}),
        RunEvent(kind="seed", payload={"seed_idx": 1, "seed_doc_id": "src/aaa", "neighbors": 2, "target_size": 3, "accepted": 0, "target": 3, "global_so_far": 0}),
        RunEvent(kind="accepted", payload={"hop_count": 2, "question": "q?", "persona": "p", "accepted": 1, "target": 3, "global_so_far": 1}),
        RunEvent(kind="rejected", payload={"seed_doc_id": "src/bbb", "reason": "multihop_below_floor"}),
        RunEvent(kind="pass_done", payload={"pass": 1, "total_accepted": 5}),
        RunEvent(kind="run_done", payload={"total_accepted": 5, "total_rejected": 2, "duration_s": 12.34}),
        RunEvent(kind="error", payload={"stage": "rubric", "error": "oops"}),
    ]
    for ev in samples:
        line = event_to_log_line(ev)
        assert isinstance(line, str)
        assert len(line) > 0


def test_start_run_executes_runner_and_returns_result():
    finished_result = RunResult(
        accepted=[
            AcceptedQA(
                cluster_id="c",
                partition_id="p",
                hop_count=2,
                persona="domain_expert",
                reasoning_chain="r",
                question="q?",
                answer="a.",
                proof_list=[ProofPoint("x", "src/a"), ProofPoint("y", "src/b")],
            )
        ],
        rejected=[],
        cluster_targets={"c": 1},
        cluster_achieved={"c": 1},
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )

    def runner(cfg, on_event):
        on_event(RunEvent(kind="run_done", payload={"total_accepted": 1, "total_rejected": 0, "duration_s": 0.1}))
        return finished_result

    handle = start_run(_cfg(), runner)

    deadline = time.time() + 2.0
    while handle.thread.is_alive() and time.time() < deadline:
        time.sleep(0.01)
    assert handle.status == "done"
    assert handle.result is finished_result
    drained = handle.drain_queue()
    assert any(e.kind == "run_done" for e in drained)


def test_start_run_records_error_when_runner_raises():
    def runner(cfg, on_event):
        raise RuntimeError("boom")

    handle = start_run(_cfg(), runner)
    deadline = time.time() + 2.0
    while handle.thread.is_alive() and time.time() < deadline:
        time.sleep(0.01)
    assert handle.status == "error"
    assert isinstance(handle.error, RuntimeError)
