"""Prompt templates and prompt builders.

System prompts are constants; user prompts are produced by `build_*` functions
that take the runtime data (subgraph contents, persona, rubric, ...) and
return a fully-formed string. Keeping prompts in one module makes it trivial
to tweak wording without touching pipeline logic.

The rubric prompt is parametric on the user's `RubricField` list, so adding
a new criterion in the UI immediately changes what the judge LLM scores.
"""

from __future__ import annotations

import json
from typing import Any

from multihop_eval.personas import Persona
from multihop_eval.rubric import RubricField

# ============================================================
# STEP 1 — GENERATION
# ============================================================


SYSTEM_PROMPT_GEN = """\
You are an evaluation dataset generator specialising in MULTI-HOP questions
that demonstrate the superiority of Graph RAG over Vector RAG.

You receive semantically related HR, benefits, and consulting publications connected by a similarity graph.
Use the graph structure to design a reasoning chain that traverses MULTIPLE documents.

A multi-hop question CANNOT be answered from any single document alone.
Each document in the chain must contribute a NECESSARY and DISTINCT piece of evidence.

Rules:
1. The question MUST require at least the number of hops in "Required hops".
2. Each hop must add NEW evidence that is NECESSARY — not just corroborating.
3. No single document can provide a complete answer on its own.
4. Every proof point MUST cite its exact source _id.
5. Do NOT invent facts not present in the provided content.
6. QUESTION REALISM: HR professionals asking questions often focus on a specific
   program, policy, or employee population without spelling out all the background.
   The question should feel like something a real HR practitioner would ask —
   grounded and practical, not like a textbook exercise. Give enough context to
   make it answerable, but not so much that you've basically given the answer away.
7. ANSWER FORMAT: plain prose only. No inline citations, no [source_id]
   markers inside the answer. All citations go in the proof list only.
8. Output ONLY valid JSON. No preamble, no markdown outside the JSON block.
"""


def build_gen_prompt(
    cluster_id: str,
    docs: list[dict[str, Any]],
    edges: list[tuple[str, str, float]],
    persona: Persona,
    required_hops: int,
) -> str:
    """Build the user prompt for question generation."""

    def short(doc_id: str) -> str:
        return doc_id.split("/")[-1]

    graph_lines = ["Similarity graph edges (higher score = more similar):"]
    for f, t, s in edges:
        graph_lines.append(f"  {short(f)}  <-->  {short(t)}  (score={s:.4f})")

    content_blob = "\n\n---\n\n".join(
        f"[SOURCE _id: {d['_id']}]\n{d.get('content') or json.dumps(d, indent=2)}"
        for d in docs
    )
    source_ids_hint = "\n".join(f"  - {d['_id']}" for d in docs)

    newline = "\n"
    return f"""
Cluster ID    : {cluster_id}
Required hops : {required_hops}

{newline.join(graph_lines)}

Available source _ids:
{source_ids_hint}

CRITICAL: The question must be answerable ONLY by combining evidence from
{required_hops} or more of the above documents.

=== QUESTION STYLE ===
{persona.instruction}

=== DOCUMENT CONTENT ===
{content_blob}
=== END CONTENT ===

Output ONLY this JSON:
{{
  "question":        "<realistic question — lean, not exhaustive — requiring {required_hops}+ docs>",
  "answer":          "<plain prose — NO inline citations, NO [source_id] markers>",
  "reasoning_chain": "<1-2 sentences: doc A contributes X → doc B contributes Y → ...>",
  "proof": [
    {{"point": "<necessary fact from doc A>",            "source_id": "<_id of doc A>"}},
    {{"point": "<necessary fact from doc B, different>", "source_id": "<_id of doc B>"}}
  ]
}}

The proof list must have exactly {required_hops} entries, each from a DIFFERENT source_id.
"""


# ============================================================
# STEP 2 — MULTI-HOP VALIDATION
# ============================================================


