"""Pydantic request/response models for the web API.

These shape the JSON contract between the React SPA and FastAPI. They are
deliberately separate from the domain models in ``multihop_eval.config`` so
the wire format can evolve without forcing changes on the pipeline.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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
    connect); only collection-role overrides are supplied here.
    """

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
