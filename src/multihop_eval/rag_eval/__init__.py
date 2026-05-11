"""RAG-system evaluation package.

Given a set of golden multi-hop QA pairs (from `qa_pairs_multihop_eval_v1`)
and a set of responses produced by one or more RAG systems against those
goldens, this package computes:

* Retrieval metrics (P@K, R@K, MRR, NDCG@K, HitRate@K, Chunk Overlap Rate,
  Exact Match) via `ranx` for the IR portion + native helpers for the rest.
* Rule-based generation metrics (Groundedness, Source Diversity, Citation
  Coverage, Length Consistency, ROUGE-L, Empty Retrieval Rate).

Human-annotation metrics (faithfulness / relevancy / hallucination /
completeness / coherence) are out of scope here — they are wired up via the
optional `langfuse_sink` module which surfaces traces in the LangFuse UI.

Public surface:

    from multihop_eval.rag_eval import (
        RagResponse, RetrievedChunk, RagEvalRun, RagMetricBundle,
        build_qrels, RagEvalOrchestrator,
    )
"""

from multihop_eval.rag_eval.metrics.generation import compute_generation_metrics
from multihop_eval.rag_eval.metrics.retrieval import compute_retrieval_metrics
from multihop_eval.rag_eval.models import (
    RagEvalRun,
    RagMetricBundle,
    RagResponse,
    RetrievedChunk,
)
from multihop_eval.rag_eval.pipeline import RagEvalOrchestrator
from multihop_eval.rag_eval.qrels import build_qrels
from multihop_eval.rag_eval.sources.arango_source import (
    ArangoLoadResult,
    ArangoRowError,
)
from multihop_eval.rag_eval.sources.arango_source import (
    list_systems as list_arango_systems,
)
from multihop_eval.rag_eval.sources.arango_source import (
    load_responses as load_responses_from_arango,
)
from multihop_eval.rag_eval.sources.jsonl_source import (
    JsonlLoadResult,
    JsonlParseError,
)
from multihop_eval.rag_eval.sources.jsonl_source import (
    load_responses as load_responses_from_jsonl,
)

__all__ = [
    "RagEvalRun",
    "RagEvalOrchestrator",
    "RagMetricBundle",
    "RagResponse",
    "RetrievedChunk",
    "build_qrels",
    "compute_generation_metrics",
    "compute_retrieval_metrics",
    "JsonlLoadResult",
    "JsonlParseError",
    "ArangoLoadResult",
    "ArangoRowError",
    "load_responses_from_jsonl",
    "load_responses_from_arango",
    "list_arango_systems",
]
