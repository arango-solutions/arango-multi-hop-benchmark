"""Tests for `multihop_eval.rag_eval.langfuse_sink.LangFuseSink`.

The library itself is optional and may or may not be installed. We patch the
module-level `_LangfuseClient` symbol to control which branch runs.
"""

from __future__ import annotations

from typing import Any

from multihop_eval.config import LangFuseConfig
from multihop_eval.rag_eval import langfuse_sink as sink_mod
from multihop_eval.rag_eval.langfuse_sink import LangFuseSink, LangFuseSyncResult
from multihop_eval.rag_eval.models import RagResponse, RetrievedChunk


def _resp(key: str = "q1") -> RagResponse:
    return RagResponse(
        system_name="rag_v1",
        qa_pair_key=key,
        question=f"why {key}?",
        answer="because",
        retrieved_chunks=[RetrievedChunk(doc_id="sources/a", rank=1)],
    )


class _FakeLangfuse:
    """In-memory stand-in for `langfuse.Langfuse`."""

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.traces: list[dict[str, Any]] = []
        self.flushed = False

    def trace(self, **kwargs: Any) -> None:
        self.traces.append(kwargs)

    def flush(self) -> None:
        self.flushed = True

    def get_scores(self, limit: int | None = None) -> list[dict[str, Any]]:
        return [{"trace_id": "q1", "name": "faithfulness", "value": 4}]


# ---------------------------------------------------------------------------
# Disabled / not-configured paths — every method must no-op gracefully.
# ---------------------------------------------------------------------------


def test_push_skipped_when_disabled():
    cfg = LangFuseConfig(enabled=False)
    sink = LangFuseSink(cfg)
    result = sink.push_responses([_resp()])
    assert isinstance(result, LangFuseSyncResult)
    assert result.pushed == 0
    assert result.skipped_reason == "langfuse_disabled_or_missing"


def test_pull_skipped_when_disabled():
    sink = LangFuseSink(LangFuseConfig(enabled=False))
    result = sink.pull_scores()
    assert result.pulled_scores == []
    assert result.skipped_reason == "langfuse_disabled_or_missing"


def test_skipped_when_enabled_without_keys():
    # `enabled=True` but no public/secret key -> still not configured.
    cfg = LangFuseConfig(enabled=True)
    sink = LangFuseSink(cfg)
    assert sink.push_responses([_resp()]).skipped_reason == "langfuse_disabled_or_missing"


def test_skipped_when_library_missing(monkeypatch):
    # Even with config fully populated, missing import -> no-op.
    monkeypatch.setattr(sink_mod, "_LangfuseClient", None)
    cfg = LangFuseConfig(
        enabled=True, public_key="pk", secret_key="sks"
    )  # type: ignore[arg-type]
    sink = LangFuseSink(cfg)
    result = sink.push_responses([_resp()])
    assert result.skipped_reason == "langfuse_disabled_or_missing"


# ---------------------------------------------------------------------------
# Enabled paths — patched client.
# ---------------------------------------------------------------------------


def test_push_creates_one_trace_per_response(monkeypatch):
    monkeypatch.setattr(sink_mod, "_LangfuseClient", _FakeLangfuse)
    cfg = LangFuseConfig(
        enabled=True, public_key="pk", secret_key="sks"
    )  # type: ignore[arg-type]
    sink = LangFuseSink(cfg)
    result = sink.push_responses([_resp("q1"), _resp("q2")])
    assert result.pushed == 2
    assert result.skipped_reason is None


def test_push_records_expected_trace_fields(monkeypatch):
    monkeypatch.setattr(sink_mod, "_LangfuseClient", _FakeLangfuse)
    cfg = LangFuseConfig(
        enabled=True, public_key="pk", secret_key="sks"
    )  # type: ignore[arg-type]
    sink = LangFuseSink(cfg)
    sink.push_responses([_resp("q1")])
    # We reach into the lazily-built client to verify the trace shape.
    client = sink._client_or_none()
    assert client is not None
    trace = client.traces[0]
    assert trace["name"] == "q1"
    assert trace["input"] == {"question": "why q1?"}
    assert trace["output"] == "because"
    assert trace["metadata"]["system_name"] == "rag_v1"
    assert trace["metadata"]["retrieved_doc_ids"] == ["sources/a"]
    assert client.flushed is True


def test_push_continues_through_per_trace_errors(monkeypatch):
    class _PartiallyFailing(_FakeLangfuse):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.calls = 0

        def trace(self, **kwargs: Any) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            super().trace(**kwargs)

    monkeypatch.setattr(sink_mod, "_LangfuseClient", _PartiallyFailing)
    cfg = LangFuseConfig(
        enabled=True, public_key="pk", secret_key="sks"
    )  # type: ignore[arg-type]
    result = LangFuseSink(cfg).push_responses([_resp("q1"), _resp("q2")])
    # Second trace succeeds even though the first raised.
    assert result.pushed == 1


def test_pull_returns_scores_from_client(monkeypatch):
    monkeypatch.setattr(sink_mod, "_LangfuseClient", _FakeLangfuse)
    cfg = LangFuseConfig(
        enabled=True, public_key="pk", secret_key="sks"
    )  # type: ignore[arg-type]
    result = LangFuseSink(cfg).pull_scores()
    assert result.pulled_scores == [
        {"trace_id": "q1", "name": "faithfulness", "value": 4}
    ]
    assert result.skipped_reason is None


def test_pull_handles_missing_scores_api(monkeypatch):
    class _NoScores(_FakeLangfuse):
        def __getattribute__(self, name):
            if name in {"get_scores", "fetch_scores"}:
                raise AttributeError(name)
            return super().__getattribute__(name)

    monkeypatch.setattr(sink_mod, "_LangfuseClient", _NoScores)
    cfg = LangFuseConfig(
        enabled=True, public_key="pk", secret_key="sks"
    )  # type: ignore[arg-type]
    result = LangFuseSink(cfg).pull_scores()
    assert result.skipped_reason == "langfuse_scores_api_unavailable"
