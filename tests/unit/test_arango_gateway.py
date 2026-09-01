"""Tests for `multihop_eval.clients.arango_gateway` using a fake `ArangoClient`.

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

from multihop_eval.clients.arango_gateway import ArangoGateway, CollectionInfo
from multihop_eval.config import AUTH_MODE_JWT, ArangoConfig

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
    doc_count: int = 0

    def insert(self, doc: dict[str, Any]) -> None:
        self.inserts.append(doc)

    def count(self) -> int:
        return self.doc_count


@dataclass
class _FakeConnection:
    """Stand-in for python-arango's `db.conn` — tracks `set_token` calls."""

    tokens: list[str] = field(default_factory=list)

    def set_token(self, token: str) -> None:
        self.tokens.append(token)


@dataclass
class _FakeDatabase:
    aql: _FakeAQL = field(default_factory=_FakeAQL)
    existing_collections: set[str] = field(default_factory=set)
    created_collections: list[str] = field(default_factory=list)
    collections_dict: dict[str, _FakeCollectionAccess] = field(default_factory=dict)
    # Metadata used by list_collections (mimics python-arango shape).
    collections_listing: list[dict[str, Any]] = field(default_factory=list)
    databases_listing: list[str] = field(default_factory=list)
    conn: _FakeConnection = field(default_factory=_FakeConnection)
    # Set to make properties() raise, simulating Arango refusing the request.
    properties_error: Exception | None = None

    def has_collection(self, name: str) -> bool:
        return name in self.existing_collections

    def create_collection(self, name: str) -> None:
        self.created_collections.append(name)
        self.existing_collections.add(name)

    def collection(self, name: str) -> _FakeCollectionAccess:
        return self.collections_dict.setdefault(name, _FakeCollectionAccess())

    def properties(self) -> dict[str, Any]:
        if self.properties_error is not None:
            raise self.properties_error
        return {"name": "fakedb"}

    def collections(self) -> list[dict[str, Any]]:
        return list(self.collections_listing)

    def databases(self) -> list[str]:
        return list(self.databases_listing)


@dataclass
class _FakeArangoSDK:
    db_obj: _FakeDatabase

    def db(self, name: str, **kwargs: Any) -> _FakeDatabase:
        # Record the kwargs the caller used so tests can verify which auth
        # path was taken.
        self.db_obj.last_credentials = (name, kwargs)  # type: ignore[attr-defined]
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


# ---------------------------------------------------------------------------
# verify_connection — the message the user actually sees
# ---------------------------------------------------------------------------


class _ArangoServerError(Exception):
    """Mimics python-arango's ArangoServerError (which carries http_code)."""

    def __init__(self, http_code: int, message: str) -> None:
        super().__init__(message)
        self.http_code = http_code


def test_verify_connection_returns_none_when_reachable(gateway):
    assert gateway.verify_connection() is None
    assert gateway.ping() is True


def test_verify_connection_reports_the_real_arango_message(gateway, db_obj):
    """Regression: a bare bool forced users to read the server log for a 401."""
    db_obj.properties_error = _ArangoServerError(
        401, "[HTTP 401][ERR 11] not authorized to execute this request"
    )

    error = gateway.verify_connection()

    assert error is not None
    assert "[HTTP 401][ERR 11] not authorized to execute this request" in error
    assert gateway.ping() is False


def test_401_in_password_mode_names_the_user_and_database(gateway, db_obj):
    db_obj.properties_error = _ArangoServerError(401, "[HTTP 401][ERR 11] nope")

    error = gateway.verify_connection()

    # A valid user denied one database looks identical to a bad password,
    # so the hint has to mention both possibilities.
    assert "'root'" in error
    assert "'testdb'" in error
    assert "password" in error
    assert "granted access" in error


