#!/usr/bin/env python3
"""Legacy CLI entrypoint — preserved for backward compatibility.

The original monolithic generator has been split into the
`multihop_eval` package under `src/`. This shim:

  * Reads connection + LLM creds + eval params from the environment
    (`./env` / `.env`) using `AppConfig.from_env()`.
  * Runs `EvaluationOrchestrator.run()` with a console progress callback.
  * Exports results to Excel at `output_excel_path` and (optionally)
    persists every accepted row to ArangoDB.

For the interactive Streamlit experience (Configure / Run / Dashboard /
Ad-hoc tabs), use `python main.py` instead.
"""

from __future__ import annotations

import sys
from collections import Counter

from multihop_eval.arango_gateway import ArangoGateway
from multihop_eval.config import AppConfig
from multihop_eval.exporters import export_to_excel
from multihop_eval.llm_client import LLMClient
from multihop_eval.logging_setup import configure_logging
from multihop_eval.models import RunEvent
from multihop_eval.pipeline import EvaluationOrchestrator
from multihop_eval.rubric_evaluator import RubricEvaluator


def _print_event(ev: RunEvent) -> None:
    p = ev.payload
    if ev.kind == "cluster_start":
        print(
            f"  cluster={p['cluster_id']} docs={p['doc_count']} target={p['target']} "
            f"{'[TOP-UP]' if p.get('topup') else ''}"
        )
    elif ev.kind == "accepted":
        print(
            f"  [ACCEPTED] {p['hop_count']}-hop | {p['accepted']}/{p['target']} | "
            f"{p['question'][:80]}…"
        )
    elif ev.kind == "rejected":
        print(f"  rejected ({p['reason']}): seed={p['seed_doc_id']}")
    elif ev.kind == "pass_done":
        print(f"  PASS {p['pass']} done — total={p['total_accepted']}")
    elif ev.kind == "run_done":
        print(
            f"  RUN COMPLETE — accepted={p['total_accepted']} "
            f"rejected={p['total_rejected']} duration={p['duration_s']:.1f}s"
        )


def main() -> int:
    log = configure_logging("INFO")
    try:
        cfg = AppConfig.from_env()
    except Exception as exc:
        log.error("Failed to load config from env: %s", exc)
        log.error("Populate ./env or .env (see .env.example) and try again.")
        return 2

    gateway = ArangoGateway(cfg.arango)
    llm = LLMClient(cfg.llm)
    rubric_evaluator = (
        RubricEvaluator(llm, cfg.eval.rubric_fields)
        if cfg.eval.score_with_rubric and cfg.eval.rubric_fields
        else None
    )
    orchestrator = EvaluationOrchestrator(
        gateway=gateway,
        llm=llm,
        eval_config=cfg.eval,
        rubric_evaluator=rubric_evaluator,
    )

    log.info(
        "Target clusters: %d | Questions per cluster: %d",
        len(cfg.eval.target_clusters),
        cfg.eval.n_questions,
    )
    result = orchestrator.run(on_event=_print_event)

    hop_counts = Counter(qa.hop_count for qa in result.accepted)
    log.info("=" * 60)
    log.info("DONE  |  Total QA pairs: %d", len(result.accepted))
    for h in sorted(hop_counts):
        log.info("  %d-hop: %d", h, hop_counts[h])
    log.info("=" * 60)

    if result.accepted:
        export_to_excel(result.accepted, cfg.eval.output_excel_path)
    else:
        log.warning("No verified rows to export.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
