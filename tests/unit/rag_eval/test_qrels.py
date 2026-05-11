"""Tests for `multihop_eval.rag_eval.qrels.build_qrels`."""

from __future__ import annotations

import pytest

from multihop_eval.rag_eval.qrels import build_qrels


def _row(key: str, proof_ids: list[str], *, field: str = "proof") -> dict:
    """Helper: build a golden row with proof points under the chosen field."""
    return {
        "_key": key,
        field: [{"point": f"point about {sid}", "source_id": sid} for sid in proof_ids],
    }


def test_binary_grades_all_proof_docs_as_one():
    rows = [_row("q1", ["sources/a", "sources/b", "sources/c"])]
    qrels = build_qrels(rows, mode="binary")
    assert qrels == {"q1": {"sources/a": 1, "sources/b": 1, "sources/c": 1}}


def test_graded_decays_with_hop_index():
    # Three hops -> grades 3, 2, 1.
    rows = [_row("q1", ["sources/seed", "sources/mid", "sources/leaf"])]
    qrels = build_qrels(rows, mode="graded")
    assert qrels == {"q1": {"sources/seed": 3, "sources/mid": 2, "sources/leaf": 1}}


def test_graded_two_hop_gives_two_one():
    rows = [_row("q1", ["sources/a", "sources/b"])]
    qrels = build_qrels(rows, mode="graded")
    assert qrels["q1"] == {"sources/a": 2, "sources/b": 1}


def test_graded_duplicate_doc_keeps_max_grade():
    # If the same doc appears as both hop 0 and hop 2, hop 0 (highest grade) wins.
    rows = [_row("q1", ["sources/x", "sources/y", "sources/x"])]
    qrels = build_qrels(rows, mode="graded")
    assert qrels["q1"]["sources/x"] == 3


def test_empty_proof_list_skips_row():
    rows = [_row("q1", [])]
    qrels = build_qrels(rows, mode="binary")
    assert qrels == {}


def test_proof_with_only_blank_source_ids_skips_row():
    rows = [{"_key": "q1", "proof": [{"point": "p", "source_id": ""}]}]
    qrels = build_qrels(rows, mode="binary")
    assert qrels == {}


def test_missing_key_skips_row():
    rows = [{"_key": "", "proof": [{"point": "p", "source_id": "sources/a"}]}]
    qrels = build_qrels(rows, mode="binary")
    assert qrels == {}


def test_reads_proof_list_field_for_in_memory_rows():
    # In-memory `AcceptedQA.to_row_dict()` uses the `proof_list` key instead of `proof`.
    rows = [_row("q1", ["sources/a"], field="proof_list")]
    qrels = build_qrels(rows, mode="binary")
    assert qrels == {"q1": {"sources/a": 1}}


def test_proof_string_variant_is_ignored():
    # `AcceptedQA.to_row_dict()` also emits a formatted `proof` string alongside
    # `proof_list`. The string variant must NOT be parsed; we should fall back
    # to `proof_list`.
    row = {
        "_key": "q1",
        "proof": "- [sources/a]\n  some point",  # formatted string, not a list
        "proof_list": [{"point": "p", "source_id": "sources/a"}],
    }
    qrels = build_qrels([row], mode="binary")
    assert qrels == {"q1": {"sources/a": 1}}


def test_unknown_mode_raises():
    rows = [_row("q1", ["sources/a"])]
    with pytest.raises(ValueError, match="Unknown relevance mode"):
        build_qrels(rows, mode="weighted")


def test_custom_key_field():
    rows = [{"qa_pair_key": "qx", "proof": [{"point": "p", "source_id": "sources/a"}]}]
    qrels = build_qrels(rows, mode="binary", key_field="qa_pair_key")
    assert qrels == {"qx": {"sources/a": 1}}


def test_explicit_proof_field_disables_fallback():
    # When proof_field is explicit, the other field must NOT be consulted.
    rows = [_row("q1", ["sources/a"], field="proof_list")]
    qrels = build_qrels(rows, mode="binary", proof_field="proof")
    assert qrels == {}


def test_handles_iterable_input_not_list():
    def gen():
        yield _row("q1", ["sources/a"])
        yield _row("q2", ["sources/b", "sources/c"])

    qrels = build_qrels(gen(), mode="binary")
    assert set(qrels) == {"q1", "q2"}
