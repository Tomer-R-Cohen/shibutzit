from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.session_store import store
from src.constraints import Constraint

SESSION_ID = "optimize-router-test-session"


@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def session_headers(client):
    store.reset(SESSION_ID)
    headers = {"X-Session-Id": SESSION_ID}
    client.post("/api/session", headers=headers)
    client.post("/api/workbook/load", headers=headers)
    guess = client.get("/api/mapping/guess", headers=headers).json()
    client.post(
        "/api/mapping/apply",
        headers=headers,
        json={"mapping": guess["mapping"], "manual_fields": guess["manual_fields"]},
    )
    yield headers
    store.reset(SESSION_ID)


def test_infeasible_solve_gets_narrated_and_recorded_in_chat(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[0]["student_id"], students[1]["student_id"]

    sess = store.get_or_create(SESSION_ID)
    together = Constraint(type="together", hard=True, args={"student_a": a, "student_b": b}, label_hebrew="ביחד לבדיקה")
    separate = Constraint(type="separate", hard=True, args={"student_a": a, "student_b": b}, label_hebrew="בנפרד לבדיקה")
    sess.constraints.append(together)
    sess.constraints.append(separate)

    with patch("backend.routers.optimize.narrate_infeasibility", return_value="הסבר מדומה.") as mocked:
        resp = client.post("/api/optimize", headers=session_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_feasible"] is False
    assert together.id in body["conflicting_constraint_ids"]
    assert separate.id in body["conflicting_constraint_ids"]
    assert body["infeasibility_explanation"] == "הסבר מדומה."
    mocked.assert_called_once()

    history = client.get("/api/chat/history", headers=session_headers).json()["messages"]
    assert history[-1]["content"] == "הסבר מדומה."


def test_feasible_solve_does_not_call_narration(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)

    with patch("backend.routers.optimize.narrate_infeasibility") as mocked:
        resp = client.post("/api/optimize", headers=session_headers)
        mocked.assert_not_called()

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_feasible"] is True
    assert body["infeasibility_explanation"] is None
    assert body["result_state"]["is_stale"] is False
    assert body["result_state"]["solve_revision"] == body["result_state"]["input_revision"]


def test_result_freshness_is_server_owned_and_manual_moves_are_labeled(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)

    with patch("backend.routers.optimize.narrate_result", return_value=None):
        solved = client.post("/api/optimize", headers=session_headers).json()
    assert solved["is_feasible"] is True
    assert client.get("/api/result-state", headers=session_headers).json()["is_stale"] is False

    sess = store.get_or_create(SESSION_ID)
    student_id, current_zero_based = next(iter(sess.adjustment_state.assignment.items()))
    current = current_zero_based + 1
    new_class = 1 if current != 1 else 2
    moved = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": student_id, "new_class": new_class},
    ).json()
    assert moved["result_state"]["result_mode"] == "manual"
    assert moved["result_state"]["is_stale"] is False

    constraint = client.get("/api/constraints", headers=session_headers).json()["constraints"][0]
    patched = client.patch(
        f"/api/constraints/{constraint['id']}",
        headers=session_headers,
        json={"active": not constraint["active"]},
    ).json()
    assert patched["result_state"]["is_stale"] is True
    assert client.get("/api/result-state", headers=session_headers).json()["is_stale"] is True
