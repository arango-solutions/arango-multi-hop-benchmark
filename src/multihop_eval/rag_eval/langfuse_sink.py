"""Optional LangFuse sink for human-annotation metrics.

LangFuse is an external SaaS where annotators score traces (faithfulness,
relevancy, hallucination flags, coherence, completeness). This module:

* Pushes one trace per `RagResponse` so annotators can rate it.
* Pulls back any scores annotators have applied since the last sync.

The whole thing is **strictly optional**:

* `LangFuseConfig.enabled` is `False` by default. When disabled, every
  function in this module is a no-op that returns sensible defaults.
* The `langfuse` library is declared as an *optional* pyproject extra
  (`pip install multihop-eval[langfuse]`). When the import fails we fall
  back to no-op semantics with a warning logged once.

The UI hides the LangFuse panel entirely unless `is_configured()` is true.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from multihop_eval.config import LangFuseConfig
from multihop_eval.rag_eval.models import RagResponse

log = logging.getLogger(__name__)

# We import `langfuse` lazily so a project without it installed still loads
# this module fine. The "is the library installed?" check happens inside the
# class so the user gets a clear error only when they actually try to push.
try:  # pragma: no cover - exercised by environment, not unit tests
    from langfuse import Langfuse as _LangfuseClient  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001 - any import error means we no-op
    _LangfuseClient = None  # type: ignore[assignment]


@dataclass
class LangFuseSyncResult:
    """Outcome of a push / pull operation."""

    pushed: int = 0
    pulled_scores: list[dict[str, Any]] = field(default_factory=list)
    skipped_reason: str | None = None


class LangFuseSink:
    """Thin wrapper around the LangFuse SDK with a hard kill-switch.

    `enabled=False` -> every method short-circuits with a `skipped_reason`.
    Library missing -> same. This means the rest of the codebase can call
    `sink.push_responses(...)` unconditionally without if-blocks.
    """

    def __init__(self, config: LangFuseConfig) -> None:
        self.config = config
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # Internal: lazy client construction.
    # ------------------------------------------------------------------

    def _client_or_none(self) -> Any | None:
        if not self.config.is_configured():
            return None
        if _LangfuseClient is None:
            log.warning(
                "LangFuse is enabled but the `langfuse` package isn't installed. "
                "Install with `pip install multihop-eval[langfuse]` to enable the sink."
            )
            return None
        if self._client is None:
            self._client = _LangfuseClient(
                public_key=self.config.public_key.get_secret_value() if self.config.public_key else None,
                secret_key=self.config.secret_key.get_secret_value() if self.config.secret_key else None,
                host=self.config.host,
            )
        return self._client

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------

    def push_responses(
        self,
        responses: list[RagResponse],
        *,
        system_name_tag: str = "system_name",
    ) -> LangFuseSyncResult:
        """Create one LangFuse trace per response so annotators can score them.

        Each trace carries:
          * `name` = `qa_pair_key`
          * `input` = the question
          * `output` = the generated answer
          * `metadata` = retrieved chunk ids + the system_name (under the
            `system_name_tag` key) for filtering inside the LangFuse UI.

        Returns a `LangFuseSyncResult` describing how many traces were created
        (or why the push was skipped).
        """
        client = self._client_or_none()
        if client is None:
            return LangFuseSyncResult(skipped_reason="langfuse_disabled_or_missing")
        pushed = 0
        for r in responses:
            try:
                client.trace(
                    name=r.qa_pair_key,
                    input={"question": r.question},
                    output=r.answer,
                    metadata={
                        system_name_tag: r.system_name,
                        "retrieved_doc_ids": [c.doc_id for c in r.retrieved_chunks],
                    },
                )
                pushed += 1
            except Exception as exc:  # noqa: BLE001 - one trace failure shouldn't abort
                log.warning("LangFuse trace push failed for %s: %s", r.qa_pair_key, exc)
        # Best-effort flush; some SDK versions return None.
        flush = getattr(client, "flush", None)
        if callable(flush):
            try:
                flush()
            except Exception as exc:  # noqa: BLE001
                log.warning("LangFuse flush failed: %s", exc)
        return LangFuseSyncResult(pushed=pushed)

    def pull_scores(self, *, limit: int | None = None) -> LangFuseSyncResult:
        """Return any annotator scores LangFuse has on file.

        The shape of `score` rows depends on the LangFuse SDK version; we
        pass them through unchanged so the UI / exporter can render whatever
        the SDK gives back.
        """
        client = self._client_or_none()
        if client is None:
            return LangFuseSyncResult(skipped_reason="langfuse_disabled_or_missing")
        fetch_scores = getattr(client, "get_scores", None) or getattr(client, "fetch_scores", None)
        if not callable(fetch_scores):
            return LangFuseSyncResult(skipped_reason="langfuse_scores_api_unavailable")
        try:
            raw = fetch_scores(limit=limit) if limit else fetch_scores()
        except Exception as exc:  # noqa: BLE001
            log.warning("LangFuse score fetch failed: %s", exc)
            return LangFuseSyncResult(skipped_reason=f"fetch_failed: {exc}")
        scores: list[dict[str, Any]] = []
        for item in raw or []:
            if isinstance(item, dict):
                scores.append(item)
            else:
                scores.append({"raw": str(item)})
        return LangFuseSyncResult(pulled_scores=scores)
