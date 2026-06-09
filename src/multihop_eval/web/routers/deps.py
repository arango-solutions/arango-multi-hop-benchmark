"""Shared FastAPI dependencies for resolving the per-client session."""

from __future__ import annotations

from fastapi import Header, Response

from multihop_eval.web.sessions import SESSION_HEADER, ServerSession, store


def get_session(
    response: Response,
    x_arango_session: str | None = Header(default=None),
) -> ServerSession:
    """Resolve the caller's :class:`ServerSession`, minting one if needed.

    The (possibly new) token is echoed back in the ``X-Arango-Session``
    response header so the SPA can persist it and reuse it on later calls.
    """
    session = store.get_or_create(x_arango_session)
    response.headers[SESSION_HEADER] = session.token
    return session
