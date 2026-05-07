"""Tests for `multihop_eval.arango_gateway` using a fake `ArangoClient`.

We don't hit a real ArangoDB instance here — the goal is to verify that the
gateway:
  * builds full cluster ids from short ids
  * passes the configured collection names to AQL
  * dedupes inter-edges and sorts by score desc
  * decimates seeds evenly when there are more docs than slots
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from multihop_eval.arango_gateway import ArangoGateway
from multihop_eval.config import ArangoConfig

# ---------------------------------------------------------------------------
# Fake python-arango client tree
# ---------------------------------------------------------------------------


@dataclass
class _FakeAQL:
    """Records every execute() and returns scripted result lists in order."""

    scripts: list[Any] = field(default_factory=list)
    last_calls: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, query: str, *, bind_vars: dict[str, Any] | None = None) -> list[Any]:
        self.last_calls.append({"query": query, "bind_vars": bind_vars or {}})
        if not self.scripts:
            raise AssertionError(f"AQL script exhausted; last query: {query[:80]}")
        return self.scripts.pop(0)


@dataclass
class _FakeCollectionAccess:
    inserts: list[dict[str, Any]] = field(default_factory=list)

    def insert(self, doc: dict[str, Any]) -> None:
        self.inserts.append(doc)


@dataclass
class _FakeDatabase:
    aql: _FakeAQL = field(default_factory=_FakeAQL)
    existing_collections: set[str] = field(default_factory=set)
    created_collections: list[str] = field(default_factory=list)
    collections: dict[str, _FakeCollectionAccess] = field(default_factory=dict)

    def has_collection(self, name: str) -> bool:
        return name in self.existing_collections

    def create_collection(self, name: str) -> None:
        self.created_collections.append(name)
        self.existing_collections.add(name)

    def collection(self, name: str) -> _FakeCollectionAccess:
        return self.collections.setdefault(name, _FakeCollectionAccess())

    def properties(self) -> dict[str, Any]:
        return {"name": "fakedb"}


@dataclass
class _FakeArangoSDK:
    db_obj: _FakeDatabase

    def db(self, name: str, *, username: str, password: str) -> _FakeDatabase:
        self.db_obj.last_credentials = (name, username, password)  # type: ignore[attr-defined]
        return self.db_obj


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> ArangoConfig:
    return ArangoConfig(
        host="https://arango.example.com",
        db="testdb",
        username="root",
        password="secret",  # type: ignore[arg-type]
        domains_collection="dom",
        relations_collection="rel",
        rags_collection="rags",
        sources_collection="src",
        similarity_collection="sims",
        qa_collection="qa_test",
    )


@pytest.fixture
def db_obj() -> _FakeDatabase:
    return _FakeDatabase()


@pytest.fixture
def gateway(cfg, db_obj) -> ArangoGateway:
    return ArangoGateway(cfg, client=_FakeArangoSDK(db_obj))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Connection / collection lifecycle
# ---------------------------------------------------------------------------


def test_ensure_qa_collection_creates_when_missing(gateway, db_obj):
    gateway.ensure_qa_collection()
    assert "qa_test" in db_obj.created_collections


def test_ensure_qa_collection_skips_when_existing(gateway, db_obj):
    db_obj.existing_collections.add("qa_test")
    gateway.ensure_qa_collection()
    assert "qa_test" not in db_obj.created_collections


def test_insert_qa_row_writes_expected_fields(gateway, db_obj):
    gateway.insert_qa_row(
        {
            "cluster_id": "dom/cluster_test_0",
            "partition_id": "test_0_part",
            "hop_count": 3,
            "persona": "hr_manager",
            "reasoning_chain": "A->B->C",
            "question": "q?",
            "answer": "a.",
            "proof_list": [{"point": "p", "source_id": "s"}],
            "rubric_scores": {"factuality": {"score": 5, "justification": "ok"}},
            "rubric_weighted_score": 4.7,
        }
    )
    coll = db_obj.collection("qa_test")
    assert len(coll.inserts) == 1
    inserted = coll.inserts[0]
    assert inserted["cluster_id"] == "dom/cluster_test_0"
    assert inserted["proof"] == [{"point": "p", "source_id": "s"}]
    assert inserted["rubric_weighted_score"] == 4.7


def test_ping_returns_true_for_healthy_db(gateway):
    assert gateway.ping() is True


# ---------------------------------------------------------------------------
# Cluster + similarity reads
# ---------------------------------------------------------------------------


def test_get_cluster_doc_ids_uses_full_id_and_relations_collection(gateway, db_obj):
    db_obj.aql.scripts = [["src/a", "src/b"]]
    result = gateway.get_cluster_doc_ids("cluster_test_0")
    assert result == ["src/a", "src/b"]
    call = db_obj.aql.last_calls[0]
    assert call["bind_vars"]["@relations"] == "rel"
    assert call["bind_vars"]["cluster_id"] == "dom/cluster_test_0"


def test_get_cluster_doc_ids_passes_through_full_ids(gateway, db_obj):
    db_obj.aql.scripts = [[]]
    gateway.get_cluster_doc_ids("dom/already_full")
    assert db_obj.aql.last_calls[0]["bind_vars"]["cluster_id"] == "dom/already_full"


def test_get_partition_id_returns_first_match(gateway, db_obj):
    db_obj.aql.scripts = [["test_0_partition_xyz"]]
    assert gateway.get_partition_id("cluster_test_0") == "test_0_partition_xyz"
    call = db_obj.aql.last_calls[0]
    assert call["bind_vars"]["prefix"] == "test_0_"


def test_get_partition_id_returns_empty_when_no_cluster_suffix(gateway, db_obj):
    # "12345" — no `cluster_<suffix>` pattern → regex bails out before AQL.
    assert gateway.get_partition_id("12345") == ""
    # AQL must not have been touched at all for this no-match case.
    assert db_obj.aql.last_calls == []


def test_get_seed_docs_decimates_when_more_than_n(gateway, db_obj):
    all_ids = [f"src/d{i:02d}" for i in range(20)]
    db_obj.aql.scripts = [all_ids]
    seeds = gateway.get_seed_docs("cluster_test_0", 5)
    assert len(seeds) == 5
    # Decimation should be evenly spaced and start at index 0.
    assert seeds[0] == "src/d00"
    assert seeds[-1] != seeds[0]
    assert all(s in all_ids for s in seeds)


def test_get_seed_docs_returns_all_when_fewer(gateway, db_obj):
    db_obj.aql.scripts = [["src/a", "src/b"]]
    assert gateway.get_seed_docs("cluster_test_0", 5) == ["src/a", "src/b"]


def test_get_seed_docs_returns_empty_for_empty_cluster(gateway, db_obj):
    db_obj.aql.scripts = [[]]
    assert gateway.get_seed_docs("cluster_test_0", 3) == []


def test_get_all_neighbors_uses_similarity_collection(gateway, db_obj):
    db_obj.aql.scripts = [
        [{"doc_id": "src/b", "score": 0.9}, {"doc_id": "src/c", "score": 0.7}]
    ]
    out = gateway.get_all_neighbors("src/a")
    assert [n["doc_id"] for n in out] == ["src/b", "src/c"]
    assert db_obj.aql.last_calls[0]["bind_vars"]["@sims"] == "sims"


def test_fetch_doc_contents_uses_doc_ids(gateway, db_obj):
    db_obj.aql.scripts = [
        [{"_id": "src/a", "content": "A", "file_name": "a.pdf"}]
    ]
    out = gateway.fetch_doc_contents(["src/a"])
    assert out == [{"_id": "src/a", "content": "A", "file_name": "a.pdf"}]
    assert db_obj.aql.last_calls[0]["bind_vars"]["doc_ids"] == ["src/a"]


def test_get_inter_edges_returns_empty_for_single_doc(gateway, db_obj):
    assert gateway.get_inter_edges(["src/only"]) == []


def test_get_inter_edges_dedupes_and_sorts_desc(gateway, db_obj):
    db_obj.aql.scripts = [
        [
            {"f": "src/a", "t": "src/b", "s": 0.4},
            {"f": "src/b", "t": "src/a", "s": 0.4},  # duplicate, reversed
            {"f": "src/a", "t": "src/c", "s": 0.9},
            {"f": "src/b", "t": "src/c", "s": 0.7},
        ]
    ]
    edges = gateway.get_inter_edges(["src/a", "src/b", "src/c"])
    assert len(edges) == 3
    scores = [e[2] for e in edges]
    assert scores == sorted(scores, reverse=True)


def test_fetch_qa_rows_with_limit(gateway, db_obj):
    db_obj.aql.scripts = [[{"_key": "1"}, {"_key": "2"}]]
    out = gateway.fetch_qa_rows(limit=2)
    assert len(out) == 2
    assert "@qa" in db_obj.aql.last_calls[0]["bind_vars"]
    assert db_obj.aql.last_calls[0]["bind_vars"]["limit"] == 2
