"""Single source of truth for runtime configuration.

`AppConfig` aggregates three blocks:

* `ArangoConfig`  — connection + collection names
* `LLMConfig`     — chat-completions endpoint + retries
* `EvalConfig`    — generation-pipeline knobs, personas, and the user rubric

Each of `ArangoConfig` and `LLMConfig` is a `BaseSettings` so it can be filled
from environment variables (or a `.env` file) when running outside the UI.
`EvalConfig` is a plain `BaseModel` because it is shaped by the user in the
Streamlit Configure tab and persisted alongside a run.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from multihop_eval.personas import DEFAULT_PERSONAS, Persona
from multihop_eval.rubric import DEFAULT_RUBRIC, RubricField


def _env_file_candidates() -> tuple[str, ...]:
    """Look for `./env` (used by the original script) and `./.env` (standard)."""
    here = Path.cwd()
    candidates = []
    for name in ("env", ".env"):
        candidate = here / name
        if candidate.exists():
            candidates.append(str(candidate))
    return tuple(candidates) or (".env",)


class ArangoConfig(BaseSettings):
    """Connection details + every collection used by the pipeline."""

    model_config = SettingsConfigDict(
        env_prefix="ARANGO_",
        env_file=_env_file_candidates(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(..., description="ArangoDB HTTP host, e.g. https://my-cluster.example.com")
    db: str = Field(..., description="Database name")
    username: str = Field(default="root")
    password: SecretStr = Field(...)

    similarity_collection: str = "multihop_eval_similarities"
    relations_collection: str = "multihop_eval_corpus_relations"
    rags_collection: str = "multihop_eval_rags"
    sources_collection: str = "multihop_eval_sources"
    domains_collection: str = "multihop_eval_domains"
    qa_collection: str = "qa_pairs_multihop_eval_v1"

    @field_validator("host")
    @classmethod
    def _host_has_scheme(cls, value: str) -> str:
        cleaned = value.strip().rstrip("/")
        if not cleaned:
            raise ValueError("Arango host must not be empty.")
        if "://" not in cleaned:
            raise ValueError(f"Arango host must include scheme (http:// or https://): {value!r}")
        return cleaned


class LLMConfig(BaseSettings):
    """OpenAI-compatible chat-completions client config."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=_env_file_candidates(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_url: str = "https://api.openai.com/v1/chat/completions"
    api_key: SecretStr = Field(...)
    model: str = "gpt-4.1"
    max_tokens: int = Field(default=4000, gt=0, le=128_000)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    timeout_s: int = Field(default=180, gt=0, le=3600)
    retries: int = Field(default=3, ge=1, le=10)
    backoff_base: int = Field(default=2, ge=1, le=10)


class EvalConfig(BaseModel):
    """Generation-pipeline knobs + user-editable personas and rubric."""

    target_clusters: list[str] = Field(default_factory=lambda: ["cluster_0"])
    n_questions: int = Field(default=50, gt=0, le=10_000)
    hop_dist: list[int] = Field(default_factory=lambda: [2, 3])
    hop_dist_weights: list[float] = Field(default_factory=lambda: [0.7, 0.3])
    subgraph_sizes_fallback: list[int] = Field(default_factory=lambda: [5, 4, 3, 2])
    max_verify_rounds: int = Field(default=3, ge=1, le=10)
    random_seed: int = 42

    personas: list[Persona] = Field(default_factory=lambda: list(DEFAULT_PERSONAS))
    rubric_fields: list[RubricField] = Field(default_factory=lambda: list(DEFAULT_RUBRIC))

    save_to_arango: bool = True
    output_excel_path: str = "eval.xlsx"
    score_with_rubric: bool = True

    @field_validator("target_clusters")
    @classmethod
    def _at_least_one_cluster(cls, value: list[str]) -> list[str]:
        cleaned = [c.strip() for c in value if c and c.strip()]
        if not cleaned:
            raise ValueError("target_clusters must contain at least one non-empty id.")
        return cleaned

    @field_validator("hop_dist")
    @classmethod
    def _hop_dist_positive(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("hop_dist must not be empty.")
        if any(h < 2 for h in value):
            raise ValueError("hop_dist values must all be >= 2 (a 1-hop is single-doc).")
        return value

    @model_validator(mode="after")
    def _hop_dist_weights_match(self) -> EvalConfig:
        if len(self.hop_dist_weights) != len(self.hop_dist):
            raise ValueError(
                f"hop_dist_weights length ({len(self.hop_dist_weights)}) must match "
                f"hop_dist length ({len(self.hop_dist)})."
            )
        if any(w < 0 for w in self.hop_dist_weights):
            raise ValueError("hop_dist_weights must all be non-negative.")
        if not math.isclose(sum(self.hop_dist_weights), 1.0, abs_tol=1e-3):
            raise ValueError(
                f"hop_dist_weights must sum to 1.0 (got {sum(self.hop_dist_weights):.4f})."
            )
        if not self.personas:
            raise ValueError("At least one persona is required.")
        if self.score_with_rubric and not self.rubric_fields:
            raise ValueError(
                "score_with_rubric=True but rubric_fields is empty. Add fields or disable."
            )
        return self


class AppConfig(BaseModel):
    """The full runtime config — what the UI saves and the orchestrator reads."""

    arango: ArangoConfig
    llm: LLMConfig
    eval: EvalConfig = Field(default_factory=EvalConfig)

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build an `AppConfig` reading env / `.env` / `./env` for arango+llm."""
        return cls(arango=ArangoConfig(), llm=LLMConfig(), eval=EvalConfig())

    def to_safe_dict(self) -> dict[str, Any]:
        """Serialise without secrets — safe to log or display."""
        d = self.model_dump()
        d["arango"]["password"] = "***"
        d["llm"]["api_key"] = "***"
        return d
