"""Connection router — Arango connect/disconnect, AMP detect, discovery.

Ports the logic from the former Streamlit ``connection_panel`` into stateless
HTTP endpoints. The live :class:`ArangoGateway` is stashed on the caller's
:class:`ServerSession` so the Config and Run endpoints can reuse it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from multihop_eval.clients.amp import detect_amp
from multihop_eval.clients.arango_gateway import ArangoGateway
from multihop_eval.config import AUTH_MODE_PASSWORD, ArangoConfig
from multihop_eval.web.routers.deps import get_session
from multihop_eval.web.schemas import (
    AmpInfo,
    ClustersResponse,
    CollectionItem,
    CollectionsResponse,
    ConnectionStatus,
    ConnectRequest,
    DatabasesResponse,
)
from multihop_eval.web.sessions import (
    STATUS_CONNECTED_AMP,
    STATUS_CONNECTED_MANUAL,
    STATUS_ERROR,
    ServerSession,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/connection", tags=["connection"])

DEFAULT_DB_NAME = "_system"


def _amp_info(session: ServerSession) -> AmpInfo:
    """Detect AMP (caching the result on the session) and describe it."""
    detected = detect_amp()
    if detected is not None:
        session.amp_env = detected
    amp = session.amp_env
    return AmpInfo(
        detected=amp is not None,
        deployment_name=amp.deployment_name if amp else None,
        endpoint=amp.endpoint if amp else None,
    )


def _status(session: ServerSession, amp: AmpInfo) -> ConnectionStatus:
    return ConnectionStatus(
        status=session.conn_status,
        db=session.db,
        error=session.conn_error,
        last_tested=session.last_tested,
        amp=amp,
    )


def _stash_gateway(session: ServerSession, gateway: ArangoGateway, *, status: str, db: str) -> None:
    session.gateway = gateway
    session.db = db
    session.conn_status = status
    session.conn_error = None
    session.last_tested = datetime.now(UTC).isoformat(timespec="seconds")
    session.db_list = None
    session.collections = None
    session.cluster_ids = None


def _build_gateway_or_error(session: ServerSession, cfg: ArangoConfig) -> ArangoGateway | None:
    try:
        gateway = ArangoGateway(cfg)
    except Exception as exc:  # noqa: BLE001 - surface every reason to the UI
        session.conn_status = STATUS_ERROR
        session.conn_error = str(exc)
        return None
    if not gateway.ping():
        session.conn_status = STATUS_ERROR
        session.conn_error = "Ping failed — credentials or endpoint may be wrong."
        return None
    return gateway


def _require_gateway(session: ServerSession) -> ArangoGateway:
    if session.gateway is None:
        raise HTTPException(status_code=409, detail="Not connected to ArangoDB.")
    return session.gateway


@router.get("/status", response_model=ConnectionStatus)
def get_status(session: ServerSession = Depends(get_session)) -> ConnectionStatus:
    return _status(session, _amp_info(session))


@router.get("/amp", response_model=AmpInfo)
def get_amp(session: ServerSession = Depends(get_session)) -> AmpInfo:
    return _amp_info(session)


@router.post("/connect", response_model=ConnectionStatus)
def connect(req: ConnectRequest, session: ServerSession = Depends(get_session)) -> ConnectionStatus:
    db = req.db or DEFAULT_DB_NAME
    if req.mode == "amp":
        amp = detect_amp()
        if amp is None:
            raise HTTPException(status_code=400, detail="No AMP environment detected.")
        session.amp_env = amp
        try:
            cfg = ArangoConfig.from_amp(amp, db=db)
        except Exception as exc:  # noqa: BLE001 - invalid env / missing token
            session.conn_status = STATUS_ERROR
            session.conn_error = f"AMP config invalid: {exc}"
            return _status(session, _amp_info(session))
        gateway = _build_gateway_or_error(session, cfg)
        if gateway is not None:
            _stash_gateway(session, gateway, status=STATUS_CONNECTED_AMP, db=db)
        return _status(session, _amp_info(session))

    # Manual password mode.
    if not req.host:
        raise HTTPException(status_code=400, detail="host is required for password mode.")
    try:
        cfg = ArangoConfig(  # type: ignore[call-arg]
            host=req.host,
            db=db,
            username=req.username,
            password=req.password or None,
            auth_mode=AUTH_MODE_PASSWORD,
        )
    except Exception as exc:  # noqa: BLE001
        session.conn_status = STATUS_ERROR
        session.conn_error = str(exc)
        return _status(session, _amp_info(session))
    gateway = _build_gateway_or_error(session, cfg)
    if gateway is not None:
        _stash_gateway(session, gateway, status=STATUS_CONNECTED_MANUAL, db=db)
    return _status(session, _amp_info(session))


@router.post("/disconnect", response_model=ConnectionStatus)
def disconnect(session: ServerSession = Depends(get_session)) -> ConnectionStatus:
    session.disconnect()
    return _status(session, _amp_info(session))


@router.post("/test", response_model=ConnectionStatus)
def test_connection(session: ServerSession = Depends(get_session)) -> ConnectionStatus:
    gateway = _require_gateway(session)
    if gateway.ping():
        session.last_tested = datetime.now(UTC).isoformat(timespec="seconds")
    else:
        session.conn_status = STATUS_ERROR
        session.conn_error = "Ping failed."
    return _status(session, _amp_info(session))


@router.get("/databases", response_model=DatabasesResponse)
def list_databases(session: ServerSession = Depends(get_session)) -> DatabasesResponse:
    gateway = _require_gateway(session)
    try:
        dbs = gateway.list_databases()
    except Exception as exc:  # noqa: BLE001
        log.warning("list_databases failed: %s", exc)
        dbs = []
    if not dbs:
        dbs = [gateway.config.db]
    session.db_list = dbs
    return DatabasesResponse(databases=dbs)


@router.get("/collections", response_model=CollectionsResponse)
def list_collections(session: ServerSession = Depends(get_session)) -> CollectionsResponse:
    gateway = _require_gateway(session)
    try:
        cols = gateway.list_collections()
    except Exception as exc:  # noqa: BLE001
        log.warning("list_collections failed: %s", exc)
        cols = []
    session.collections = cols
    return CollectionsResponse(
        collections=[
            CollectionItem(name=c.name, doc_count=c.doc_count, kind=c.kind, system=c.system)
            for c in cols
        ]
    )


@router.get("/clusters", response_model=ClustersResponse)
def list_clusters(
    domains_collection: str,
    session: ServerSession = Depends(get_session),
) -> ClustersResponse:
    gateway = _require_gateway(session)
    ids = gateway.list_cluster_ids(domains_collection)
    session.cluster_ids = ids
    return ClustersResponse(clusters=ids)
