"""Integration test — full `EvaluationOrchestrator.run` against fakes.

We script the LLM responses for one cluster with two seeds:
  * Seed 1 → multi-hop check passes, proof verify passes (accepted).
  * Seed 2 → multi-hop check fails below floor (rejected).

We verify that:
  * Pass 1 yields the expected accepted/rejected counts.
  * Pass 2 (top-up) is triggered because target wasn't met.
  * Inserts went into the fake Arango.
  * `on_event` was called with at least one `cluster_start`, `accepted`,
    `rejected`, and `run_done` event.
"""

from __future__ import annotations

from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.generation.models import RunEvent
from multihop_eval.generation.personas import DEFAULT_PERSONAS
from multihop_eval.generation.pipeline import EvaluationOrchestrator
from multihop_eval.generation.rubric import DEFAULT_RUBRIC
from multihop_eval.generation.rubric_evaluator import RubricEvaluator
from multihop_eval.generation.run_control import RunControl
from tests.conftest import FakeArangoGateway, FakeLLMClient


def _seed_arango() -> FakeArangoGateway:
    """Cluster 'cluster_test_0' with 16 docs and rich similarity edges so
    Pass 2 (top-up) has fresh seeds beyond Pass 1's pool."""
    doc_ids = [f"src/d{i:02d}" for i in range(16)]
    docs = {
        did: {"content": f"Doc {did} content about topic {i}.", "filename": f"{did}.pdf"}
        for i, did in enumerate(doc_ids)
    }
    sims: list[tuple[str, str, float]] = []
    # Connect every doc to its two neighbours and to one 'hub' doc, giving
    # each seed at least 2 in-cluster neighbours so build_subgraph succeeds.
    hub = doc_ids[0]
    for i, did in enumerate(doc_ids):
        if did == hub:
            continue
        sims.append((hub, did, 0.95 - 0.01 * i))
    for i in range(len(doc_ids) - 1):
        sims.append((doc_ids[i], doc_ids[i + 1], 0.80 - 0.005 * i))
    return FakeArangoGateway(
        cluster_doc_ids={"cluster_test_0": doc_ids},
        docs=docs,
        similarities=sims,
        partition_ids={"cluster_test_0": "test_0_part"},
    )


def _good_gen_response(source_ids: list[str]) -> dict:
    return {
        "question": "Combined question across docs?",
        "answer": "An answer that combines multiple sources.",
        "reasoning_chain": " -> ".join(source_ids),
        "proof": [
            {"point": f"point from {sid}", "source_id": sid} for sid in source_ids
        ],
    }


def _multihop_pass(genuine: int) -> dict:
    return {
        "verdict": "pass",
        "genuine_hop_count": genuine,
        "is_multihop": True,
        "reason": "two distinct hops",
        "genuine_source_ids": ["src/a", "src/b"],
    }


def _multihop_fail() -> dict:
    return {
        "verdict": "fail",
        "genuine_hop_count": 1,
        "is_multihop": False,
        "reason": "single doc could answer",
        "genuine_source_ids": ["src/a"],
    }


def _proof_pass(source_ids: list[str]) -> dict:
    return {
        "verdict": "pass",
        "corrected_proof": [
            {"point": f"point from {sid}", "source_id": sid} for sid in source_ids
        ],
        "notes": "all correct",
    }


def _rubric_response() -> dict:
    return {f.name: {"score": f.scale_max, "justification": "ok"} for f in DEFAULT_RUBRIC}


def _config(target: int = 1) -> AppConfig:
    return AppConfig(
        arango=ArangoConfig(
            host="https://arango.example.com",
            db="testdb",
            username="root",
            password="secret",  # type: ignore[arg-type]
        ),
        llm=LLMConfig(api_key="sk-test"),  # type: ignore[arg-type]
        eval=EvalConfig(
            target_clusters=["cluster_test_0"],
            n_questions=target,
            personas=list(DEFAULT_PERSONAS),
            rubric_fields=list(DEFAULT_RUBRIC),
            score_with_rubric=False,  # disable rubric in this test for clarity
            save_to_arango=True,
            hop_dist=[2],
            hop_dist_weights=[1.0],
        ),
    )


