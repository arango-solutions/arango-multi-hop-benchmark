"""Question personas — each persona conditions the LLM's question style.

Personas are user-editable from the Streamlit Configure tab. The defaults
ship as domain-neutral starting points; tailor them for the domain of the
corpus being evaluated.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Persona(BaseModel):
    """A named question style that the generator LLM should imitate."""

    label: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Short identifier stored on every QA row, e.g. 'domain_expert'.",
    )
    instruction: str = Field(
        ...,
        min_length=10,
        description="The 'write as a …' instruction injected into the generation prompt.",
    )

    @field_validator("label")
    @classmethod
    def _label_is_slug(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Persona label must not be blank.")
        # Keep labels safe for filenames, ArangoDB attribute keys, and CSV exports.
        if any(ch in cleaned for ch in ("/", "\\", "\n", "\t")):
            raise ValueError("Persona label must not contain slashes or whitespace control chars.")
        return cleaned


DEFAULT_PERSONAS: list[Persona] = [
    Persona(
        label="domain_expert",
        instruction=(
            "Write as a domain expert at a mid-to-large organisation who needs to make a "
            "practical decision about an internal program, policy, or population. State the "
            "situation briefly and ask a focused question about what approach to take or what "
            "the tradeoffs are. Sound informed but not a specialist. 2-3 sentences max. Don't "
            "over-explain the organisational background."
        ),
    ),
    Persona(
        label="analyst",
        instruction=(
            "Write as an analyst looking up a specific piece of information from a publication. "
            "Ask a clear, direct question based on what the documents contain. Keep it short "
            "and factual — 1 to 2 sentences max."
        ),
    ),
]
