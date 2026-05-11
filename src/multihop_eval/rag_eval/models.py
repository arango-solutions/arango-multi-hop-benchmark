"""Pydantic models shared between rag_eval modules.

These shapes are deliberately decoupled from the generation-side dataclasses
(`AcceptedQA`, `RunResult`) so the RAG-eval feature can evolve independently
and so the JSONL upload contract is enforced by pydantic validation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class RetrievedChunk(BaseModel):
    """One chunk a RAG system returned for a question."""

    doc_id: str = Field(..., min_length=1, description="Source document _id (e.g. 'sources/abc').")
    rank: int = Field(..., ge=1, description="1-based rank of this chunk in the response.")
    score: float | None = Field(default=None, description="Optional retriever score for the chunk.")
    text: str | None = Field(default=None, description="Optional raw text — used for groundedness.")


class RagResponse(BaseModel):
    """One RAG system's response to one golden question."""

    system_name: str = Field(..., min_length=1, description="Name/tag of the RAG system under test.")
    qa_pair_key: str = Field(..., min_length=1, description="Arango _key of the golden QA row.")
    question: str = Field(..., min_length=1)
    answer: str = Field(default="", description="The generated answer; may be empty.")
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("retrieved_chunks")
    @classmethod
    def _ranks_strictly_unique(cls, value: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if len({c.rank for c in value}) != len(value):
            raise ValueError("retrieved_chunks ranks must be unique within a response.")
        return value

    @model_validator(mode="after")
    def _sort_by_rank(self) -> RagResponse:
        self.retrieved_chunks.sort(key=lambda c: c.rank)
        return self


class RagMetricBundle(BaseModel):
    """Aggregate retrieval + generation metrics for one (system, run)."""

    retrieval: dict[str, float] = Field(default_factory=dict)
    generation: dict[str, float] = Field(default_factory=dict)
    per_query: list[dict[str, Any]] = Field(
        default_factory=list,
        description="One row per response with metric values — drives drill-down tables.",
    )


class RagEvalRun(BaseModel):
    """Result of evaluating one RAG system over a golden set."""

    system_name: str
    n_responses: int
    n_matched_goldens: int = Field(
        default=0,
        description="Count of responses that matched a golden by qa_pair_key.",
    )
    metrics: RagMetricBundle = Field(default_factory=RagMetricBundle)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def duration_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()