def test_401_in_jwt_mode_points_at_the_token_not_a_password(tmp_path, db_obj):
    token_file = tmp_path / "token"
    token_file.write_text("a.b.c", encoding="utf-8")
    cfg = ArangoConfig(
        host="https://arango.example.com",
        db="ampdb",
        auth_mode=AUTH_MODE_JWT,
        jwt_token_path=str(token_file),
    )
    gateway = ArangoGateway(cfg, client=_FakeArangoSDK(db_obj))  # type: ignore[arg-type]
    db_obj.properties_error = _ArangoServerError(401, "[HTTP 401][ERR 11] nope")

    error = gateway.verify_connection()

    assert str(token_file) in error
    assert "expired" in error
    assert "'ampdb'" in error
    assert "password" not in error


def test_non_401_failures_are_passed_through_verbatim(gateway, db_obj):
    """A 404 or a TLS error must not be dressed up as a credentials problem."""
    db_obj.properties_error = _ArangoServerError(404, "[HTTP 404][ERR 1228] database not found")

    error = gateway.verify_connection()

    assert error == "[HTTP 404][ERR 1228] database not found"
    assert "password" not in error


def test_connection_errors_without_an_http_code_still_surface(gateway, db_obj):
    db_obj.properties_error = OSError("[Errno 61] Connection refused")

    error = gateway.verify_connection()

    assert "Connection refused" in error


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
            "persona": "domain_expert",
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


def test_fetch_goldens_with_keys_delegates(gateway, db_obj):
    db_obj.aql.scripts = [[{"_key": "1"}]]
    out = gateway.fetch_goldens_with_keys()
    assert out == [{"_key": "1"}]


def test_ensure_rag_response_collection_creates_when_missing(gateway, db_obj):
    gateway.ensure_rag_response_collection("rag_responses_v1")
    assert "rag_responses_v1" in db_obj.created_collections


def test_ensure_rag_response_collection_skips_when_existing(gateway, db_obj):
    db_obj.existing_collections.add("rag_responses_v1")
    gateway.ensure_rag_response_collection("rag_responses_v1")
    assert "rag_responses_v1" not in db_obj.created_collections


def test_fetch_rag_responses_no_filters(gateway, db_obj):
    db_obj.aql.scripts = [[{"_key": "rag_v1__q1"}]]
    out = gateway.fetch_rag_responses("rag_responses_v1")
    assert out == [{"_key": "rag_v1__q1"}]
    call = db_obj.aql.last_calls[0]
    assert call["bind_vars"]["@coll"] == "rag_responses_v1"
    assert "system_name" not in call["bind_vars"]
    assert "qa_keys" not in call["bind_vars"]


def test_fetch_rag_responses_filters_by_system_name(gateway, db_obj):
    db_obj.aql.scripts = [[]]
    gateway.fetch_rag_responses("rag_responses_v1", system_name="rag_v2")
    call = db_obj.aql.last_calls[0]
    assert call["bind_vars"]["system_name"] == "rag_v2"
    assert "FILTER" in call["query"]


def test_fetch_rag_responses_filters_by_qa_keys(gateway, db_obj):
    db_obj.aql.scripts = [[]]
    gateway.fetch_rag_responses("rag_responses_v1", qa_keys=["q1", "q2"])
    call = db_obj.aql.last_calls[0]
    assert call["bind_vars"]["qa_keys"] == ["q1", "q2"]


def test_fetch_rag_responses_applies_limit(gateway, db_obj):
    db_obj.aql.scripts = [[]]
    gateway.fetch_rag_responses("rag_responses_v1", limit=5)
    call = db_obj.aql.last_calls[0]
    assert call["bind_vars"]["limit"] == 5
    assert "LIMIT" in call["query"]


def test_list_rag_systems_returns_sorted_distinct(gateway, db_obj):
    db_obj.aql.scripts = [["rag_v2", "rag_v1", None]]
    assert gateway.list_rag_systems("rag_responses_v1") == ["rag_v1", "rag_v2"]


# ---------------------------------------------------------------------------
# Auth / discovery helpers (AMP path)
# ---------------------------------------------------------------------------


def test_password_mode_passes_username_and_password(cfg, db_obj):
    sdk = _FakeArangoSDK(db_obj)
    ArangoGateway(cfg, client=sdk)  # type: ignore[arg-type]
    name, kwargs = db_obj.last_credentials  # type: ignore[attr-defined]
    assert name == "testdb"
    assert kwargs["username"] == "root"
    assert kwargs["password"] == "secret"
    assert "user_token" not in kwargs


