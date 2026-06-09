"""Run router — start/stop a generation run and stream progress via SSE.

Replaces the Streamlit Run tab's thread + queue + poll loop with a
server-side :class:`RunHandle` per session and a Server-Sent Events stream
the React tab consumes with ``EventSource``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from multihop_eval.web.routers.deps import get_session
from multihop_eval.web.run_manager import (
    build_runner,
    run_status_dict,
    sse_event_stream,
    start_run,
)
from multihop_eval.web.schemas import RunStatusResponse
from multihop_eval.web.sessions import ServerSession, store

router = APIRouter(prefix="/run", tags=["run"])

_ACTIVE = {"running"}


@router.post("/start", response_model=RunStatusResponse)
def start(session: ServerSession = Depends(get_session)) -> RunStatusResponse:
    if session.app_config is None:
        raise HTTPException(status_code=409, detail="Save a configuration before running.")
    if not session.is_connected():
        raise HTTPException(status_code=409, detail="Connect to ArangoDB before running.")
    if session.run is not None and session.run.status in _ACTIVE:
        raise HTTPException(status_code=409, detail="A run is already in progress.")

    runner = build_runner(session.app_config)
    session.run = start_run(session.app_config, runner)
    return RunStatusResponse(**run_status_dict(session.run))


@router.post("/stop", response_model=RunStatusResponse)
def stop(session: ServerSession = Depends(get_session)) -> RunStatusResponse:
    if session.run is None:
        raise HTTPException(status_code=409, detail="No run to stop.")
    session.run.control.request_stop()
    return RunStatusResponse(**run_status_dict(session.run))


@router.get("/status", response_model=RunStatusResponse)
def status(session: ServerSession = Depends(get_session)) -> RunStatusResponse:
    return RunStatusResponse(**run_status_dict(session.run))


@router.get("/events")
def events(
    session: str | None = None,
    x_arango_session: str | None = Header(default=None),
) -> StreamingResponse:
    """Server-Sent Events stream for the active run.

    ``EventSource`` cannot set custom headers, so the session token is taken
    from the ``session`` query parameter (falling back to the header for
    non-browser callers such as tests).
    """
    token = session or x_arango_session
    resolved = store.get(token)
    if resolved is None or resolved.run is None:
        raise HTTPException(status_code=404, detail="No active run for this session.")
    return StreamingResponse(
        sse_event_stream(resolved.run),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
