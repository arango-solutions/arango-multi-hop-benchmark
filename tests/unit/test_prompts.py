"""Tests for `multihop_eval.prompts`."""

from __future__ import annotations

import json

import pytest

from multihop_eval.personas import Persona
from multihop_eval.prompts import (
    SYSTEM_PROMPT_GEN,
    SYSTEM_PROMPT_MULTIHOP_CHECK,
    SYSTEM_PROMPT_RUBRIC,
    SYSTEM_PROMPT_VERIFY,
    build_gen_prompt,
    build_multihop_check_prompt,
    build_rubric_prompt,
    build_verify_prompt,
)
from multihop_eval.rubric import RubricField


def _persona() -> Persona:
    return Persona(
        label="domain_expert",
        instruction="Write as a curious domain expert and ask clearly.",
    )


def _docs() -> list[dict]:
    return [
        {"_id": "src/aaa111", "content": "Document A talks about wellness."},
        {"_id": "src/bbb222", "content": "Document B talks about retirement matching."},
        {"_id": "src/ccc333", "content": "Document C ties them together."},
    ]


# ---------------------------------------------------------------------------
# build_gen_prompt
# ---------------------------------------------------------------------------


def test_gen_prompt_mentions_every_source_id():
    prompt = build_gen_prompt(
        cluster_id="dom/cluster_test_0",
        docs=_docs(),
        edges=[("src/aaa111", "src/bbb222", 0.42)],
        persona=_persona(),
        required_hops=3,
    )
    for d in _docs():
        assert d["_id"] in prompt


def test_gen_prompt_includes_required_hops_and_cluster():
    prompt = build_gen_prompt(
        cluster_id="dom/cluster_alpha",
        docs=_docs(),
        edges=[],
        persona=_persona(),
        required_hops=4,
    )
    assert "Required hops : 4" in prompt
    assert "dom/cluster_alpha" in prompt
    assert "exactly 4 entries" in prompt


def test_gen_prompt_renders_persona_instruction():
    prompt = build_gen_prompt(
        cluster_id="x", docs=_docs(), edges=[], persona=_persona(), required_hops=2
    )
    assert "curious domain expert" in prompt


def test_system_prompt_gen_is_nonempty():
    assert "MULTI-HOP" in SYSTEM_PROMPT_GEN


# ---------------------------------------------------------------------------
# build_multihop_check_prompt
# ---------------------------------------------------------------------------


def test_multihop_prompt_inlines_required_hops_and_proof():
    proof = [{"point": "p1", "source_id": "src/aaa111"}]
    prompt = build_multihop_check_prompt(
        question="Q?",
        answer="A.",
        reasoning_chain="A->B",
        proof=proof,
        required_hops=2,
        content_blob="some content",
    )
    assert "Required hops   : 2" in prompt
    assert "src/aaa111" in prompt
    assert "genuine_hop_count" in prompt
    assert "MULTI-HOP" in SYSTEM_PROMPT_MULTIHOP_CHECK or "multi-hop" in SYSTEM_PROMPT_MULTIHOP_CHECK.lower()


# ---------------------------------------------------------------------------
# build_verify_prompt
# ---------------------------------------------------------------------------


def test_verify_prompt_includes_proof_and_content():
    prompt = build_verify_prompt(
        question="Q?",
        answer="A.",
        proof=[{"point": "p", "source_id": "src/x"}],
        content_blob="some content",
    )
    assert "corrected_proof" in prompt
    assert "src/x" in prompt
    assert "proof verification" in SYSTEM_PROMPT_VERIFY.lower()


# ---------------------------------------------------------------------------
# build_rubric_prompt — parametric on user fields
# ---------------------------------------------------------------------------


def test_rubric_prompt_lists_every_user_field_name_and_description():
    fields = [
        RubricField(
            name="factuality",
            description="Are claims supported by sources?",
            scale_min=1,
            scale_max=5,
            weight=2.0,
        ),
        RubricField(
            name="conciseness",
            description="Is the answer free of filler?",
            scale_min=0,
            scale_max=10,
            weight=1.0,
        ),
    ]
    prompt = build_rubric_prompt(
        question="Q?",
        answer="A.",
        proof=[],
        persona_label="domain_expert",
        rubric_fields=fields,
        content_blob="content",
    )
    for f in fields:
        assert f.name in prompt
        assert f.description in prompt
        assert f"{f.scale_min}-{f.scale_max}" in prompt
        assert f"weight {f.weight}" in prompt


def test_rubric_prompt_emits_schema_with_every_field_key():
    fields = [
        RubricField(name="alpha", description="alpha description here long enough"),
        RubricField(name="beta", description="beta description here long enough"),
    ]
    prompt = build_rubric_prompt(
        question="Q?",
        answer="A.",
        proof=[],
        persona_label="x",
        rubric_fields=fields,
        content_blob="x",
    )
    # Locate the schema example: it's the JSON object that comes after the
    # 'Output ONLY this JSON object:' marker.
    marker = "Output ONLY this JSON object:"
    tail = prompt[prompt.index(marker) + len(marker):].strip()
    schema = json.loads(tail)
    assert set(schema.keys()) == {"alpha", "beta"}
    for entry in schema.values():
        assert "score" in entry and "justification" in entry


def test_rubric_prompt_rejects_empty_field_list():
    with pytest.raises(ValueError):
        build_rubric_prompt(
            question="Q?",
            answer="A.",
            proof=[],
            persona_label="x",
            rubric_fields=[],
            content_blob="x",
        )


def test_rubric_system_prompt_is_nonempty():
    assert "judge" in SYSTEM_PROMPT_RUBRIC.lower()
