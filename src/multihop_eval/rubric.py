"""User-defined evaluation rubric.

A rubric is a list of `RubricField` items. Each field is a named criterion
the judge LLM should score on a numeric scale, with an optional weight used
to compute a weighted aggregate score per QA pair.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class RubricField(BaseModel):
    """A single named evaluation criterion."""

    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=10)
    scale_min: int = Field(default=1, ge=0, le=10)
    scale_max: int = Field(default=5, ge=1, le=100)
    weight: float = Field(default=1.0, gt=0.0, le=100.0)

    @field_validator("name")
    @classmethod
    def _name_is_identifier(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Rubric field name must not be blank.")
        if not all(ch.isalnum() or ch in "_-" for ch in cleaned):
            raise ValueError(
                "Rubric field name must contain only alphanumerics, underscore or hyphen."
            )
        return cleaned

    @model_validator(mode="after")
    def _scale_consistent(self) -> RubricField:
        if self.scale_min >= self.scale_max:
            raise ValueError(
                f"scale_min ({self.scale_min}) must be strictly less than scale_max "
                f"({self.scale_max})."
            )
        return self


DEFAULT_RUBRIC: list[RubricField] = [
    RubricField(
        name="factuality",
        description=(
            "Are every claim in the answer and every proof point directly supported by the "
            "cited source documents? Penalise hallucinations and unsupported assertions."
        ),
        weight=2.0,
    ),
    RubricField(
        name="faithfulness",
        description=(
            "Does the answer accurately summarise the relevant content from the cited "
            "documents without distortion or omission of necessary nuance?"
        ),
    ),
    RubricField(
        name="conciseness",
        description=(
            "Is the answer free of redundant filler, hedging, and unnecessary preamble while "
            "still covering every necessary point?"
        ),
    ),
    RubricField(
        name="multi_hop_genuineness",
        description=(
            "Does answering the question genuinely require combining evidence from multiple "
            "documents (rather than being answerable from any single document)?"
        ),
        weight=1.5,
    ),
    RubricField(
        name="persona_fit",
        description=(
            "Does the question read like a realistic question for the declared persona? "
            "Penalise textbook-style or unnaturally exhaustive phrasing."
        ),
    ),
]
