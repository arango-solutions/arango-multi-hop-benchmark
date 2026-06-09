"""Config router — read / save / load-from-env the session ``AppConfig``.

Mirrors the assembly logic from the former Streamlit ``config_form``: the
Arango credentials come from the live gateway on the session, while the
collection-role overrides, LLM settings, eval knobs, personas, and rubric
come from the request body.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.generation.personas import DEFAULT_PERSONAS
from multihop_eval.generation.rubric import DEFAULT_RUBRIC
from multihop_eval.web.routers.deps import get_session
from multihop_eval.web.schemas import ConfigResponse, ConfigSaveRequest
from multihop_eval.web.sessions import ServerSession

router = APIRouter(prefix="/config", tags=["config"])


def _defaults() -> dict[str, Any]:
    """Default values used to prefill the Configure form on first load."""
    arango_defaults = ArangoConfig.model_fields
    collection_roles = (
        "sources_collection",
        "similarity_collection",
        "relations_collection",
        "domains_collection",
        "rags_collection",
        "qa_collection",
    )
    return {
        "collections": {role: arango_defaults[role].default for role in collection_roles},
        "llm": {
            "api_url": "https://api.openai.com/v1/chat/completions",
            "api_key": "",
            "model": "gpt-4.1",
            "temperature": 0.3,
            "max_tokens": 4000,
            "timeout_s": 180,
            "retries": 3,
        },
        "eval": {
            "target_clusters": ["cluster_0"],
            "n_questions": 50,
            "hop_dist": [2, 3],
            "hop_dist_weights": [0.7, 0.3],
            "max_verify_rounds": 3,
            "save_to_arango": True,
            "score_with_rubric": True,
        },
        "personas": [{"label": p.label, "instruction": p.instruction} for p in DEFAULT_PERSONAS],
        "rubric_fields": [
            {
                "name": f.name,
                "description": f.description,
                "scale_min": f.scale_min,
                "scale_max": f.scale_max,
                "weight": f.weight,
            }
            for f in DEFAULT_RUBRIC
        ],
    }


def _arango_config_from(
    session: ServerSession,
    *,
    collection_overrides: dict[str, str],
) -> ArangoConfig:
    """Clone the live gateway's config, overlaying the chosen collections."""
    if session.gateway is None:
        raise HTTPException(
            status_code=409,
            detail="Connect to ArangoDB before saving configuration.",
        )
    base = session.gateway.config.model_dump()
    if session.gateway.config.password is not None:
        base["password"] = session.gateway.config.password.get_secret_value()
    base.update({k: v for k, v in collection_overrides.items() if v})
    return ArangoConfig(**base)  # type: ignore[arg-type]


@router.get("", response_model=ConfigResponse)
def get_config(session: ServerSession = Depends(get_session)) -> ConfigResponse:
    saved = session.app_config.to_safe_dict() if session.app_config else None
    return ConfigResponse(saved=saved, defaults=_defaults())


@router.post("", response_model=ConfigResponse)
def save_config(
    req: ConfigSaveRequest,
    session: ServerSession = Depends(get_session),
) -> ConfigResponse:
    arango_cfg = _arango_config_from(session, collection_overrides=req.collections)
    try:
        cfg = AppConfig(
            arango=arango_cfg,
            llm=LLMConfig(**req.llm.model_dump()),  # type: ignore[arg-type]
            eval=EvalConfig(
                target_clusters=req.eval.target_clusters,
                n_questions=req.eval.n_questions,
                hop_dist=req.eval.hop_dist,
                hop_dist_weights=req.eval.hop_dist_weights,
                max_verify_rounds=req.eval.max_verify_rounds,
                save_to_arango=req.eval.save_to_arango,
                score_with_rubric=req.eval.score_with_rubric,
                personas=[p.model_dump() for p in req.eval.personas],  # type: ignore[arg-type]
                rubric_fields=[r.model_dump() for r in req.eval.rubric_fields],  # type: ignore[arg-type]
            ),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_format_errors(exc)) from exc

    session.app_config = cfg
    return ConfigResponse(saved=cfg.to_safe_dict(), defaults=_defaults())


@router.get("/from-env", response_model=ConfigResponse)
def load_from_env(session: ServerSession = Depends(get_session)) -> ConfigResponse:
    try:
        cfg = AppConfig.from_env()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_format_errors(exc)) from exc
    session.app_config = cfg
    return ConfigResponse(saved=cfg.to_safe_dict(), defaults=_defaults())


def _format_errors(exc: ValidationError) -> list[str]:
    return [f"{' / '.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
