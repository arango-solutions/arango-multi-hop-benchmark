"""Dashboard router — KPI summary, accepted rows, and Excel/JSON export.

The dashboard reads from one of two sources:

* ``session`` — the in-memory :class:`RunResult` produced by the most recent
  run on this session (rich: includes rejection breakdown + run duration).
* ``arango`` — rows previously persisted to the QA collection (read live via
  the session's gateway; no rejection records exist for this source).

Export is driven off the same data: JSON works for either source, while the
styled Excel workbook is built from the session run's ``AcceptedQA`` objects.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from multihop_eval.exporters import export_to_excel
from multihop_eval.generation.summary import build_summary, summary_from_qa_rows
from multihop_eval.web.routers.deps import get_session
from multihop_eval.web.schemas import DashboardResponse
from multihop_eval.web.sessions import ServerSession

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _session_rows(session: ServerSession) -> list[dict[str, Any]]:
    """Row dicts for the current session run, or ``[]`` when there is none."""
    if session.run is None or session.run.result is None:
        return []
    return [qa.to_row_dict() for qa in session.run.result.accepted]


@router.get("/summary", response_model=DashboardResponse)
def summary(
    source: str = Query(default="session"),
    session: ServerSession = Depends(get_session),
) -> DashboardResponse:
    if source == "session":
        run = session.run
        if run is None or run.result is None:
            return DashboardResponse(source="session", available=False)
        stats = build_summary(run.result)
        rows = _session_rows(session)
        return DashboardResponse(
            source="session",
            available=True,
            summary=stats.to_dict(),
            rows=rows,
            row_count=len(rows),
        )

    if source == "arango":
        if session.gateway is None:
            raise HTTPException(status_code=409, detail="Connect to ArangoDB first.")
        rows = session.gateway.fetch_qa_rows()
        stats = summary_from_qa_rows(rows)
        return DashboardResponse(
            source="arango",
            available=bool(rows),
            summary=stats.to_dict(),
            rows=rows,
            row_count=len(rows),
        )

    raise HTTPException(status_code=400, detail="source must be 'session' or 'arango'.")


@router.get("/export")
def export(
    source: str = Query(default="session"),
    fmt: str = Query(default="json"),
    session: ServerSession = Depends(get_session),
) -> Response:
    if fmt not in {"json", "excel"}:
        raise HTTPException(status_code=400, detail="fmt must be 'json' or 'excel'.")

    if source == "session":
        run = session.run
        if run is None or run.result is None:
            raise HTTPException(status_code=409, detail="No session run to export.")
        accepted = run.result.accepted
        if fmt == "json":
            payload = json.dumps(
                [qa.to_row_dict() for qa in accepted], indent=2, default=str
            ).encode("utf-8")
            return _download(payload, "application/json", "multihop_eval.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "multihop_eval.xlsx"
            export_to_excel(accepted, out)
            data = out.read_bytes()
        return _download(data, _XLSX_MEDIA, "multihop_eval.xlsx")

    if source == "arango":
        if session.gateway is None:
            raise HTTPException(status_code=409, detail="Connect to ArangoDB first.")
        if fmt == "excel":
            raise HTTPException(
                status_code=400,
                detail="Excel export is only available for the current session run.",
            )
        rows = session.gateway.fetch_qa_rows()
        payload = json.dumps(rows, indent=2, default=str).encode("utf-8")
        return _download(payload, "application/json", "multihop_eval_persisted.json")

    raise HTTPException(status_code=400, detail="source must be 'session' or 'arango'.")


def _download(data: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
