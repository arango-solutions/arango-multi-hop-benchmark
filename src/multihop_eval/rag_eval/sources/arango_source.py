"""Load RAG responses from an Arango collection.

The Arango sink shares the JSONL schema, so loading is just `fetch_rag_responses`
followed by pydantic validation. Validation errors are collected per row (rather
than raised) so the UI can show the bad rows without losing the good ones —
matching the JSONL loader's contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from multihop_eval.rag_eval.models import RagResponse


class _GatewayLike(Protocol):
    """The slice of `ArangoGateway` this loader needs.

    Tests pass a `FakeArangoGateway` that implements these two methods; prod
    code passes the real gateway.
    """

    def fetch_rag_responses(
        self,
        collection: str,
        *,
        system_name: str | None = ...,
        qa_keys: list[str] | None = ...,
        limit: int | None = ...,
    ) -> list[dict[str, Any]]: ...

    def list_rag_systems(self, collection: str) -> list[str]: ...


@dataclass
class ArangoRowError:
    """One row that came back from Arango but failed `RagResponse` validation."""

    arango_key: str
    message: str


@dataclass
class ArangoLoadResult:
    """Outcome of loading RAG responses from an Arango collection."""

    responses: list[RagResponse] = field(default_factory=list)
    errors: list[ArangoRowError] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


def load_responses(
    gateway: _GatewayLike,
    collection: str,
    *,
    system_name: str | None = None,
    qa_keys: list[str] | None = None,
    limit: int | None = None,
) -> ArangoLoadResult:
    """Fetch and validate RAG responses from an Arango collection.

    Args:
        gateway: `ArangoGateway`-compatible object.
        collection: Name of the response collection.
        system_name: Filter for one system; pass `None` to read every system.
        qa_keys: Optional subset of golden keys to load responses for.
        limit: Optional cap on the number of rows returned.

    Returns:
        `ArangoLoadResult` with parsed `responses` and per-row `errors`.
    """
    rows = gateway.fetch_rag_responses(
        collection,
        system_name=system_name,
        qa_keys=qa_keys,
        limit=limit,
    )
    result = ArangoLoadResult()
    for row in rows:
        # Strip Arango bookkeeping fields before validation so pydantic doesn't
        # ignore them silently and so the round-trip stays predictable.
        payload = {k: v for k, v in row.items() if not k.startswith("_")}
        try:
            result.responses.append(RagResponse.model_validate(payload))
        except ValidationError as exc:
            result.errors.append(
                ArangoRowError(arango_key=str(row.get("_key", "")), message=str(exc))
            )
    return result


def list_systems(gateway: _GatewayLike, collection: str) -> list[str]:
    """Return the distinct `system_name` values found in the collection."""
    return gateway.list_rag_systems(collection)
