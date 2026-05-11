"""End-to-end RAG evaluation orchestrator.

`RagEvalOrchestrator.evaluate(...)` takes a list of goldens and a list of
`RagResponse`s spanning one or more RAG systems, partitions by `system_name`,
builds qrels from the configured relevance mode, computes both metric
bundles per system, and returns one `RagEvalRun` per system_name.

Goldens come pre-fetched (e.g. from the dashboard's session cache) so the
orchestrator doesn't need to know about ArangoDB. The UI / CLI layer handles
loading; the orchestrator stays pure.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from multihop_eval.config import (
    RAG_RESPONSE_SOURCE_ARANGO,
    RAG_RESPONSE_SOURCE_JSONL,
    RagEvalConfig,
)
from multihop_eval.rag_eval.metrics.generation import compute_generation_metrics
from multihop_eval.rag_eval.metrics.retrieval import compute_retrieval_metrics
from multihop_eval.rag_eval.models import RagEvalRun, RagMetricBundle, RagResponse
from multihop_eval.rag_eval.qrels import build_qrels
from multihop_eval.rag_eval.sources.arango_source import (
    load_responses as load_responses_from_arango,
)
from multihop_eval.rag_eval.sources.jsonl_source import (
    load_responses as load_responses_from_jsonl,
)


class _ArangoSource(Protocol):
    """The slice of `ArangoGateway` the orchestrator needs for the Arango source."""

    def fetch_rag_responses(
        self,
        collection: str,
        *,
        system_name: str | None = ...,
        qa_keys: list[str] | None = ...,
        limit: int | None = ...,
    ) -> list[dict[str, Any]]: ...

    def list_rag_systems(self, collection: str) -> list[str]: ...


class RagEvalOrchestrator:
    """Compute per-system retrieval + generation metrics in one call.

    The orchestrator is intentionally a small class rather than a free
    function so we can wire it through Streamlit state cleanly (same shape
    as `EvaluationOrchestrator`).
    """

    def __init__(self, config: RagEvalConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Source loading helpers — useful in the UI before calling evaluate().
    # ------------------------------------------------------------------

    def load_responses(
        self,
        *,
        jsonl_path: Path | None = None,
        jsonl_lines: Iterable[str] | None = None,
        arango_gateway: _ArangoSource | None = None,
    ) -> list[RagResponse]:
        """Load responses from whichever source `config.response_source` selects.

        Args:
            jsonl_path: Required when `response_source == 'jsonl'` and we want
                to read from disk; mutually exclusive with `jsonl_lines`.
            jsonl_lines: In-memory line iterable for the JSONL source — handy
                when the UI receives an uploaded file as bytes.
            arango_gateway: Required when `response_source == 'arango'`.

        Returns:
            All responses found at the configured source, with any
            `config.system_filter` applied.

        Raises:
            ValueError: If required inputs for the configured source are missing.
        """
        if self.config.response_source == RAG_RESPONSE_SOURCE_JSONL:
            source = jsonl_lines if jsonl_lines is not None else jsonl_path
            if source is None:
                raise ValueError(
                    "RagEvalConfig.response_source='jsonl' requires either "
                    "jsonl_path or jsonl_lines."
                )
            result = load_responses_from_jsonl(source)
            responses = result.responses
        elif self.config.response_source == RAG_RESPONSE_SOURCE_ARANGO:
            if arango_gateway is None:
                raise ValueError(
                    "RagEvalConfig.response_source='arango' requires "
                    "arango_gateway."
                )
            arango_result = load_responses_from_arango(
                arango_gateway, self.config.response_arango_collection
            )
            responses = arango_result.responses
        else:  # pragma: no cover - validator guarantees this branch is dead
            raise ValueError(f"Unknown response_source: {self.config.response_source!r}")

        if self.config.system_filter:
            allowed = set(self.config.system_filter)
            responses = [r for r in responses if r.system_name in allowed]
        return responses

    # ------------------------------------------------------------------
    # The actual evaluation.
    # ------------------------------------------------------------------

    def evaluate(
        self,
        goldens: list[dict[str, Any]],
        responses: list[RagResponse],
    ) -> list[RagEvalRun]:
        """Compute metrics for every distinct `system_name` in `responses`.

        Args:
            goldens: Golden QA rows including a stable id (key field is
                `_key` by default — same shape as `ArangoGateway.fetch_qa_rows`).
            responses: All loaded `RagResponse`s across every system. They
                are partitioned by `system_name` here.

        Returns:
            One `RagEvalRun` per `system_name`, sorted alphabetically so the
            UI's tab order is deterministic.
        """
        qrels = build_qrels(goldens, mode=self.config.relevance_mode)
        goldens_by_key = {str(g.get("_key")): g for g in goldens if g.get("_key")}

        per_system: dict[str, list[RagResponse]] = defaultdict(list)
        for r in responses:
            per_system[r.system_name].append(r)

        runs: list[RagEvalRun] = []
        for system_name in sorted(per_system):
            sys_responses = per_system[system_name]
            started_at = datetime.now(UTC)
            retrieval_agg, retrieval_per_q = compute_retrieval_metrics(
                qrels,
                sys_responses,
                goldens_by_key,
                k_values=self.config.k_values,
            )
            generation_agg, generation_per_q = compute_generation_metrics(
                sys_responses,
                goldens_by_key,
                fuzz_threshold=self.config.groundedness_fuzz_threshold,
                length_z_threshold=self.config.length_z_threshold,
                empty_retrieval_min_score=self.config.empty_retrieval_min_score,
            )
            per_query = _merge_per_query(retrieval_per_q, generation_per_q)
            matched = sum(1 for r in sys_responses if r.qa_pair_key in goldens_by_key)
            runs.append(
                RagEvalRun(
                    system_name=system_name,
                    n_responses=len(sys_responses),
                    n_matched_goldens=matched,
                    metrics=RagMetricBundle(
                        retrieval=retrieval_agg,
                        generation=generation_agg,
                        per_query=per_query,
                    ),
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                )
            )
        return runs


def _merge_per_query(
    retrieval_rows: list[dict[str, Any]],
    generation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join retrieval + generation per-query rows on `qa_pair_key`.

    Both lists are produced from the same `responses` list in the same order,
    so we could zip — but join-by-key is cheap and removes a hidden coupling
    between the two metric modules.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for row in retrieval_rows:
        by_key[row["qa_pair_key"]] = dict(row)
    for row in generation_rows:
        key = row["qa_pair_key"]
        merged = by_key.setdefault(key, {"qa_pair_key": key})
        for k, v in row.items():
            if k == "qa_pair_key":
                continue
            merged[k] = v
    return list(by_key.values())
