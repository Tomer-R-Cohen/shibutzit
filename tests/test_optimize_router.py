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
