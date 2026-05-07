"""Multi-hop QA dataset generator + evaluator package.

Public surface — import what you need from here:

    from multihop_eval import (
        AppConfig, ArangoConfig, LLMConfig, EvalConfig,
        Persona, RubricField,
        EvaluationOrchestrator, AdhocEvaluator,
        build_summary,
    )
"""

from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.personas import DEFAULT_PERSONAS, Persona
from multihop_eval.rubric import DEFAULT_RUBRIC, RubricField

__all__ = [
    "AppConfig",
    "ArangoConfig",
    "LLMConfig",
    "EvalConfig",
    "Persona",
    "DEFAULT_PERSONAS",
    "RubricField",
    "DEFAULT_RUBRIC",
]

__version__ = "1.0.0"
