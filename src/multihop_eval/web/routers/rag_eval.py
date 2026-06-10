"""RAG-eval router — score one or more RAG systems against the goldens.

Ports the Streamlit "RAG Eval" tab: load the golden QA set from Arango, load
the systems' responses (uploaded JSONL or an Arango collection), then compute
retrieval + generation metrics per ``system_name`` via
:class:`RagEvalOrchestrator`. The resulting runs are cached on the session so
the export endpoint can serialise them to Excel/JSON.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import ValidationError

from multihop_eval.config import RagEvalConfig
from multihop_eval.exporters import export_rag_eval_to_excel
from multihop_eval.rag_eval import (
    RagEvalOrchestrator,
    load_responses_from_arango,
    load_responses_from_jsonl,
)
from multihop_eval.web.routers.deps import get_session
from multihop_eval.web.schemas import RagEvalRequest, RagEvalResponse
from multihop_eval.web.sessions import ServerSession

router = APIRouter(prefix="/rag_eval", tags=["rag_eval"])

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/evaluate", response_model=RagEvalResponse)
def evaluate(
    req: RagEvalRequest,
    session: ServerSession = Depends(get_session),
) -> RagEvalResponse:
    if session.gateway is None:
        raise HTTPException(status_code=409, detail="Connect to ArangoDB first.")

    try:
        cfg = RagEvalConfig(
            relevance_mode=req.relevance_mode,
            k_values=req.k_values,
            response_source=req.response_source,
            response_arango_collection=req.response_arango_collection,
            system_filter=req.system_filter,
            length_z_threshold=req.length_z_threshold,
            groundedness_fuzz_threshold=req.groundedness_fuzz_threshold,
            empty_retrieval_min_score=req.empty_retrieval_min_score,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_format_errors(exc)) from exc

    load_errors: list[str] = []
    if cfg.response_source == "jsonl":
        if not req.jsonl_text:
            raise HTTPException(
                status_code=422,
                detail="response_source='jsonl' requires an uploaded JSONL file.",
            )
        result = load_responses_from_jsonl(req.jsonl_text.splitlines())
        responses = result.responses
        load_errors = [f"line {e.line_number}: {e.message}" for e in result.errors]
    else:  # arango
        result = load_responses_from_arango(session.gateway, cfg.response_arango_collection)
        responses = result.responses
        load_errors = [f"{e.arango_key}: {e.message}" for e in result.errors]

    if cfg.system_filter:
        allowed = set(cfg.system_filter)
        responses = [r for r in responses if r.system_name in allowed]

    goldens = session.gateway.fetch_goldens_with_keys(limit=req.golden_limit)

    runs = RagEvalOrchestrator(cfg).evaluate(goldens, responses)
    session.rag_eval_runs = runs

    return RagEvalResponse(
        runs=[json.loads(run.model_dump_json()) for run in runs],
        n_goldens=len(goldens),
        n_responses=len(responses),
        n_systems=len(runs),
        load_errors=load_errors,
    )


@router.get("/export")
def export(
    fmt: str = Query(default="json"),
    session: ServerSession = Depends(get_session),
) -> Response:
    runs = session.rag_eval_runs
    if not runs:
        raise HTTPException(status_code=409, detail="Run an evaluation before exporting.")
    if fmt == "json":
        payload = {run.system_name: json.loads(run.model_dump_json()) for run in runs}
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        return _download(data, "application/json", "rag_eval.json")
    if fmt == "excel":
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "rag_eval.xlsx"
            export_rag_eval_to_excel(runs, out)
            data = out.read_bytes()
        return _download(data, _XLSX_MEDIA, "rag_eval.xlsx")
    raise HTTPException(status_code=400, detail="fmt must be 'json' or 'excel'.")


def _download(data: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _format_errors(exc: ValidationError) -> list[str]:
    return [f"{' / '.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
