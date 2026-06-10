"""Dashboard router: session vs arango summary, rows, and export."""

from __future__ import annotations

import queue
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from multihop_eval.generation.models import (
    AcceptedQA,
    ProofPoint,
    RejectedQA,
    RejectionReason,
    RubricScore,
    RunResult,
)
from multihop_eval.web.run_manager import RunHandle
from multihop_eval.web.sessions import SESSION_HEADER, store


def _accepted() -> AcceptedQA:
    return AcceptedQA(
        cluster_id="cluster_0",
        partition_id="p0",
        hop_count=2,
        persona="analyst",
        reasoning_chain="a -> b",
        question="What links A and B?",
        answer="They share C.",
        proof_list=[ProofPoint(point="A relates C", source_id="sources/1")],
        rubric_scores={"factuality": RubricScore(score=4.0, justification="ok")},
        rubric_weighted_score=4.0,
    )


def _run_result() -> RunResult:
    now = datetime.now(UTC)
    return RunResult(
        accepted=[_accepted()],
        rejected=[
            RejectedQA(
                cluster_id="cluster_0",
                persona="analyst",
                seed_doc_id="sources/9",
                reason=RejectionReason.MULTIHOP_BELOW_FLOOR,
            )
        ],
        cluster_targets={"cluster_0": 2},
        cluster_achieved={"cluster_0": 1},
        started_at=now,
        finished_at=now,
    )


def _session_with_run() -> str:
    session = store.get_or_create(None)
    handle = RunHandle(thread=None, event_queue=queue.Queue())
    handle.status = "done"
    handle.result = _run_result()
    session.run = handle
    return session.token


def test_summary_session_no_run_is_unavailable(client: TestClient) -> None:
    resp = client.get("/dashboard/summary", params={"source": "session"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "source": "session",
        "available": False,
        "summary": None,
        "rows": [],
        "row_count": 0,
    }


def test_summary_session_with_run(client: TestClient) -> None:
    token = _session_with_run()
    resp = client.get(
        "/dashboard/summary",
        params={"source": "session"},
        headers={SESSION_HEADER: token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["row_count"] == 1
    assert body["summary"]["total_accepted"] == 1
    assert body["summary"]["total_rejected"] == 1
    assert body["summary"]["rejection_breakdown"] == {"multihop_below_floor": 1}
    assert body["rows"][0]["question"] == "What links A and B?"


def test_summary_arango_requires_connection(client: TestClient) -> None:
    resp = client.get("/dashboard/summary", params={"source": "arango"})
    assert resp.status_code == 409


def test_summary_arango_reads_persisted_rows(
    client: TestClient, fake_arango_with_qa
) -> None:
    token = fake_arango_with_qa
    resp = client.get(
        "/dashboard/summary",
        params={"source": "arango"},
        headers={SESSION_HEADER: token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "arango"
    assert body["available"] is True
    assert body["row_count"] == 1
    assert body["summary"]["total_accepted"] == 1
    # Persisted rows carry no rejection info.
    assert body["summary"]["total_rejected"] == 0


def test_summary_bad_source_is_400(client: TestClient) -> None:
    assert client.get("/dashboard/summary", params={"source": "nope"}).status_code == 400


def test_export_session_json_and_excel(client: TestClient) -> None:
    token = _session_with_run()
    h = {SESSION_HEADER: token}
    js = client.get("/dashboard/export", params={"source": "session", "fmt": "json"}, headers=h)
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("application/json")
    assert "attachment" in js.headers["content-disposition"]

    xl = client.get("/dashboard/export", params={"source": "session", "fmt": "excel"}, headers=h)
    assert xl.status_code == 200
    assert "spreadsheetml" in xl.headers["content-type"]
    assert xl.content[:2] == b"PK"  # xlsx is a zip


def test_export_session_without_run_is_409(client: TestClient) -> None:
    assert (
        client.get("/dashboard/export", params={"source": "session"}).status_code == 409
    )


def test_export_arango_excel_is_rejected(client: TestClient, fake_arango_with_qa) -> None:
    resp = client.get(
        "/dashboard/export",
        params={"source": "arango", "fmt": "excel"},
        headers={SESSION_HEADER: fake_arango_with_qa},
    )
    assert resp.status_code == 400