SYSTEM_PROMPT_MULTIHOP_CHECK = """\
You are a strict multi-hop reasoning validator for an HR and benefits QA dataset.

A document counts as a genuine hop only if ALL three hold:
  (a) The cited fact is grounded in that document's content.
  (b) Removing it would make the answer incomplete or wrong.
  (c) The fact is distinct from what other cited documents already provide.

Be strict. If in doubt, mark as "fail". Output ONLY valid JSON.
"""


def build_multihop_check_prompt(
    question: str,
    answer: str,
    reasoning_chain: str,
    proof: list[dict[str, Any]],
    required_hops: int,
    content_blob: str,
) -> str:
    return f"""
Question        : {question}
Answer          : {answer}
Reasoning chain : {reasoning_chain}
Required hops   : {required_hops}

Proof points:
{json.dumps(proof, indent=2)}

Source content:
=== BEGIN SOURCE ===
{content_blob}
=== END SOURCE ===

Output ONLY this JSON:
{{
  "verdict": "pass" | "fail",
  "genuine_hop_count": <int>,
  "is_multihop": true | false,
  "reason": "<brief explanation>",
  "genuine_source_ids": ["<_id1>", ...]
}}

"verdict" = "pass" only when genuine_hop_count >= {required_hops} AND is_multihop = true.
"""


# ============================================================
# STEP 3 — PROOF VERIFICATION
# ============================================================


SYSTEM_PROMPT_VERIFY = """\
You are a strict proof verification agent for an HR and benefits QA dataset.
Every proof point must be directly supported by the source content.
Correct any hallucinated or wrongly attributed points. Fix wrong source_ids.
Return "pass" if all points are now correct, "fail" if you cannot ground them.
Output ONLY valid JSON, no extra text.
"""


def build_verify_prompt(
    question: str,
    answer: str,
    proof: list[dict[str, Any]],
    content_blob: str,
) -> str:
    return f"""
Question: {question}
Answer:   {answer}

Proof points to verify:
{json.dumps(proof, indent=2)}

Source content:
=== BEGIN SOURCE ===
{content_blob}
=== END SOURCE ===

Output ONLY this JSON:
{{
  "verdict": "pass" | "fail",
  "corrected_proof": [
    {{"point": "<verified or corrected fact>", "source_id": "<correct _id>"}}
  ],
  "notes": "<what was changed, or 'all correct'>"
}}
"""


# ============================================================
# STEP 4 — RUBRIC SCORING
# ============================================================


SYSTEM_PROMPT_RUBRIC = """\
You are an impartial evaluation judge.
You score each criterion strictly and INDEPENDENTLY based ONLY on the source content
and the QA pair you are given. Output ONLY valid JSON, no preamble.
"""


def build_rubric_prompt(
    *,
    question: str,
    answer: str,
    proof: list[dict[str, Any]],
    persona_label: str,
    rubric_fields: list[RubricField],
    content_blob: str,
) -> str:
    """Build the user prompt that asks the judge LLM to score a QA pair.

    The output schema is parametric on the rubric — every field name supplied
    by the user must appear as a top-level key in the response JSON.
    """
    if not rubric_fields:
        raise ValueError("rubric_fields must contain at least one field.")

    # Field instructions table.
    bullets = []
    for f in rubric_fields:
        bullets.append(
            f"- {f.name} (score {f.scale_min}-{f.scale_max}, weight {f.weight}): {f.description}"
        )

    # Schema example showing every field.
    example_obj = {
        f.name: {"score": f.scale_min, "justification": "<one short sentence>"}
        for f in rubric_fields
    }

    return f"""
Persona expected: {persona_label}

Question : {question}
Answer   : {answer}

Proof points:
{json.dumps(proof, indent=2)}

Source content:
=== BEGIN SOURCE ===
{content_blob}
=== END SOURCE ===

Score the following criteria — and ONLY these criteria:
{chr(10).join(bullets)}

Rules:
* Use only the source content above; do NOT invoke outside knowledge.
* Each score must be an integer (or float) within the stated range.
* Do not skip any criterion. Missing criteria fail validation.

Output ONLY this JSON object:
{json.dumps(example_obj, indent=2)}
"""