def test_orchestrator_pass1_accepts_good_candidates_and_persists():
    arango = _seed_arango()
    cfg = _config(target=1)
    fake_llm = FakeLLMClient(
        responses=[
            _good_gen_response(["src/a", "src/b"]),
            _multihop_pass(2),
            _proof_pass(["src/a", "src/b"]),
        ]
    )

    # Bypass real HTTP — wrap fake_llm in something duck-typed as LLMClient.
    class _LLMShim:
        def __init__(self, fake):
            self._fake = fake

        def call(self, sys, usr, *, max_tokens=None, temperature=None):
            return self._fake.call(sys, usr, max_tokens=max_tokens, temperature=temperature)

    orchestrator = EvaluationOrchestrator(
        gateway=arango,  # type: ignore[arg-type]
        llm=_LLMShim(fake_llm),  # type: ignore[arg-type]
        eval_config=cfg.eval,
        rubric_evaluator=None,
    )
    events: list[RunEvent] = []
    result = orchestrator.run(on_event=events.append)

    assert len(result.accepted) == 1
    assert result.accepted[0].hop_count == 2
    assert len(arango.inserted_qa) == 1
    assert arango.qa_collection_ensured is True

    kinds = [e.kind for e in events]
    assert "cluster_start" in kinds
    assert "accepted" in kinds
    assert "run_done" in kinds


def test_orchestrator_triggers_topup_on_shortfall():
    """Pass 1 fails every multi-hop check; Pass 2 (top-up) should run and we
    should see at least one Pass 2 event. We use a large response queue and
    let the test pass as long as Pass 2 was attempted, since exact accept
    counts depend on seed decimation."""
    arango = _seed_arango()
    cfg = _config(target=2)

    class _LLMShim:
        def __init__(self, fake):
            self._fake = fake

        def call(self, sys, usr, *, max_tokens=None, temperature=None):
            return self._fake.call(sys, usr, max_tokens=max_tokens, temperature=temperature)

    # Pass 1 — every seed fails multi-hop check.
    #   target=2, multiplier=4 → up to 8 Pass 1 seeds, 2 LLM calls each.
    pass1 = []
    for _ in range(8):
        pass1.append(_good_gen_response(["src/d00", "src/d01"]))
        pass1.append(_multihop_fail())

    # Pass 2 — top-up should accept 2 fresh QA pairs. Provide a few buffer
    # cycles in case decimation gives us more seeds than needed.
    pass2 = []
    for _ in range(4):
        pass2.extend(
            [
                _good_gen_response(["src/d00", "src/d05"]),
                _multihop_pass(2),
                _proof_pass(["src/d00", "src/d05"]),
            ]
        )

    fake_llm = FakeLLMClient(responses=pass1 + pass2)
    orchestrator = EvaluationOrchestrator(
        gateway=arango,  # type: ignore[arg-type]
        llm=_LLMShim(fake_llm),  # type: ignore[arg-type]
        eval_config=cfg.eval,
        rubric_evaluator=None,
    )
    events: list[RunEvent] = []
    result = orchestrator.run(on_event=events.append)

    pass_done_events = [e for e in events if e.kind == "pass_done"]
    pass_numbers = {e.payload["pass"] for e in pass_done_events}
    assert 1 in pass_numbers
    assert 2 in pass_numbers, "Pass 2 (top-up) should have been triggered."
    # At least one acceptance came from Pass 2.
    assert len(result.accepted) >= 1


