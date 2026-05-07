"""Tests for `multihop_eval.subgraph`."""

from __future__ import annotations

import random

import pytest

from multihop_eval.subgraph import build_subgraph, pick_subgraph_size

# ---------------------------------------------------------------------------
# pick_subgraph_size
# ---------------------------------------------------------------------------


def test_pick_subgraph_size_respects_floor_of_two():
    rng = random.Random(0)
    # Only 0 in-cluster neighbours → cap at max(2, min(desired, 1)) = 2.
    assert pick_subgraph_size(0, hop_dist=[2, 3], hop_dist_weights=[1.0, 0.0], rng=rng) == 2


def test_pick_subgraph_size_respects_neighbour_ceiling():
    rng = random.Random(0)
    # Hop distribution always picks 5, but only 2 neighbours → cap at 3.
    size = pick_subgraph_size(2, hop_dist=[5], hop_dist_weights=[1.0], rng=rng)
    assert size == 3


def test_pick_subgraph_size_uses_weights():
    # Always choose 4 in this toy distribution.
    rng = random.Random(0)
    sizes = {pick_subgraph_size(10, hop_dist=[4], hop_dist_weights=[1.0], rng=rng) for _ in range(20)}
    assert sizes == {4}


def test_pick_subgraph_size_rejects_mismatched_weights():
    with pytest.raises(ValueError):
        pick_subgraph_size(5, hop_dist=[2, 3], hop_dist_weights=[1.0])


def test_pick_subgraph_size_rejects_empty_hop_dist():
    with pytest.raises(ValueError):
        pick_subgraph_size(5, hop_dist=[], hop_dist_weights=[])


# ---------------------------------------------------------------------------
# build_subgraph
# ---------------------------------------------------------------------------


def _make_callables(neighbors_by_seed, docs_by_id, edges):
    def fetch_neighbors(seed):
        return list(neighbors_by_seed.get(seed, []))

    def fetch_doc_contents(ids):
        return [docs_by_id[i] for i in ids if i in docs_by_id]

    def fetch_inter_edges(ids):
        s = set(ids)
        return [(f, t, score) for f, t, score in edges if f in s and t in s]

    return fetch_neighbors, fetch_doc_contents, fetch_inter_edges


def test_build_subgraph_returns_seed_plus_top_neighbors():
    docs = {f"src/{c}": {"_id": f"src/{c}", "content": c.upper()} for c in "abcd"}
    neighbors = {
        "src/a": [
            {"doc_id": "src/b", "score": 0.9},
            {"doc_id": "src/c", "score": 0.7},
            {"doc_id": "src/d", "score": 0.5},
        ]
    }
    edges = [("src/a", "src/b", 0.9), ("src/a", "src/c", 0.7)]
    fetch_n, fetch_d, fetch_e = _make_callables(neighbors, docs, edges)

    out = build_subgraph(
        "src/a",
        cluster_doc_ids={"src/a", "src/b", "src/c", "src/d"},
        target_size=3,
        fetch_neighbors=fetch_n,
        fetch_doc_contents=fetch_d,
        fetch_inter_edges=fetch_e,
    )
    assert out is not None
    selected_docs, selected_edges = out
    selected_ids = [d["_id"] for d in selected_docs]
    assert selected_ids == ["src/a", "src/b", "src/c"]
    assert ("src/a", "src/b", 0.9) in selected_edges


def test_build_subgraph_filters_out_of_cluster_neighbors():
    docs = {f"src/{c}": {"_id": f"src/{c}", "content": c} for c in "abx"}
    neighbors = {
        "src/a": [
            {"doc_id": "src/x", "score": 0.99},  # different cluster
            {"doc_id": "src/b", "score": 0.5},
        ]
    }
    fetch_n, fetch_d, fetch_e = _make_callables(neighbors, docs, [])

    out = build_subgraph(
        "src/a",
        cluster_doc_ids={"src/a", "src/b"},
        target_size=3,
        fetch_neighbors=fetch_n,
        fetch_doc_contents=fetch_d,
        fetch_inter_edges=fetch_e,
    )
    assert out is not None
    selected_ids = [d["_id"] for d in out[0]]
    assert "src/x" not in selected_ids
    assert selected_ids == ["src/a", "src/b"]


def test_build_subgraph_returns_none_when_no_in_cluster_neighbors():
    docs = {f"src/{c}": {"_id": f"src/{c}", "content": c} for c in "ax"}
    neighbors = {"src/a": [{"doc_id": "src/x", "score": 0.99}]}
    fetch_n, fetch_d, fetch_e = _make_callables(neighbors, docs, [])

    out = build_subgraph(
        "src/a",
        cluster_doc_ids={"src/a"},
        target_size=3,
        fetch_neighbors=fetch_n,
        fetch_doc_contents=fetch_d,
        fetch_inter_edges=fetch_e,
    )
    assert out is None


def test_build_subgraph_returns_none_when_target_size_below_two():
    out = build_subgraph(
        "src/a",
        cluster_doc_ids={"src/a", "src/b"},
        target_size=1,
        fetch_neighbors=lambda _: [{"doc_id": "src/b", "score": 0.5}],
        fetch_doc_contents=lambda ids: [{"_id": i, "content": ""} for i in ids],
        fetch_inter_edges=lambda _ids: [],
    )
    assert out is None


def test_build_subgraph_drops_missing_docs_and_returns_none_if_below_two():
    """Docs disappearing between graph-traversal and content-fetch should
    not crash; if the survivors are <2 docs the subgraph is invalid."""
    neighbors = {"src/a": [{"doc_id": "src/b", "score": 0.5}]}
    fetch_n, _, fetch_e = _make_callables(neighbors, {}, [])
    # Pretend doc fetch returns only the seed (src/b vanished).
    out = build_subgraph(
        "src/a",
        cluster_doc_ids={"src/a", "src/b"},
        target_size=3,
        fetch_neighbors=fetch_n,
        fetch_doc_contents=lambda ids: [{"_id": "src/a", "content": "A"}],
        fetch_inter_edges=fetch_e,
    )
    assert out is None
