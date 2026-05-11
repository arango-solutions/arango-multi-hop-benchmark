"""Build qrels (query-relevance judgments) from golden QA pairs.

A 'qrel' is the IR-evaluation convention: for each query, a dict mapping
relevant document id -> integer relevance grade. We derive it from the
golden multi-hop QA pair's `proof_list`:

* **binary** mode: every `source_id` in `proof_list` gets grade 1, every
  other doc is implicitly 0. This is the right default when you don't trust
  the order of `proof_list`.

* **graded** mode: earlier hops get higher grades, on the assumption that
  the first proof point is the seed/most-pivotal doc. Grade for hop index
  `i` (0-based) over a proof list of length `n` is `max(1, n - i)`. So a
  3-hop proof gives grades 3, 2, 1 to its three docs.

The orchestrator picks the mode from `RagEvalConfig.relevance_mode`.
"""

from __future__ import annotations

from collections.abc import Iterable

from multihop_eval.config import RAG_RELEVANCE_BINARY, RAG_RELEVANCE_GRADED


def _grades_for_proof_ids(proof_ids: list[str], mode: str) -> dict[str, int]:
    """Translate one query's ordered proof source-ids into a {doc_id: grade} dict.

    If the same doc appears multiple times in the proof list, its grade is
    the **maximum** of the per-position grades (i.e. earliest hop wins).
    """
    if not proof_ids:
        return {}
    if mode == RAG_RELEVANCE_BINARY:
        return dict.fromkeys(proof_ids, 1)
    if mode == RAG_RELEVANCE_GRADED:
        n = len(proof_ids)
        grades: dict[str, int] = {}
        for idx, doc_id in enumerate(proof_ids):
            grade = max(1, n - idx)
            if grade > grades.get(doc_id, 0):
                grades[doc_id] = grade
        return grades
    raise ValueError(
        f"Unknown relevance mode {mode!r}; expected "
        f"{RAG_RELEVANCE_BINARY!r} or {RAG_RELEVANCE_GRADED!r}."
    )


# Order matters: Arango-stored rows use `proof` (because `insert_qa_row` remaps
# the in-memory `proof_list` field onto Arango's `proof`); in-memory rows still
# carry `proof_list`. We try them in this order.
_PROOF_FIELD_CANDIDATES: tuple[str, ...] = ("proof", "proof_list")


def _extract_proof_ids(row: dict, proof_field: str | None) -> list[str]:
    """Pull the ordered list of proof source_ids out of one golden row.

    If `proof_field` is given we use that exclusively; otherwise we try
    `proof` then `proof_list` so the same builder works for both shapes.
    """
    fields_to_try = (proof_field,) if proof_field else _PROOF_FIELD_CANDIDATES
    for field in fields_to_try:
        proof = row.get(field)
        if not proof:
            continue
        # Skip the formatted-string variant of `proof` produced by
        # `AcceptedQA.to_row_dict()` — that one is a string, not a list.
        if not isinstance(proof, list):
            continue
        ids: list[str] = []
        for pp in proof:
            sid = (pp or {}).get("source_id") if isinstance(pp, dict) else None
            if sid:
                ids.append(sid)
        if ids:
            return ids
    return []


def build_qrels(
    goldens: Iterable[dict],
    *,
    mode: str = RAG_RELEVANCE_BINARY,
    key_field: str = "_key",
    proof_field: str | None = None,
) -> dict[str, dict[str, int]]:
    """Build a `ranx`-compatible qrels dict from golden rows.

    Args:
        goldens: Iterable of golden QA rows (e.g. from `ArangoGateway.fetch_qa_rows`
            or the in-memory `AcceptedQA.to_row_dict()`). Each row must contain
            a stable key under `key_field` and a list of proof points (dicts
            with a `source_id`) under either `proof` or `proof_list`.
        mode: 'binary' (default) or 'graded'. See module docstring.
        key_field: Dict key holding the golden's stable id; defaults to Arango's
            `_key`. Pass `'qa_pair_key'` if you've already renamed it.
        proof_field: Optional override. If `None`, both `'proof'` and
            `'proof_list'` are tried in that order so the same builder works
            for Arango-persisted and in-memory rows.

    Returns:
        `{qa_key: {source_id: grade}}` — exactly the shape `ranx.Qrels.from_dict`
        accepts. Rows missing a key or with no proof source_ids are skipped so
        downstream metric computations don't divide by zero.

    Raises:
        ValueError: If `mode` is not one of the allowed values.
    """
    qrels: dict[str, dict[str, int]] = {}
    for row in goldens:
        key = row.get(key_field)
        if not key:
            continue
        proof_ids = _extract_proof_ids(row, proof_field)
        grades = _grades_for_proof_ids(proof_ids, mode)
        if grades:
            qrels[str(key)] = grades
    return qrels
