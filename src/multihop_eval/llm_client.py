"""LLM client wrapper around an OpenAI-compatible chat-completions API.

Responsibilities:
  * Send a `(system_prompt, user_prompt)` pair to the chat endpoint.
  * Retry transient failures with exponential backoff.
  * Detect and raise `ContextLengthError` *immediately* (no retry) so the
    pipeline can shrink the subgraph and try again instead of burning quota.
  * Provide stateless helpers `extract_json` and `strip_citations` that the
    rest of the pipeline relies on.

The HTTP transport is injected via a `requests.Session`-compatible object so
unit tests can stub it without touching the network.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Protocol

import requests

from multihop_eval.config import LLMConfig

log = logging.getLogger(__name__)


CITATION_RE = re.compile(r"\[(?:[a-zA-Z_]+/)?[^\]]{3,120}\]")
"""Matches inline citations like `[some_prefix/abc123]` or `[abc123]`.

Used to scrub citation markers from generated answers — proof goes in a
separate list and the human-facing answer must read as plain prose.
"""

CONTEXT_ERROR_KEYWORDS: tuple[str, ...] = (
    "context_length_exceeded",
    "maximum context",
    "too many tokens",
    "token limit",
    "context window",
    "reduce the length",
)


class ContextLengthError(RuntimeError):
    """Raised when the LLM rejects a request for being too long.

    Surfaced separately from generic transport errors so callers can shrink
    the subgraph instead of retrying the same oversized prompt.
    """


class HttpClient(Protocol):
    """Subset of `requests.Session` used by `LLMClient` — for test injection."""

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int):
        ...


class LLMClient:
    """OpenAI-compatible chat-completions client with retry + ctx-len handling."""

    def __init__(self, config: LLMConfig, *, http: HttpClient | None = None) -> None:
        self.config = config
        self._http: HttpClient = http or requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a chat-completion request and return the assistant message text.

        Retries up to `config.retries` times with exponential backoff for
        transient errors. Raises `ContextLengthError` immediately for
        context-window failures so the caller can recover with a smaller prompt.
        """
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": (
                temperature if temperature is not None else self.config.temperature
            ),
        }

        last_error: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            try:
                resp = self._http.post(
                    self.config.api_url,
                    headers=self._headers,
                    json=payload,
                    timeout=self.config.timeout_s,
                )
                if resp.status_code >= 400:
                    body = resp.text[:400] if hasattr(resp, "text") else ""
                    raise RuntimeError(f"HTTP {resp.status_code}: {body}")
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except ContextLengthError:
                raise
            except Exception as exc:
                err_str = str(exc).lower()
                if _is_context_length_error(err_str):
                    raise ContextLengthError(str(exc)) from exc
                last_error = exc
                if attempt < self.config.retries:
                    wait = self.config.backoff_base ** attempt
                    log.warning(
                        "LLM attempt %d/%d failed: %s. Retry in %ds.",
                        attempt,
                        self.config.retries,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    break

        raise RuntimeError(
            f"LLM failed after {self.config.retries} attempts: {last_error}"
        )


def _is_context_length_error(err_lower: str) -> bool:
    return any(kw in err_lower for kw in CONTEXT_ERROR_KEYWORDS)


def extract_json(raw: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM response.

    Handles ```json fenced blocks, plain ``` fences, and free-text-around-JSON
    by locating the outermost `{ ... }` braces. Raises `ValueError` with a
    helpful preview if no object is found.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop fence opening ("```" or "```json"); drop trailing fence if present.
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0 or end <= start:
        raise ValueError(f"No JSON object found in LLM response. Preview: {raw[:300]!r}")
    return json.loads(text[start:end])


def strip_citations(text: str) -> str:
    """Remove `[source_id]` style citation markers from prose."""
    return CITATION_RE.sub("", text).strip()
