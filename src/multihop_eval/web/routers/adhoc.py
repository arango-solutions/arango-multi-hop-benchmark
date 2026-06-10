"""Ad-hoc router — validate a single user-supplied QA pair.

Mirrors the former Streamlit "Ad-hoc" tab: the user pastes a question /
answer / reasoning chain / proof + the source documents, and we run the exact
multi-hop + proof verification the generation pipeline uses (plus an optional
rubric score). No Arango access is needed, but a saved configuration is — it
carries the LLM credentials and the rubric definition.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from multihop_eval.clients.llm_client import LLMClient
from multihop_eval.generation.adhoc import AdhocEvaluator
from multihop_eval.web.routers.deps import get_session
from multihop_eval.web.schemas import AdhocRequest, AdhocResponse
from multihop_eval.web.sessions import ServerSession

router = APIRouter(prefix="/adhoc", tags=["adhoc"])


@router.post("/evaluate", response_model=AdhocResponse)
def evaluate(
    req: AdhocRequest,
    session: ServerSession = Depends(get_session),
) -> AdhocResponse:
    cfg = session.app_config
    if cfg is None:
        raise HTTPException(
            status_code=409,
            detail="Save a configuration on the Configure tab before running ad-hoc evaluation.",
        )

    rubric_fields = cfg.eval.rubric_fields if req.score_with_rubric else None
    if req.score_with_rubric and not rubric_fields:
        raise HTTPException(
            status_code=422,
            detail="score_with_rubric=true but the saved configuration has no rubric fields.",
        )

    evaluator = AdhocEvaluator(
        llm=LLMClient(cfg.llm),
        rubric_fields=rubric_fields,
        max_verify_rounds=cfg.eval.max_verify_rounds,
    )
    try:
        result = evaluator.evaluate(
            question=req.question,
            answer=req.answer,
            reasoning_chain=req.reasoning_chain,
            proof=req.proof,
            sources=req.sources,
            score_with_rubric=req.score_with_rubric,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return AdhocResponse(**result.to_dict())
