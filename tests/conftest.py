"""Shared pytest fixtures: fakes for the LLM client and the ArangoDB gateway.

These fakes let unit + integration tests run without a live OpenAI key or
ArangoDB cluster. The fakes match the real classes' public surface (duck-typed)
so `EvaluationOrchestrator` and friends can be instantiated identically.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pytest

from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.personas import DEFAULT_PERSONAS
from multihop_eval.rubric import DEFAULT_RUBRIC

# ---------------------------------------------------------------------------
# FakeLLMClient — returns scripted responses in order.
# ---------------------------------------------------------------------------


class _ScriptExhaustedError(RuntimeError):
    """Raised when a `FakeLLMClient` is asked for more responses than scripted."""


@dataclass
class FakeLLMClient:
    """A scripted fake for `LLMClient.call(...)`.

    Pass `responses` as either strings (returned as-is) or dicts (json-encoded).
    Specials:
      * `"__CTX__"` → raise `ContextLengthError`
      * `"__BOOM__"` → raise `RuntimeError`
    """

    responses: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    _queue: deque = field(default_factory=deque)

    def __post_init__(self) -> None:
        self._queue = deque(self.responses)

    def queue(self, items: Iterable[Any]) -> None:
        self._queue.extend(items)

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        from multihop_eval.llm_client import ContextLengthError

        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if not self._queue:
            raise _ScriptExhaustedError(
                f"FakeLLMClient script exhausted after {len(self.calls)} calls; "
                f"last user_prompt began with: {user_prompt[:120]!r}"
            )
        item = self._queue.popleft()
        if item == "__CTX__":
            raise ContextLengthError("scripted context-length error")
        if item == "__BOOM__":
            raise RuntimeError("scripted boom")
        if isinstance(item, str):
            return item
        return json.dumps(item)


# ---------------------------------------------------------------------------
# FakeArangoGateway — in-memory dict-backed substitute for ArangoGateway.
# ---------------------------------------------------------------------------


@dataclass
class FakeArangoGateway:
    """Mimics the public surface of `ArangoGateway` against in-memory data."""

    cluster_doc_ids: dict[str, list[str]] = field(default_factory=dict)
    """cluster_id (short) -> list of source document _ids in that cluster."""

    docs: dict[str, dict[str, Any]] = field(default_factory=dict)
    """source _id -> doc payload with at least 'content' and 'filename'."""

    similarities: list[tuple[str, str, float]] = field(default_factory=list)
    """(_from, _to, score) edges between source _ids."""

    partition_ids: dict[str, str] = field(default_factory=dict)
    """cluster_id (short) -> rag_partition_id."""

    inserted_qa: list[dict[str, Any]] = field(default_factory=list)
    qa_collection_ensured: bool = False

    rag_response_collections_ensured: set[str] = field(default_factory=set)
    rag_responses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """collection name -> list of stored response rows."""

    def ping(self) -> bool:
        return True

    def ensure_qa_collection(self) -> None:
        self.qa_collection_ensured = True

    def insert_qa_row(self, row: dict[str, Any]) -> None:
        self.inserted_qa.append(dict(row))

    def fetch_qa_rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is None:
            return list(self.inserted_qa)
        return list(self.inserted_qa[:limit])

    def fetch_goldens_with_keys(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.fetch_qa_rows(limit=limit)

    def ensure_rag_response_collection(self, name: str) -> None:
        self.rag_response_collections_ensured.add(name)
        self.rag_responses.setdefault(name, [])

    def fetch_rag_responses(
        self,
        collection: str,
        *,
        system_name: str | None = None,
        qa_keys: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self.rag_responses.get(collection, []))
        if system_name is not None:
            rows = [r for r in rows if r.get("system_name") == system_name]
        if qa_keys is not None:
            wanted = set(qa_keys)
            rows = [r for r in rows if r.get("qa_pair_key") in wanted]
        # Mimic the real gateway's sort-by-key-desc so test ordering matches prod.
        rows.sort(key=lambda r: r.get("_key", ""), reverse=True)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def list_rag_systems(self, collection: str) -> list[str]:
        return sorted({r.get("system_name", "") for r in self.rag_responses.get(collection, []) if r.get("system_name")})

    def get_cluster_doc_ids(self, cluster_id: str) -> list[str]:
        return list(self.cluster_doc_ids.get(cluster_id, []))

    def get_partition_id(self, cluster_id: str) -> str:
        return self.partition_ids.get(cluster_id, "")

    def get_seed_docs(self, cluster_id: str, n_seeds: int) -> list[str]:
        all_ids = sorted(self.cluster_doc_ids.get(cluster_id, []))
        if not all_ids:
            return []
        if len(all_ids) <= n_seeds:
            return all_ids
        step = len(all_ids) / n_seeds
        return [all_ids[int(i * step)] for i in range(n_seeds)]

    def get_all_neighbors(self, seed_doc_id: str) -> list[dict[str, Any]]:
        rows = []
        for f, t, s in self.similarities:
            if f == seed_doc_id:
                rows.append({"doc_id": t, "score": s})
            elif t == seed_doc_id:
                rows.append({"doc_id": f, "score": s})
        rows.sort(key=lambda r: -r["score"])
        return rows

    def fetch_doc_contents(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        out = []
        for did in doc_ids:
            d = self.docs.get(did)
            if d is not None:
                out.append({"_id": did, "content": d.get("content", ""), "file_name": d.get("filename", "")})
        return out

    def get_inter_edges(self, doc_ids: list[str]) -> list[tuple[str, str, float]]:
        s = set(doc_ids)
        seen = set()
        edges: list[tuple[str, str, float]] = []
        for f, t, score in self.similarities:
            if f in s and t in s:
                key = tuple(sorted([f, t]))
                if key not in seen:
                    seen.add(key)
                    edges.append((f, t, score))
        return sorted(edges, key=lambda x: -x[2])


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def fake_arango() -> FakeArangoGateway:
    return FakeArangoGateway()


@pytest.fixture
def app_config() -> AppConfig:
    """Minimal valid AppConfig usable by tests that don't exercise env-loading."""
    return AppConfig(
        arango=ArangoConfig(
            host="https://arango.example.com",
            db="testdb",
            username="root",
            password="secret",  # type: ignore[arg-type]
        ),
        llm=LLMConfig(api_key="sk-test"),  # type: ignore[arg-type]
        eval=EvalConfig(
            target_clusters=["cluster_test_0"],
            n_questions=2,
            personas=list(DEFAULT_PERSONAS),
            rubric_fields=list(DEFAULT_RUBRIC),
        ),
    )
