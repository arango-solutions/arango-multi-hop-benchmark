"""End-to-end generation pipeline.

Three layered classes:

* `GenerationPipeline.attempt(...)` — generate → multi-hop check → proof
  verify on a single subgraph. Returns either an `AcceptedQA` or a
  `RejectionReason` describing why the candidate was discarded.

* `ClusterProcessor.process(...)` — iterate seeds in a cluster, build
  subgraphs, call `GenerationPipeline.attempt`, and stop once the cluster
  target is met.

* `EvaluationOrchestrator.run(...)` — drive Pass 1 (main generation) +
  Pass 2 (top-up for shortfalls), call the optional rubric judge per
  accepted row, persist to ArangoDB if configured, and emit `RunEvent`s
  through the user-supplied `on_event` callback for the live UI log.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from multihop_eval.clients.llm_client import (
    ContextLengthError,
    LLMClient,
    extract_json,
    strip_citations,
)
from multihop_eval.config import EvalConfig
from multihop_eval.generation.models import (
    AcceptedQA,
    ProofPoint,
    RejectedQA,
    RejectionReason,
    RunEvent,
    RunResult,
)
from multihop_eval.generation.personas import Persona
from multihop_eval.generation.prompts import (
    SYSTEM_PROMPT_GEN,
    SYSTEM_PROMPT_MULTIHOP_CHECK,
    SYSTEM_PROMPT_VERIFY,
    build_gen_prompt,
    build_multihop_check_prompt,
    build_verify_prompt,
)
from multihop_eval.generation.rubric_evaluator import RubricEvaluator
from multihop_eval.generation.run_control import RunControl
from multihop_eval.generation.subgraph import build_subgraph, pick_subgraph_size

log = logging.getLogger(__name__)

OnEvent = Callable[[RunEvent], None]


class _GatewayProtocol(Protocol):
    """The subset of `ArangoGateway` the pipeline depends on."""

    def get_cluster_doc_ids(self, cluster_id: str) -> list[str]: ...
    def get_partition_id(self, cluster_id: str) -> str: ...
    def get_seed_docs(self, cluster_id: str, n_seeds: int) -> list[str]: ...
    def get_all_neighbors(self, seed_doc_id: str) -> list[dict[str, Any]]: ...
    def fetch_doc_contents(self, doc_ids: list[str]) -> list[dict[str, Any]]: ...
    def get_inter_edges(self, doc_ids: list[str]) -> list[tuple[str, str, float]]: ...
    def ensure_qa_collection(self) -> None: ...
    def insert_qa_row(self, row: dict[str, Any]) -> None: ...


# ============================================================
# Generation pipeline (one subgraph → one candidate)
# ============================================================


class GenerationPipeline:
    """Runs generate → multi-hop check → proof verify on one subgraph."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        max_verify_rounds: int = 3,
        domains_collection: str = "multihop_eval_domains",
    ) -> None:
        self.llm = llm
        self.max_verify_rounds = max_verify_rounds
        self.domains_collection = domains_collection

    def attempt(
        self,
        *,
        cluster_id_short: str,
        partition_id: str,
        docs: list[dict[str, Any]],
        edges: list[tuple[str, str, float]],
        persona: Persona,
        question_index: int,
        min_genuine_hops: int | None = None,
    ) -> AcceptedQA | RejectionReason:
        """Generate one candidate QA from this subgraph and validate it."""
        required_hops = len(docs)
        content_blob = _build_content_blob(docs)
        full_cluster_id = (
            cluster_id_short
            if "/" in cluster_id_short
            else f"{self.domains_collection}/{cluster_id_short}"
        )

        # 1) Generation
        try:
            raw = self.llm.call(
                SYSTEM_PROMPT_GEN,
                build_gen_prompt(full_cluster_id, docs, edges, persona, required_hops),
            )
            item = extract_json(raw)
        except ContextLengthError:
            raise  # caller decides whether to shrink
        except Exception as exc:
            log.error("Generation LLM error: %s", exc)
            return RejectionReason.LLM_GEN_ERROR

        for key in ("question", "answer", "proof"):
            if key not in item:
                log.warning("LLM output missing key %r", key)
                return RejectionReason.MISSING_KEY

        question = item["question"]
        answer = strip_citations(item["answer"])
        proof: list[dict[str, Any]] = list(item["proof"])
        reasoning_chain = item.get("reasoning_chain", "")
        log.info("[Q%d] Generated (%d-hop)", question_index, required_hops)

        # 2) Multi-hop check
        try:
            passed, genuine_hops, mh_reason = self._check_multihop(
                question, answer, reasoning_chain, proof, required_hops, content_blob
            )
        except Exception as exc:
            log.error("Multi-hop check failed: %s", exc)
            return RejectionReason.UNEXPECTED_ERROR
        log.info(
            "Multi-hop: %s | genuine=%d/%d | %s",
            "PASS" if passed else "FAIL",
            genuine_hops,
            required_hops,
            mh_reason,
        )

        hop_floor = min_genuine_hops if min_genuine_hops is not None else required_hops
        if not passed:
            if genuine_hops < hop_floor:
                log.warning("Rejected: %d genuine hops < floor %d.", genuine_hops, hop_floor)
                return RejectionReason.MULTIHOP_BELOW_FLOOR
            log.info("Downgraded: %d-hop -> %d-hop.", required_hops, genuine_hops)
            required_hops = genuine_hops

        # 3) Proof verification (with up to max_verify_rounds correction loops)
        verdict = "fail"
        for rnd in range(1, self.max_verify_rounds + 1):
            log.info("[Q%d] Proof verification round %d/%d", question_index, rnd, self.max_verify_rounds)
            try:
                verdict, proof = self._verify_and_correct_proof(
                    question, answer, proof, content_blob
                )
            except Exception as exc:
                log.error("Proof verification call failed: %s", exc)
                return RejectionReason.UNEXPECTED_ERROR
            log.info("Proof: %s", verdict)
            if verdict == "pass":
                break

        if verdict != "pass":
            log.warning("Proof verification failed after %d rounds.", self.max_verify_rounds)
            return RejectionReason.PROOF_VERIFY_FAILED

        distinct_sources = {p.get("source_id", "") for p in proof if p.get("source_id")}
        if len(distinct_sources) < 2:
            log.warning("Post-correction proof collapsed to <2 sources.")
            return RejectionReason.PROOF_COLLAPSED_TO_ONE_SOURCE

        proof_list = [
            ProofPoint(point=p.get("point", ""), source_id=p.get("source_id", "")) for p in proof
        ]
        return AcceptedQA(
            cluster_id=full_cluster_id,
            partition_id=partition_id,
            hop_count=len(distinct_sources),
            persona=persona.label,
            reasoning_chain=reasoning_chain,
            question=question,
            answer=answer,
            proof_list=proof_list,
        )

    def _check_multihop(
        self,
        question: str,
        answer: str,
        reasoning_chain: str,
        proof: list[dict[str, Any]],
        required_hops: int,
        content_blob: str,
    ) -> tuple[bool, int, str]:
        raw = self.llm.call(
            SYSTEM_PROMPT_MULTIHOP_CHECK,
            build_multihop_check_prompt(
                question, answer, reasoning_chain, proof, required_hops, content_blob
            ),
            max_tokens=1000,
            temperature=0.0,
        )
        result = extract_json(raw)
        verdict = str(result.get("verdict", "fail")).strip().lower()
        hops = int(result.get("genuine_hop_count", 0) or 0)
        multi = bool(result.get("is_multihop", False))
        reason = str(result.get("reason", ""))
        passed = verdict == "pass" and multi and hops >= required_hops
        return passed, hops, reason

    def _verify_and_correct_proof(
        self,
        question: str,
        answer: str,
        proof: list[dict[str, Any]],
        content_blob: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        raw = self.llm.call(
            SYSTEM_PROMPT_VERIFY,
            build_verify_prompt(question, answer, proof, content_blob),
            max_tokens=2000,
            temperature=0.0,
        )
        result = extract_json(raw)
        verdict = str(result.get("verdict", "fail")).strip().lower()
        corrected = result.get("corrected_proof") or proof
        return verdict, list(corrected)


def _build_content_blob(docs: list[dict[str, Any]]) -> str:
    import json
    return "\n\n---\n\n".join(
        f"[SOURCE _id: {d['_id']}]\n{d.get('content') or json.dumps(d, indent=2)}"
        for d in docs
    )


# ============================================================
# Cluster processor (loop seeds within one cluster)
# ============================================================


class ClusterProcessor:
    """Iterate seeds in a cluster, build subgraphs, drive `GenerationPipeline`."""

    def __init__(
        self,
        *,
        gateway: _GatewayProtocol,
        pipeline: GenerationPipeline,
        eval_config: EvalConfig,
        rng: random.Random | None = None,
    ) -> None:
        self.gateway = gateway
        self.pipeline = pipeline
        self.eval_config = eval_config
        self.rng = rng or random.Random(eval_config.random_seed)

    def process(
        self,
        *,
        cluster_id: str,
        cluster_index: int,
        target: int,
        topup: bool = False,
        used_seeds: set[str] | None = None,
        cached_partition_id: str | None = None,
        cached_cluster_ids: set[str] | None = None,
        on_event: OnEvent | None = None,
        global_so_far: int = 0,
        control: RunControl | None = None,
    ) -> tuple[list[AcceptedQA], list[RejectedQA], set[str]]:
        """Generate up to `target` accepted QA pairs from this cluster.

        If `control` is supplied, the seed loop checks it at the top of each
        iteration: a paused control blocks until released, and a stop
        request causes the loop to exit early (returning whatever was
        accepted so far).
        """
        partition_id = (
            cached_partition_id
            if cached_partition_id is not None
            else self.gateway.get_partition_id(cluster_id)
        )
        cluster_doc_ids_set = (
            cached_cluster_ids
            if cached_cluster_ids is not None
            else set(self.gateway.get_cluster_doc_ids(cluster_id))
        )

        _emit(
            on_event,
            "cluster_start",
            {
                "cluster_id": cluster_id,
                "doc_count": len(cluster_doc_ids_set),
                "target": target,
                "topup": topup,
                "partition_id": partition_id,
            },
        )

        if len(cluster_doc_ids_set) < 2:
            log.warning("<2 docs in cluster %s — skipping.", cluster_id)
            return [], [], set()

        seed_multiplier = 6 if topup else 4
        all_seeds = self.gateway.get_seed_docs(cluster_id, target * seed_multiplier)
        used = used_seeds or set()
        seeds = [s for s in all_seeds if s not in used] if topup else all_seeds

        accepted: list[AcceptedQA] = []
        rejected: list[RejectedQA] = []
        seen_seeds: set[str] = set()
        persona_offset = cluster_index * max(1, target)

        for seed_idx, seed_doc_id in enumerate(seeds):
            if len(accepted) >= target:
                break
            if control is not None and control.wait_if_paused():
                log.info("Stop requested — exiting cluster %s seed loop early.", cluster_id)
                break
            seen_seeds.add(seed_doc_id)

            all_nbrs = self.gateway.get_all_neighbors(seed_doc_id)
            same = [
                n
                for n in all_nbrs
                if n["doc_id"] in cluster_doc_ids_set and n["doc_id"] != seed_doc_id
            ]
            if not same:
                continue

            target_size = (
                2
                if topup
                else pick_subgraph_size(
                    len(same),
                    hop_dist=self.eval_config.hop_dist,
                    hop_dist_weights=self.eval_config.hop_dist_weights,
                    rng=self.rng,
                )
            )
            personas = self.eval_config.personas
            persona = personas[(persona_offset + seed_idx) % len(personas)]

            _emit(
                on_event,
                "seed",
                {
                    "cluster_id": cluster_id,
                    "seed_idx": seed_idx + 1,
                    "seed_doc_id": seed_doc_id,
                    "neighbors": len(same),
                    "target_size": target_size,
                    "accepted": len(accepted),
                    "target": target,
                    "global_so_far": global_so_far + len(accepted),
                },
            )

            try_sizes = [target_size] + [
                s for s in self.eval_config.subgraph_sizes_fallback if s < target_size
            ]
            attempt_outcome: AcceptedQA | RejectionReason | None = None
            for attempt_size in try_sizes:
                subgraph = build_subgraph(
                    seed_doc_id,
                    cluster_doc_ids_set,
                    attempt_size,
                    fetch_neighbors=self.gateway.get_all_neighbors,
                    fetch_doc_contents=self.gateway.fetch_doc_contents,
                    fetch_inter_edges=self.gateway.get_inter_edges,
                )
                if subgraph is None:
                    continue
                docs, edges = subgraph
                try:
                    attempt_outcome = self.pipeline.attempt(
                        cluster_id_short=cluster_id,
                        partition_id=partition_id,
                        docs=docs,
                        edges=edges,
                        persona=persona,
                        question_index=len(accepted) + 1,
                        min_genuine_hops=2 if topup else None,
                    )
                except ContextLengthError:
                    log.warning("Context too long at size=%d; trying smaller.", attempt_size)
                    continue
                except Exception as exc:
                    log.error("Pipeline error at size=%d: %s", attempt_size, exc)
                    attempt_outcome = RejectionReason.UNEXPECTED_ERROR
                    break
                break

            if isinstance(attempt_outcome, AcceptedQA):
                accepted.append(attempt_outcome)
                _emit(
                    on_event,
                    "accepted",
                    {
                        "cluster_id": cluster_id,
                        "hop_count": attempt_outcome.hop_count,
                        "question": attempt_outcome.question,
                        "persona": attempt_outcome.persona,
                        "accepted": len(accepted),
                        "target": target,
                        "global_so_far": global_so_far + len(accepted),
                    },
                )
            else:
                reason = (
                    attempt_outcome
                    if isinstance(attempt_outcome, RejectionReason)
                    else RejectionReason.CONTEXT_TOO_LONG
                )
                rejected.append(
                    RejectedQA(
                        cluster_id=cluster_id,
                        persona=persona.label,
                        seed_doc_id=seed_doc_id,
                        reason=reason,
                    )
                )
                _emit(
                    on_event,
                    "rejected",
                    {
                        "cluster_id": cluster_id,
                        "seed_doc_id": seed_doc_id,
                        "reason": reason.value,
                    },
                )

        return accepted, rejected, seen_seeds


# ============================================================
# Orchestrator (Pass 1 + Pass 2 + rubric + persistence)
# ============================================================


class EvaluationOrchestrator:
    """Top-level entry point — what `EvaluationOrchestrator.run` produces is
    what the dashboard renders."""

    def __init__(
        self,
        *,
        gateway: _GatewayProtocol,
        llm: LLMClient,
        eval_config: EvalConfig,
        rubric_evaluator: RubricEvaluator | None = None,
    ) -> None:
        self.gateway = gateway
        self.llm = llm
        self.eval_config = eval_config
        self.rubric_evaluator = rubric_evaluator
        self.pipeline = GenerationPipeline(
            llm=llm, max_verify_rounds=eval_config.max_verify_rounds
        )

    def run(
        self,
        *,
        on_event: OnEvent | None = None,
        control: RunControl | None = None,
    ) -> RunResult:
        """Execute Pass 1 + Pass 2, optionally score with rubric + persist.

        If `control` is provided, the orchestrator consults it at safe
        checkpoints (between clusters and inside each cluster's seed loop).
        On a stop request the orchestrator returns the partial `RunResult`
        accumulated so far and emits a `run_stopped` event in lieu of
        `run_done` so the UI can distinguish the two.
        """
        started = datetime.now(UTC)
        rng = random.Random(self.eval_config.random_seed)
        processor = ClusterProcessor(
            gateway=self.gateway,
            pipeline=self.pipeline,
            eval_config=self.eval_config,
            rng=rng,
        )

        if self.eval_config.save_to_arango:
            self.gateway.ensure_qa_collection()

        all_accepted: list[AcceptedQA] = []
        all_rejected: list[RejectedQA] = []
        cluster_state: dict[str, dict[str, Any]] = {}

        # Pass 1
        for i, cid in enumerate(self.eval_config.target_clusters):
            if control is not None and control.wait_if_paused():
                log.info("Stop requested — exiting Pass 1 before cluster %s.", cid)
                break
            partition_id = self.gateway.get_partition_id(cid)
            cluster_doc_ids_set = set(self.gateway.get_cluster_doc_ids(cid))
            target = self.eval_config.n_questions
            accepted, rejected, used_seeds = processor.process(
                cluster_id=cid,
                cluster_index=i,
                target=target,
                topup=False,
                used_seeds=set(),
                cached_partition_id=partition_id,
                cached_cluster_ids=cluster_doc_ids_set,
                on_event=on_event,
                global_so_far=len(all_accepted),
                control=control,
            )
            self._post_process(accepted, on_event=on_event)
            all_accepted.extend(accepted)
            all_rejected.extend(rejected)
            cluster_state[cid] = {
                "target": target,
                "achieved": len(accepted),
                "partition_id": partition_id,
                "cluster_doc_ids_set": cluster_doc_ids_set,
                "used_seeds": used_seeds,
                "index": i,
            }

        _emit(on_event, "pass_done", {"pass": 1, "total_accepted": len(all_accepted)})

        # Pass 2 — top-up. Skip entirely if stop was requested during Pass 1.
        stop_requested = control is not None and control.is_stop_requested
        shortfalls = {
            c: s for c, s in cluster_state.items() if s["achieved"] < s["target"]
        }
        if shortfalls and not stop_requested:
            sorted_short = sorted(
                shortfalls.items(), key=lambda x: -(x[1]["target"] - x[1]["achieved"])
            )
            for cid, s in sorted_short:
                if control is not None and control.wait_if_paused():
                    log.info("Stop requested — exiting Pass 2 before cluster %s.", cid)
                    break
                deficit = s["target"] - s["achieved"]
                accepted, rejected, used_seeds = processor.process(
                    cluster_id=cid,
                    cluster_index=s["index"],
                    target=deficit,
                    topup=True,
                    used_seeds=s["used_seeds"],
                    cached_partition_id=s["partition_id"],
                    cached_cluster_ids=s["cluster_doc_ids_set"],
                    on_event=on_event,
                    global_so_far=len(all_accepted),
                    control=control,
                )
                self._post_process(accepted, on_event=on_event)
                all_accepted.extend(accepted)
                all_rejected.extend(rejected)
                cluster_state[cid]["achieved"] += len(accepted)

            _emit(on_event, "pass_done", {"pass": 2, "total_accepted": len(all_accepted)})

        finished = datetime.now(UTC)
        result = RunResult(
            accepted=all_accepted,
            rejected=all_rejected,
            cluster_targets={c: s["target"] for c, s in cluster_state.items()},
            cluster_achieved={c: s["achieved"] for c, s in cluster_state.items()},
            started_at=started,
            finished_at=finished,
        )
        end_kind = (
            "run_stopped"
            if (control is not None and control.is_stop_requested)
            else "run_done"
        )
        _emit(
            on_event,
            end_kind,
            {
                "total_accepted": len(all_accepted),
                "total_rejected": len(all_rejected),
                "duration_s": (finished - started).total_seconds(),
            },
        )
        return result

    def _post_process(self, accepted: list[AcceptedQA], *, on_event: OnEvent | None) -> None:
        """Score with rubric (if enabled) and persist to Arango (if enabled)."""
        for qa in accepted:
            if self.eval_config.score_with_rubric and self.rubric_evaluator is not None:
                try:
                    docs = self.gateway.fetch_doc_contents(
                        list({p.source_id for p in qa.proof_list})
                    )
                    content_blob = _build_content_blob(docs)
                    scores, weighted = self.rubric_evaluator.score(
                        question=qa.question,
                        answer=qa.answer,
                        proof=[p.to_dict() for p in qa.proof_list],
                        persona_label=qa.persona,
                        content_blob=content_blob,
                    )
                    qa.rubric_scores = scores
                    qa.rubric_weighted_score = weighted
                except Exception as exc:
                    log.error("Rubric scoring failed for question %r: %s", qa.question[:60], exc)
                    _emit(on_event, "error", {"stage": "rubric", "error": str(exc)})

            if self.eval_config.save_to_arango:
                try:
                    self.gateway.insert_qa_row(qa.to_row_dict())
                except Exception as exc:
                    log.error("Arango insert failed: %s", exc)
                    _emit(on_event, "error", {"stage": "arango_insert", "error": str(exc)})


def _emit(callback: OnEvent | None, kind: str, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(RunEvent(kind=kind, payload=payload))
    except Exception:  # pragma: no cover - never let UI crash the pipeline
        log.exception("on_event callback raised — continuing.")
