"""Load RAG responses from a JSON Lines file.

JSONL is the contract we hand to the RAG-team: one line per (system, question).
Each line is validated against `RagResponse`; the loader collects every error
with the offending line number so the UI can surface them all in one go
rather than failing on the first bad row.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from multihop_eval.rag_eval.models import RagResponse


@dataclass
class JsonlParseError:
    """One row that failed to parse / validate."""

    line_number: int  # 1-based
    raw: str
    message: str


@dataclass
class JsonlLoadResult:
    """Outcome of loading a JSONL response file."""

    responses: list[RagResponse] = field(default_factory=list)
    errors: list[JsonlParseError] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    def systems(self) -> list[str]:
        """Sorted list of distinct `system_name` values present."""
        return sorted({r.system_name for r in self.responses})


def _iter_lines(source: Path | Iterable[str]) -> Iterator[tuple[int, str]]:
    """Yield `(line_number, raw_line)` from a path or any iterable of strings."""
    if isinstance(source, Path):
        with source.open("r", encoding="utf-8") as fh:
            for idx, raw in enumerate(fh, start=1):
                yield idx, raw
    else:
        for idx, raw in enumerate(source, start=1):
            yield idx, raw


def load_responses(source: Path | Iterable[str]) -> JsonlLoadResult:
    """Parse + validate a JSONL stream of `RagResponse` rows.

    Blank lines and lines that are pure whitespace are silently skipped.
    Every other failure becomes a `JsonlParseError` so the caller can decide
    whether to abort or proceed with the rows that did parse.

    Args:
        source: Either a `pathlib.Path` to a `.jsonl` file or any iterable of
            string lines (handy for tests).

    Returns:
        `JsonlLoadResult` with the successfully-parsed `responses` and any
        per-line `errors`. Use `result.success` for a quick green-light check.
    """
    result = JsonlLoadResult()
    for line_number, raw in _iter_lines(source):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            payload: Any = json.loads(stripped)
        except json.JSONDecodeError as exc:
            result.errors.append(
                JsonlParseError(line_number=line_number, raw=stripped, message=f"invalid JSON: {exc}")
            )
            continue
        if not isinstance(payload, dict):
            result.errors.append(
                JsonlParseError(
                    line_number=line_number,
                    raw=stripped,
                    message=f"expected JSON object, got {type(payload).__name__}",
                )
            )
            continue
        try:
            result.responses.append(RagResponse.model_validate(payload))
        except ValidationError as exc:
            result.errors.append(
                JsonlParseError(line_number=line_number, raw=stripped, message=str(exc))
            )
    return result
