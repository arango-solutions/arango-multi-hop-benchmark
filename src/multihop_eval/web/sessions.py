"""In-memory per-client session registry.

The Streamlit app kept the live :class:`ArangoGateway`, the saved
:class:`AppConfig`, and the in-flight run on ``st.session_state``. With a
React SPA + FastAPI backend that state lives server-side, keyed by an opaque
session token the browser sends in the ``X-Arango-Session`` header (or, for
``EventSource`` which cannot set headers, a ``session`` query parameter).

The store is a process-local dict. BYOC deployments run a single container,
so a dict is sufficient; swap for a shared store only if the service is ever
horizontally scaled.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from multihop_eval.clients.amp import AmpEnv
from multihop_eval.clients.arango_gateway import ArangoGateway, CollectionInfo
from multihop_eval.config import AppConfig
from multihop_eval.web.run_manager import RunHandle

STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTED_AMP = "connected_amp"
STATUS_CONNECTED_MANUAL = "connected_manual"
STATUS_ERROR = "error"

SESSION_HEADER = "X-Arango-Session"


@dataclass
class ServerSession:
    """All long-lived state for one browser session."""

    token: str
    gateway: ArangoGateway | None = None
    db: str | None = None
    conn_status: str = STATUS_DISCONNECTED
    conn_error: str | None = None
    last_tested: str | None = None
    amp_env: AmpEnv | None = None

    db_list: list[str] | None = None
    collections: list[CollectionInfo] | None = None
    cluster_ids: list[str] | None = None

    app_config: AppConfig | None = None
    run: RunHandle | None = None

    # Cached result of the most recent RAG-eval run (list[RagEvalRun]); kept
    # as Any to avoid importing the rag_eval models into the session module.
    rag_eval_runs: list[Any] | None = field(default=None)

    def is_connected(self) -> bool:
        return self.conn_status in {STATUS_CONNECTED_AMP, STATUS_CONNECTED_MANUAL}

    def disconnect(self) -> None:
        self.gateway = None
        self.db = None
        self.conn_status = STATUS_DISCONNECTED
        self.conn_error = None
        self.db_list = None
        self.collections = None
        self.cluster_ids = None


class SessionStore:
    """Thread-safe registry of :class:`ServerSession` keyed by token."""

    def __init__(self) -> None:
        self._sessions: dict[str, ServerSession] = {}
        self._lock = threading.Lock()

    def get(self, token: str | None) -> ServerSession | None:
        if not token:
            return None
        with self._lock:
            return self._sessions.get(token)

    def get_or_create(self, token: str | None) -> ServerSession:
        """Return the session for ``token`` or mint a fresh one.

        The freshly-minted session's token differs from the (unknown) token
        the caller supplied, so callers should always echo ``session.token``
        back to the client.
        """
        with self._lock:
            if token and token in self._sessions:
                return self._sessions[token]
            new_token = secrets.token_urlsafe(24)
            session = ServerSession(token=new_token)
            self._sessions[new_token] = session
            return session

    def remove(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


# Process-wide singleton used by the routers.
store = SessionStore()