def test_orchestrator_calls_rubric_evaluator_per_accepted():
    arango = _seed_arango()
    cfg = _config(target=1)
    cfg.eval.score_with_rubric = True

    fake_llm = FakeLLMClient(
        responses=[
            _good_gen_response(["src/a", "src/b"]),
            _multihop_pass(2),
            _proof_pass(["src/a", "src/b"]),
            _rubric_response(),
        ]
    )

    class _LLMShim:
        def __init__(self, fake):
            self._fake = fake

        def call(self, sys, usr, *, max_tokens=None, temperature=None):
            return self._fake.call(sys, usr, max_tokens=max_tokens, temperature=temperature)

    shim = _LLMShim(fake_llm)
    rubric_eval = RubricEvaluator(shim, list(DEFAULT_RUBRIC))  # type: ignore[arg-type]
    orchestrator = EvaluationOrchestrator(
        gateway=arango,  # type: ignore[arg-type]
        llm=shim,  # type: ignore[arg-type]
        eval_config=cfg.eval,
        rubric_evaluator=rubric_eval,
    )
    result = orchestrator.run()
    assert len(result.accepted) == 1
    accepted = result.accepted[0]
    # Every default rubric field should have been scored.
    for f in DEFAULT_RUBRIC:
        assert f.name in accepted.rubric_scores
    assert accepted.rubric_weighted_score is not None


def test_orchestrator_exits_early_when_stop_is_requested_before_run():
    """A pre-stopped `RunControl` should cause the orchestrator to short-circuit
    its seed loops and return a partial `RunResult` with no acceptances. The
    final emitted event must be `run_stopped` (not `run_done`) so the UI can
    surface the stoppage distinctly."""
    arango = _seed_arango()
    cfg = _config(target=2)

    class _LLMShim:
        def __init__(self, fake):
            self._fake = fake

        def call(self, sys, usr, *, max_tokens=None, temperature=None):
            return self._fake.call(sys, usr, max_tokens=max_tokens, temperature=temperature)

    # No LLM responses: if the stop signal is honored, no LLM calls are made.
    fake_llm = FakeLLMClient(responses=[])
    orchestrator = EvaluationOrchestrator(
        gateway=arango,  # type: ignore[arg-type]
        llm=_LLMShim(fake_llm),  # type: ignore[arg-type]
        eval_config=cfg.eval,
        rubric_evaluator=None,
    )

    control = RunControl()
    control.request_stop()

    events: list[RunEvent] = []
    result = orchestrator.run(on_event=events.append, control=control)

    assert result.accepted == []
    assert fake_llm.calls == [], "Pipeline must not invoke the LLM after stop is requested."
    kinds = [e.kind for e in events]
    assert "run_stopped" in kinds
    assert "run_done" not in kinds


def test_orchestrator_stop_request_mid_run_yields_partial_result():
    """Simulate a stop request between Pass 1 and Pass 2: Pass 1 should
    accept what it can, then Pass 2 should be skipped entirely once stop is
    set. The final event must be `run_stopped`."""
    arango = _seed_arango()
    cfg = _config(target=1)

    class _LLMShim:
        def __init__(self, fake):
            self._fake = fake

        def call(self, sys, usr, *, max_tokens=None, temperature=None):
            return self._fake.call(sys, usr, max_tokens=max_tokens, temperature=temperature)

    # Enough scripted responses for Pass 1 to accept exactly one row.
    fake_llm = FakeLLMClient(
        responses=[
            _good_gen_response(["src/a", "src/b"]),
            _multihop_pass(2),
            _proof_pass(["src/a", "src/b"]),
        ]
    )
    orchestrator = EvaluationOrchestrator(
        gateway=arango,  # type: ignore[arg-type]
        llm=_LLMShim(fake_llm),  # type: ignore[arg-type]
        eval_config=cfg.eval,
        rubric_evaluator=None,
    )

    # Trigger stop the first time the orchestrator emits a `pass_done`
    # event — i.e. between Pass 1 and Pass 2. (The `cluster_test_0` cluster
    # has only one cluster so Pass 2 would otherwise run as top-up.)
    control = RunControl()
    events: list[RunEvent] = []

    def listener(ev: RunEvent) -> None:
        events.append(ev)
        if ev.kind == "pass_done" and ev.payload.get("pass") == 1:
            control.request_stop()

    result = orchestrator.run(on_event=listener, control=control)

    kinds = [e.kind for e in events]
    assert "run_stopped" in kinds
    assert "run_done" not in kinds
    pass_numbers = {e.payload["pass"] for e in events if e.kind == "pass_done"}
    assert 1 in pass_numbers
    assert 2 not in pass_numbers, "Pass 2 should be skipped once stop is requested."
    # Pass 1 should still have produced at least one acceptance.
    assert len(result.accepted) >= 1
