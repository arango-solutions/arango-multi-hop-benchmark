"""JSON exporter for accepted QA rows + run metadata."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from multihop_eval.models import AcceptedQA, RunResult


def export_to_json(rows: list[AcceptedQA], output_path: str | Path) -> Path:
    """Write a list of accepted rows to a UTF-8 JSON file."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [r.to_row_dict() for r in rows]
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_default_serialiser)
    return out_path


def export_run_to_json(result: RunResult, output_path: str | Path) -> Path:
    """Serialise a full `RunResult` (accepted + rejected + metadata)."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "duration_s": (result.finished_at - result.started_at).total_seconds(),
        "cluster_targets": result.cluster_targets,
        "cluster_achieved": result.cluster_achieved,
        "accepted": [r.to_row_dict() for r in result.accepted],
        "rejected": [
            {
                "cluster_id": r.cluster_id,
                "persona": r.persona,
                "seed_doc_id": r.seed_doc_id,
                "reason": r.reason.value,
                "detail": r.detail,
            }
            for r in result.rejected
        ],
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_default_serialiser)
    return out_path


def _default_serialiser(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
