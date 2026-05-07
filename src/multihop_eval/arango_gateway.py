"""All ArangoDB I/O lives here.

`ArangoGateway` wraps the connection setup, the AQL queries used by the
generation pipeline, and persistence of accepted QA rows.

Keeping every Arango call behind a single class lets:
  * Unit tests substitute a `FakeArangoGateway` that mimics the surface.
  * Future swaps (e.g. read replica vs write primary) happen in one place.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from arango import ArangoClient

from multihop_eval.config import ArangoConfig

if TYPE_CHECKING:
    from arango.database import StandardDatabase  # pragma: no cover

log = logging.getLogger(__name__)


class ArangoGateway:
    """Thin layer over `python-arango` exposing only what the pipeline needs."""

    def __init__(self, config: ArangoConfig, *, client: ArangoClient | None = None) -> None:
        self.config = config
        self._client = client or ArangoClient(hosts=config.host)
        self._db: StandardDatabase = self._client.db(
            config.db,
            username=config.username,
            password=config.password.get_secret_value(),
        )

    # ------------------------------------------------------------------
    # Connection sanity
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if we can talk to the database."""
        try:
            self._db.properties()
            return True
        except Exception as exc:  # pragma: no cover - exercised in integration only
            log.warning("Arango ping failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # QA collection lifecycle
    # ------------------------------------------------------------------

    def ensure_qa_collection(self) -> None:
        name = self.config.qa_collection
        if not self._db.has_collection(name):
            self._db.create_collection(name)
            log.info("Created collection '%s'.", name)
        else:
            log.info("Collection '%s' already exists - appending.", name)

    def insert_qa_row(self, row: dict[str, Any]) -> None:
        doc = {
            "cluster_id": row["cluster_id"],
            "partition_id": row.get("partition_id", ""),
            "hop_count": row.get("hop_count", 0),
            "persona": row.get("persona", ""),
            "reasoning_chain": row.get("reasoning_chain", ""),
            "question": row["question"],
            "answer": row["answer"],
            "proof": row.get("proof_list", []),
            "rubric_scores": row.get("rubric_scores", {}),
            "rubric_weighted_score": row.get("rubric_weighted_score"),
        }
        self._db.collection(self.config.qa_collection).insert(doc)

    def fetch_qa_rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return rows previously written to the QA collection (newest first)."""
        bind: dict[str, Any] = {"@qa": self.config.qa_collection}
        query = "FOR r IN @@qa SORT r._key DESC RETURN r"
        if limit is not None:
            query = "FOR r IN @@qa SORT r._key DESC LIMIT @limit RETURN r"
            bind["limit"] = limit
        return list(self._db.aql.execute(query, bind_vars=bind))

    # ------------------------------------------------------------------
    # Cluster + similarity reads
    # ------------------------------------------------------------------

    def _cluster_full_id(self, short: str) -> str:
        if "/" in short:
            return short
        return f"{self.config.domains_collection}/{short}"

    def get_cluster_doc_ids(self, cluster_id: str) -> list[str]:
        full = self._cluster_full_id(cluster_id)
        query = """
        FOR e IN @@relations
            FILTER e._to == @cluster_id
            RETURN e._from
        """
        return list(
            self._db.aql.execute(
                query,
                bind_vars={
                    "@relations": self.config.relations_collection,
                    "cluster_id": full,
                },
            )
        )

    def get_partition_id(self, cluster_id: str) -> str:
        match = re.search(r"cluster_(\w+)$", cluster_id)
        if not match:
            return ""
        prefix = match.group(1) + "_"
        results = list(
            self._db.aql.execute(
                "FOR r IN @@rags FILTER STARTS_WITH(r.rag_partition_id, @prefix) "
                "LIMIT 1 RETURN r.rag_partition_id",
                bind_vars={
                    "@rags": self.config.rags_collection,
                    "prefix": prefix,
                },
            )
        )
        return results[0] if results else ""

    def get_seed_docs(self, cluster_id: str, n_seeds: int) -> list[str]:
        full = self._cluster_full_id(cluster_id)
        query = """
        FOR e IN @@relations
            FILTER e._to == @cluster_id
            SORT e._from ASC
            RETURN e._from
        """
        all_ids = list(
            self._db.aql.execute(
                query,
                bind_vars={
                    "@relations": self.config.relations_collection,
                    "cluster_id": full,
                },
            )
        )
        if not all_ids:
            return []
        if len(all_ids) <= n_seeds:
            return all_ids
        step = len(all_ids) / n_seeds
        return [all_ids[int(i * step)] for i in range(n_seeds)]

    def get_all_neighbors(self, seed_doc_id: str) -> list[dict[str, Any]]:
        query = """
        FOR e IN @@sims
            FILTER e._from == @seed OR e._to == @seed
            LET neighbor = (e._from == @seed) ? e._to : e._from
            SORT e.similarity_score DESC
            RETURN {doc_id: neighbor, score: e.similarity_score}
        """
        return list(
            self._db.aql.execute(
                query,
                bind_vars={
                    "@sims": self.config.similarity_collection,
                    "seed": seed_doc_id,
                },
            )
        )

    def fetch_doc_contents(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        query = """
        FOR doc_id IN @doc_ids
            LET d = DOCUMENT(doc_id)
            FILTER d != null
            RETURN {_id: d._id, content: d.content, file_name: d.filename}
        """
        return list(self._db.aql.execute(query, bind_vars={"doc_ids": doc_ids}))

    def get_inter_edges(self, doc_ids: list[str]) -> list[tuple[str, str, float]]:
        if len(doc_ids) < 2:
            return []
        query = """
        FOR e IN @@sims
            FILTER e._from IN @ids AND e._to IN @ids
            RETURN {f: e._from, t: e._to, s: e.similarity_score}
        """
        rows = list(
            self._db.aql.execute(
                query,
                bind_vars={
                    "@sims": self.config.similarity_collection,
                    "ids": doc_ids,
                },
            )
        )
        seen: set[tuple[str, str]] = set()
        edges: list[tuple[str, str, float]] = []
        for row in rows:
            key = tuple(sorted([row["f"], row["t"]]))
            if key not in seen:
                seen.add(key)
                edges.append((row["f"], row["t"], row["s"]))
        return sorted(edges, key=lambda x: -x[2])
