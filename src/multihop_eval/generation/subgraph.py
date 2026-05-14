"""Pure subgraph utilities — no IO, no LLM.

`build_subgraph` and `pick_subgraph_size` are pulled out of the original
script verbatim modulo a few clarifications, so they can be unit-tested with
synthetic neighbour lists. The Arango-facing reads are passed in as
callables, keeping this module IO-free.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from typing import Any

# Type aliases for clarity.
DocId = str
NeighborRow = dict[str, Any]  # {"doc_id": str, "score": float}
DocPayload = dict[str, Any]  # {"_id": str, "content": str, ...}
Edge = tuple[str, str, float]  # (doc_id_a, doc_id_b, similarity_score)


def pick_subgraph_size(
    n_same_cluster_neighbors: int,
    *,
    hop_dist: list[int],
    hop_dist_weights: list[float],
    rng: random.Random | None = None,
) -> int:
    """Choose how many docs to include in the subgraph.

    Constraints:
      * never less than 2 (we need at least one hop edge)
      * never more than `n_same_cluster_neighbors + 1` (the seed plus all in-cluster neighbours)

    Uses the user-defined hop distribution + weights to bias selection.
    """
    if not hop_dist:
        raise ValueError("hop_dist must not be empty")
    if len(hop_dist) != len(hop_dist_weights):
        raise ValueError(
            f"hop_dist ({len(hop_dist)}) and hop_dist_weights ({len(hop_dist_weights)}) "
            "must have equal length"
        )
    chooser = rng or random
    desired = chooser.choices(hop_dist, weights=hop_dist_weights, k=1)[0]
    max_size = 1 + max(0, n_same_cluster_neighbors)
    return max(2, min(desired, max_size))


def build_subgraph(
    seed_doc_id: DocId,
    cluster_doc_ids: Iterable[DocId],
    target_size: int,
    *,
    fetch_neighbors: Callable[[DocId], list[NeighborRow]],
    fetch_doc_contents: Callable[[list[DocId]], list[DocPayload]],
    fetch_inter_edges: Callable[[list[DocId]], list[Edge]],
) -> tuple[list[DocPayload], list[Edge]] | None:
    """Build a subgraph rooted at `seed_doc_id`.

    Steps:
      1. Pull all similarity neighbours of the seed.
      2. Keep only those that live in the same cluster (different from seed).
      3. Take the top `target_size - 1` by similarity score; together with
         the seed that gives `<=target_size` docs.
      4. Fetch their contents (drop ids that disappeared from sources).
      5. Compute inter-edges among the surviving docs.

    Returns `None` when fewer than 2 docs survive — the caller should try
    a smaller `target_size` or skip this seed.
    """
    cluster_set = set(cluster_doc_ids)
    if seed_doc_id not in cluster_set:
        cluster_set.add(seed_doc_id)
    if target_size < 2:
        return None

    all_neighbors = fetch_neighbors(seed_doc_id)
    same = [
        n for n in all_neighbors
        if n["doc_id"] in cluster_set and n["doc_id"] != seed_doc_id
    ]
    if not same:
        return None

    chosen_ids: list[DocId] = [seed_doc_id] + [n["doc_id"] for n in same[: target_size - 1]]
    raw_docs = fetch_doc_contents(chosen_ids)
    by_id = {d["_id"]: d for d in raw_docs}
    docs = [by_id[did] for did in chosen_ids if did in by_id]
    if len(docs) < 2:
        return None

    edges = fetch_inter_edges([d["_id"] for d in docs])
    return docs, edges