def test_jwt_mode_passes_user_token(tmp_path, db_obj):
    token_path = tmp_path / "token"
    token_path.write_text("jwt-abc", encoding="utf-8")
    cfg = ArangoConfig(
        host="https://x.example.com",
        db="d",
        auth_mode=AUTH_MODE_JWT,
        jwt_token_path=str(token_path),
    )  # type: ignore[call-arg]
    sdk = _FakeArangoSDK(db_obj)
    ArangoGateway(cfg, client=sdk)  # type: ignore[arg-type]
    name, kwargs = db_obj.last_credentials  # type: ignore[attr-defined]
    assert name == "d"
    assert kwargs == {"user_token": "jwt-abc"}


def test_refresh_token_reads_disk_and_pushes_to_connection(tmp_path, db_obj):
    token_path = tmp_path / "token"
    token_path.write_text("first", encoding="utf-8")
    cfg = ArangoConfig(
        host="https://x.example.com",
        db="d",
        auth_mode=AUTH_MODE_JWT,
        jwt_token_path=str(token_path),
    )  # type: ignore[call-arg]
    gateway = ArangoGateway(cfg, client=_FakeArangoSDK(db_obj))  # type: ignore[arg-type]
    # Simulate the sidecar rotating the file.
    token_path.write_text("second", encoding="utf-8")
    gateway.refresh_token()
    assert db_obj.conn.tokens == ["second"]


def test_refresh_token_is_noop_in_password_mode(gateway, db_obj):
    gateway.refresh_token()
    assert db_obj.conn.tokens == []


def test_list_databases_returns_sorted_unique(gateway, db_obj):
    db_obj.databases_listing = ["b", "_system", "a"]
    assert gateway.list_databases() == ["_system", "a", "b"]


def test_list_collections_filters_system_by_default(gateway, db_obj):
    db_obj.collections_listing = [
        {"name": "sources", "type": 2, "system": False},
        {"name": "edges", "type": 3, "system": False},
        {"name": "_users", "type": 2, "system": True},
    ]
    db_obj.collections_dict["sources"] = _FakeCollectionAccess(doc_count=42)
    db_obj.collections_dict["edges"] = _FakeCollectionAccess(doc_count=7)
    result = gateway.list_collections()
    names = [c.name for c in result]
    assert names == ["edges", "sources"]
    kinds = {c.name: c.kind for c in result}
    assert kinds == {"sources": "document", "edges": "edge"}
    counts = {c.name: c.doc_count for c in result}
    assert counts == {"sources": 42, "edges": 7}


def test_list_collections_includes_system_when_requested(gateway, db_obj):
    db_obj.collections_listing = [
        {"name": "sources", "type": 2, "system": False},
        {"name": "_users", "type": 2, "system": True},
    ]
    result = gateway.list_collections(include_system=True)
    assert {c.name for c in result} == {"sources", "_users"}
    sys_entry = next(c for c in result if c.name == "_users")
    assert sys_entry.system is True


def test_list_collections_returns_collection_info_dataclass(gateway, db_obj):
    db_obj.collections_listing = [{"name": "x", "type": 2}]
    result = gateway.list_collections()
    assert isinstance(result[0], CollectionInfo)


def test_list_cluster_ids_returns_keys(gateway, db_obj):
    db_obj.aql.scripts = [["cluster_0", "cluster_1"]]
    assert gateway.list_cluster_ids("dom") == ["cluster_0", "cluster_1"]
    call = db_obj.aql.last_calls[0]
    assert call["bind_vars"]["@coll"] == "dom"


def test_list_cluster_ids_empty_for_empty_collection_name(gateway, db_obj):
    assert gateway.list_cluster_ids("") == []
    assert db_obj.aql.last_calls == []


def test_list_cluster_ids_returns_empty_on_failure(gateway, db_obj):
    def boom(*_a, **_k):
        raise RuntimeError("missing collection")

    db_obj.aql.execute = boom  # type: ignore[assignment]
    assert gateway.list_cluster_ids("dom") == []
