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

RAG_RESPONSE_SOURCE_JSONL = "jsonl"
RAG_RESPONSE_SOURCE_ARANGO = "arango"
RAG_RELEVANCE_BINARY = "binary"
RAG_RELEVANCE_GRADED = "graded"


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


class RagEvalConfig(BaseModel):
    """User-editable knobs for the RAG-evaluation feature.

    These control how the orchestrator loads RAG-system responses, builds qrels
    from the golden `proof_list`, and weights generation-side rule metrics.
    """

    relevance_mode: str = Field(
        default=RAG_RELEVANCE_BINARY,
        description=(
            "How proof_list entries map to qrels. 'binary' = 1 if in proof_list else 0; "
            "'graded' = higher grade to earlier hops (max(1, len(proof_list) - hop_index))."
        ),
    )
    k_values: list[int] = Field(
        default_factory=lambda: [1, 3, 5, 10],
        description="Cut-offs for P@K, R@K, NDCG@K, HitRate@K.",
    )
    response_source: str = Field(
        default=RAG_RESPONSE_SOURCE_JSONL,
        description="Where the RAG responses come from: 'jsonl' (upload) or 'arango'.",
    )
    response_jsonl_path: str | None = Field(
        default=None,
        description="Local path to the uploaded JSONL — set by the UI after upload.",
    )
    response_arango_collection: str = Field(
        default="rag_responses_v1",
        description="Name of the Arango collection holding RAG responses.",
    )
    system_filter: list[str] = Field(
        default_factory=list,
        description=(
            "If non-empty, only evaluate responses whose system_name is in this list. "
            "Otherwise every system found in the source is evaluated."
        ),
    )
    length_z_threshold: float = Field(
        default=2.0,
        gt=0.0,
        le=10.0,
        description="Flag a response as length-anomalous when |z(len(answer))| exceeds this.",
    )
    groundedness_fuzz_threshold: int = Field(
        default=75,
        ge=0,
        le=100,
        description=(
            "rapidfuzz partial_ratio cutoff (0-100) above which a sentence is considered "
            "grounded in the retrieved chunks."
        ),
    )
    empty_retrieval_min_score: float | None = Field(
        default=None,
        description=(
            "If set, a chunk only counts as 'retrieved' when its score crosses this floor; "
            "used to compute Empty Retrieval Rate. Leave null to count any chunk as present."
        ),
    )

    @field_validator("relevance_mode")
    @classmethod
    def _relevance_mode_known(cls, value: str) -> str:
        if value not in {RAG_RELEVANCE_BINARY, RAG_RELEVANCE_GRADED}:
            raise ValueError(
                f"relevance_mode must be '{RAG_RELEVANCE_BINARY}' or "
                f"'{RAG_RELEVANCE_GRADED}', got {value!r}."
            )
        return value

    @field_validator("response_source")
    @classmethod
    def _source_known(cls, value: str) -> str:
        if value not in {RAG_RESPONSE_SOURCE_JSONL, RAG_RESPONSE_SOURCE_ARANGO}:
            raise ValueError(
                f"response_source must be '{RAG_RESPONSE_SOURCE_JSONL}' or "
                f"'{RAG_RESPONSE_SOURCE_ARANGO}', got {value!r}."
            )
        return value

    @field_validator("k_values")
    @classmethod
    def _k_values_positive(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("k_values must contain at least one cut-off.")
        if any(k <= 0 for k in value):
            raise ValueError(f"k_values must all be > 0; got {value}.")
        return sorted(set(value))


class LangFuseConfig(BaseSettings):
    """Optional LangFuse sink for human-annotation scores.

    Loaded from `LANGFUSE_*` env vars. When `enabled=False` (or any required
    field is missing) the sink becomes a no-op and the LangFuse panel is hidden
    from the UI — so the app runs fine without LangFuse installed.
    """

    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_",
        env_file=_env_file_candidates(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(default=False, description="Feature flag for the LangFuse integration.")
    host: str = Field(default="https://cloud.langfuse.com", description="LangFuse base URL.")
    public_key: SecretStr | None = Field(default=None, description="LangFuse public key.")
    secret_key: SecretStr | None = Field(default=None, description="LangFuse secret key.")

    def is_configured(self) -> bool:
        """True when the sink has all credentials AND is enabled."""
        return bool(self.enabled and self.public_key and self.secret_key)


class AppConfig(BaseModel):
    """The full runtime config — what the UI saves and the orchestrator reads."""

    arango: ArangoConfig
    llm: LLMConfig
    eval: EvalConfig = Field(default_factory=EvalConfig)
    rag_eval: RagEvalConfig = Field(default_factory=RagEvalConfig)
    langfuse: LangFuseConfig = Field(default_factory=LangFuseConfig)

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build an `AppConfig` reading env / `.env` / `./env` for arango+llm."""
        return cls(
            arango=ArangoConfig(),
            llm=LLMConfig(),
            eval=EvalConfig(),
            rag_eval=RagEvalConfig(),
            langfuse=LangFuseConfig(),
        )

    def to_safe_dict(self) -> dict[str, Any]:
        """Serialise without secrets — safe to log or display."""
        d = self.model_dump()
        d["arango"]["password"] = "***"
        d["llm"]["api_key"] = "***"
        if d.get("langfuse"):
            d["langfuse"]["public_key"] = "***"
            d["langfuse"]["secret_key"] = "***"
        return d
