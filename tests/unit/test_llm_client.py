"""Tests for `multihop_eval.llm_client`."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from multihop_eval.config import LLMConfig
from multihop_eval.llm_client import (
    ContextLengthError,
    LLMClient,
    extract_json,
    strip_citations,
)

# ---------------------------------------------------------------------------
# Tiny fake Response + Session for LLMClient
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    status_code: int
    payload: Any = None
    text_body: str = ""

    def json(self) -> Any:
        return self.payload

    @property
    def text(self) -> str:
        return self.text_body


@dataclass
class _FakeSession:
    """Returns scripted responses; raises if `raise_on_call` set."""

    responses: list[Any] = field(default_factory=list)
    calls: int = 0

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int):
        self.calls += 1
        if not self.responses:
            raise AssertionError("FakeSession script exhausted")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok_response(content: str) -> _FakeResponse:
    return _FakeResponse(status_code=200, payload={"choices": [{"message": {"content": content}}]})


def _llm_config(**overrides) -> LLMConfig:
    base = {"api_key": "sk-test", "retries": 3, "backoff_base": 1, "timeout_s": 1}
    base.update(overrides)
    return LLMConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------


def test_extract_json_handles_bare_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_handles_fenced_json_block():
    raw = '```json\n{"a": 1, "b": [1,2]}\n```'
    assert extract_json(raw) == {"a": 1, "b": [1, 2]}


def test_extract_json_handles_plain_fenced_block():
    raw = '```\n{"x": "y"}\n```'
    assert extract_json(raw) == {"x": "y"}


def test_extract_json_handles_prose_around_object():
    raw = 'Sure! Here is the answer:\n{"verdict": "pass"}\nLet me know if you need more.'
    assert extract_json(raw) == {"verdict": "pass"}


def test_extract_json_raises_when_no_object():
    with pytest.raises(ValueError, match="No JSON object found"):
        extract_json("just a sentence with no braces")


# ---------------------------------------------------------------------------
# strip_citations
# ---------------------------------------------------------------------------


def test_strip_citations_removes_short_form():
    assert strip_citations("Some answer [abc123def].") == "Some answer ."


def test_strip_citations_removes_collection_prefixed_form():
    text = "First fact [my_sources/file__chunk_00012] and more."
    assert strip_citations(text) == "First fact  and more."


def test_strip_citations_keeps_text_when_no_citation():
    assert strip_citations("Plain prose with no markers.") == "Plain prose with no markers."


# ---------------------------------------------------------------------------
# LLMClient: success path
# ---------------------------------------------------------------------------


def test_llm_client_returns_assistant_content():
    session = _FakeSession(responses=[_ok_response("hello world")])
    client = LLMClient(_llm_config(), http=session)
    assert client.call("sys", "user") == "hello world"
    assert session.calls == 1


def test_llm_client_propagates_max_tokens_and_temperature(monkeypatch):
    captured: dict[str, Any] = {}

    class _Capturing:
        def post(self, url, *, headers, json, timeout):
            captured["json"] = json
            return _ok_response("ok")

    client = LLMClient(_llm_config(model="gpt-test"), http=_Capturing())
    client.call("S", "U", max_tokens=42, temperature=0.0)
    assert captured["json"]["model"] == "gpt-test"
    assert captured["json"]["max_tokens"] == 42
    assert captured["json"]["temperature"] == 0.0


# ---------------------------------------------------------------------------
# LLMClient: retry behaviour
# ---------------------------------------------------------------------------


def test_llm_client_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    session = _FakeSession(responses=[
        _FakeResponse(status_code=500, text_body="server boom"),
        _ok_response("eventual success"),
    ])
    client = LLMClient(_llm_config(retries=3), http=session)
    assert client.call("s", "u") == "eventual success"
    assert session.calls == 2


def test_llm_client_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    session = _FakeSession(
        responses=[_FakeResponse(status_code=500, text_body="boom")] * 3
    )
    client = LLMClient(_llm_config(retries=3), http=session)
    with pytest.raises(RuntimeError, match="LLM failed after 3 attempts"):
        client.call("s", "u")
    assert session.calls == 3


# ---------------------------------------------------------------------------
# LLMClient: context length errors
# ---------------------------------------------------------------------------


def test_llm_client_raises_context_length_immediately(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))
    session = _FakeSession(
        responses=[
            _FakeResponse(
                status_code=400,
                text_body="error: context_length_exceeded - reduce the length",
            )
        ]
    )
    client = LLMClient(_llm_config(retries=3), http=session)
    with pytest.raises(ContextLengthError):
        client.call("s", "u")
    # Should not have retried — context errors are not transient.
    assert session.calls == 1
    assert sleep_calls == []


def test_llm_client_detects_context_length_in_exception_message(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    session = _FakeSession(
        responses=[RuntimeError("This model's maximum context length is 8192 tokens")]
    )
    client = LLMClient(_llm_config(retries=3), http=session)
    with pytest.raises(ContextLengthError):
        client.call("s", "u")
    assert session.calls == 1
