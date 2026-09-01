"""Pydantic request/response models for the web API.

These shape the JSON contract between the React SPA and FastAPI. They are
deliberately separate from the domain models in ``multihop_eval.config`` so
the wire format can evolve without forcing changes on the pipeline.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from multihop_eval.config import DEFAULT_PROJECT_NAME

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class AmpInfo(BaseModel):
    detected: bool
    deployment_name: str | None = None
    endpoint: str | None = None


class ConnectRequest(BaseModel):
    mode: Literal["amp", "password"]
    host: str | None = None
    db: str = "_system"
    username: str = "root"
    password: str | None = None


class ConnectionStatus(BaseModel):
    status: str
    db: str | None = None
    error: str | None = None
    last_tested: str | None = None
    amp: AmpInfo


class CollectionItem(BaseModel):
    name: str
    doc_count: int
    kind: str
    system: bool


class DatabasesResponse(BaseModel):
    databases: list[str]


class CollectionsResponse(BaseModel):
    collections: list[CollectionItem]


class ClustersResponse(BaseModel):
    clusters: list[str]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class PersonaModel(BaseModel):
    label: str
    instruction: str


class RubricFieldModel(BaseModel):
    name: str
    description: str
    scale_min: int = 1
    scale_max: int = 5
    weight: float = 1.0


class LLMConfigModel(BaseModel):
    api_url: str = "https://api.openai.com/v1/chat/completions"
    api_key: str = ""
    model: str = "gpt-4.1"
    temperature: float = 0.3
    max_tokens: int = 4000
    timeout_s: int = 180
    retries: int = 3


class EvalConfigModel(BaseModel):
    target_clusters: list[str] = Field(default_factory=lambda: ["cluster_0"])
    n_questions: int = 50
    hop_dist: list[int] = Field(default_factory=lambda: [2, 3])
    hop_dist_weights: list[float] = Field(default_factory=lambda: [0.7, 0.3])
    max_verify_rounds: int = 3
    save_to_arango: bool = True
    score_with_rubric: bool = True
    personas: list[PersonaModel] = Field(default_factory=list)
    rubric_fields: list[RubricFieldModel] = Field(default_factory=list)


class ConfigSaveRequest(BaseModel):
    """Everything the Configure tab gathers, minus Arango credentials.

    Arango credentials come from the live gateway on the session (set during
    connect); the Autograph project name + collection-role overrides are
    supplied here.
    """

    project_name: str = DEFAULT_PROJECT_NAME
    collections: dict[str, str] = Field(default_factory=dict)
    llm: LLMConfigModel
    eval: EvalConfigModel


class ConfigResponse(BaseModel):
    saved: dict[str, Any] | None = None
    defaults: dict[str, Any]


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class RunStatusResponse(BaseModel):
    status: str
    accepted: int = 0
    target: int = 0
    summary: dict[str, Any] | None = None
    error: str | None = None
    log: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class DashboardResponse(BaseModel):
    """KPI summary + accepted rows for the Dashboard tab.

    ``source`` is either ``"session"`` (the in-memory result of the last run)
    or ``"arango"`` (rows previously persisted to the QA collection).
    """

    source: Literal["session", "arango"]
    available: bool
    summary: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0


# ---------------------------------------------------------------------------
# Ad-hoc evaluation
# ---------------------------------------------------------------------------


class AdhocRequest(BaseModel):
    """A single QA pair + its proof and source docs to validate.

    ``proof`` entries are ``{"point": str, "source_id": str}`` dicts and
    ``sources`` entries must each carry an ``_id`` (plus ``content`` for the
    multi-hop / proof checks) — mirroring ``AdhocEvaluator.evaluate``.
    """

    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    reasoning_chain: str = ""
    proof: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    score_with_rubric: bool = False


class AdhocResponse(BaseModel):
    multi_hop_pass: bool
    genuine_hop_count: int
    multi_hop_reason: str
    proof_verdict: str
    corrected_proof: list[dict[str, Any]] = Field(default_factory=list)
    rubric_scores: dict[str, Any] = Field(default_factory=dict)
    rubric_weighted_score: float | None = None


# ---------------------------------------------------------------------------
# RAG evaluation
# ---------------------------------------------------------------------------


class RagEvalRequest(BaseModel):
    """Knobs + response source for one RAG-evaluation run."""

    relevance_mode: Literal["binary", "graded"] = "binary"
    k_values: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])
    response_source: Literal["jsonl", "arango"] = "jsonl"
    response_arango_collection: str = "rag_responses_v1"
    system_filter: list[str] = Field(default_factory=list)
    length_z_threshold: float = 2.0
    groundedness_fuzz_threshold: int = 75
    empty_retrieval_min_score: float | None = None
    jsonl_text: str | None = None
    golden_limit: int | None = None


class RagEvalResponse(BaseModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)
    n_goldens: int = 0
    n_responses: int = 0
    n_systems: int = 0
    load_errors: list[str] = Field(default_factory=list)
