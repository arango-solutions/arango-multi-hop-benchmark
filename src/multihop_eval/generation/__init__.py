"""Multi-hop QA generation feature.

Parallel to `multihop_eval.rag_eval` — this subpackage owns the original
generation pipeline (seed -> subgraph -> draft -> multi-hop check -> proof
verification -> rubric scoring) plus the shared dataclasses passed between
its stages.

Import from the concrete submodule, e.g.:

    from multihop_eval.generation.pipeline import EvaluationOrchestrator
    from multihop_eval.generation.models import AcceptedQA, RunResult
    from multihop_eval.generation.personas import DEFAULT_PERSONAS, Persona
    from multihop_eval.generation.rubric import DEFAULT_RUBRIC, RubricField
    from multihop_eval.generation.adhoc import AdhocEvaluator
    from multihop_eval.generation.summary import build_summary

(Eager re-exports here would create a circular dependency on
`multihop_eval.config`, which several submodules import from.)
"""
