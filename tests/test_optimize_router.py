from dataclasses import asdict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.prompts import build_project_memory_context
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
    with patch("backend.routers.workbook.DEFAULT_WORKBOOK_PATH", "רשימה כללית לאיזונית.xlsx"):
        client.post(
            "/api/workbook/load",
            headers=headers,
            params={"header_row": 4, "first_data_row": 5, "last_data_row": 221},
        )
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


def test_impossible_capacity_gets_smallest_tested_numeric_relaxation(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    member_ids = [students[0]["student_id"], students[1]["student_id"]]
    sess = store.get_or_create(SESSION_ID)
    impossible = Constraint(
        type="capacity",
        hard=True,
        args={"group": {"kind": "members", "members": member_ids, "label": "קבוצה קטנה"}, "min": 1, "max": 1},
        label_hebrew="תלמידה אחת מהקבוצה בכל כיתה",
        source="chat",
    )
    sess.constraints.append(impossible)
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)

    with patch("backend.routers.optimize.narrate_infeasibility", return_value="הכלל אינו אפשרי לפי מספר התלמידות."):
        response = client.post("/api/optimize", headers=session_headers).json()

    assert response["is_feasible"] is False
    proposal = response["relaxation_proposal"]
    assert proposal["kind"] == "modify"
    assert proposal["target_constraint_id"] == impossible.id
    assert proposal["changes"]["args"]["min"] == 0
    assert proposal["changes"]["args"]["max"] == 1
    assert "hard" not in proposal["changes"], "the smallest change keeps the rule mandatory"
    assert proposal["evidence"]["basis"] == "measured_trial"
    assert proposal["evidence"]["trial_feasible"] is True
    assert "דורש 6" in proposal["summary_hebrew"]
    assert response["conflicting_constraint_ids"] == [impossible.id]
    assert len(response["infeasibility_notes"]) == 1

    confirmed = client.post("/api/chat/confirm", headers=session_headers).json()
    assert confirmed["result"]["hard"] is True
    assert confirmed["result"]["args"]["min"] == 0
    assert confirmed["solver_run_requested"] is True
    assert "מריץ עכשיו" in confirmed["confirmation_message"]


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
    assert body["result_comment"].startswith("סיימתי. שובצו")
    assert "בקובץ לא נמצאו בקשות חברות" in body["result_comment"]
    assert "פנומנלי" not in body["result_comment"]
    assert body["infeasibility_explanation"] is None
    assert body["result_state"]["is_stale"] is False
    assert body["result_state"]["solve_revision"] == body["result_state"]["input_revision"]


def test_alternative_run_advances_and_persists_reproducible_seed(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    original_seed = cfg["random_seed"]

    with patch("backend.routers.optimize.narrate_result", return_value=None):
        response = client.post(
            "/api/optimize",
            headers=session_headers,
            params={"alternative": "true", "include_comment": "false"},
        )

    assert response.status_code == 200
    assert response.json()["result_comment"] is None
    assert client.get("/api/run-config", headers=session_headers).json()["random_seed"] == original_seed + 1


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
    moved_version = next(v for v in sess.assignment_versions if v.id == moved["version"]["id"])
    assert moved_version.reason == f"העברה ידנית מכיתה {current} לכיתה {new_class}"
    assert f"תלמידה {student_id}" not in moved_version.reason
    assert sess.decision_history[-1]["kind"] == "manual_move"
    assert sess.decision_history[-1]["decision"] == "applied"
    assert sess.decision_history[-1]["student"].startswith("STUDENT_")
    assert "STUDENT_" not in sess.decision_history[-1]["summary"]
    memory_context = build_project_memory_context([], sess.decision_history)
    assert "בוצע [STUDENT_" in memory_context
    assert moved_version.reason in memory_context

    locked = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": student_id, "new_class": new_class, "locked": True},
    ).json()
    locked_version = next(v for v in sess.assignment_versions if v.id == locked["version"]["id"])
    assert locked_version.reason == f"קיבוע ידני בכיתה {new_class}"
    assert sess.decision_history[-1]["kind"] == "manual_lock"

    constraint = client.get("/api/constraints", headers=session_headers).json()["constraints"][0]
    patched = client.patch(
        f"/api/constraints/{constraint['id']}",
        headers=session_headers,
        json={"active": not constraint["active"]},
    ).json()
    assert patched["result_state"]["is_stale"] is True
    assert client.get("/api/result-state", headers=session_headers).json()["is_stale"] is True
    stale_approval = client.post(f"/api/versions/{sess.current_version_id}/approve", headers=session_headers)
    assert stale_approval.status_code == 409
    assert "השתנו" in stale_approval.json()["detail"]


def test_invalid_unlock_and_move_keeps_the_existing_lock(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    with patch("backend.routers.optimize.narrate_result", return_value=None):
        solved = client.post("/api/optimize", headers=session_headers).json()
    assert solved["is_feasible"] is True

    sess = store.get_or_create(SESSION_ID)
    student_id, current_zero = next(iter(sess.adjustment_state.assignment.items()))
    locked = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": student_id, "new_class": current_zero + 1, "locked": True},
    )
    assert locked.status_code == 200
    versions_before = len(sess.assignment_versions)

    invalid = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": student_id, "new_class": cfg["num_classes"] + 1, "locked": False},
    )

    assert invalid.status_code == 400
    assert student_id in sess.adjustment_state.locked
    assert sess.locked_assignment[student_id] == current_zero
    assert sess.adjustment_state.assignment[student_id] == current_zero
    assert len(sess.assignment_versions) == versions_before

    other_class = 1 if current_zero + 1 != 1 else 2
    implicit_move = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": student_id, "new_class": other_class},
    )
    assert implicit_move.status_code == 409
    assert student_id in sess.adjustment_state.locked
    assert sess.adjustment_state.assignment[student_id] == current_zero


def test_results_students_recomputes_friendship_attention_after_manual_move(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    with patch("backend.routers.optimize.narrate_result", return_value=None):
        solved = client.post("/api/optimize", headers=session_headers).json()
    assert solved["is_feasible"] is True

    sess = store.get_or_create(SESSION_ID)
    assignment = sess.adjustment_state.assignment
    first_id, first_class = next(iter(assignment.items()))
    second_id, second_class = next((student_id, cls) for student_id, cls in assignment.items() if cls != first_class)
    sess.friendship_result.matched[first_id] = [second_id]
    sess.friendship_result.matched[second_id] = [first_id]

    before_rows = client.get("/api/results/students", headers=session_headers).json()["rows"]
    before = {row["מזהה"]: row for row in before_rows}
    assert before[first_id]["אזהרות"]
    assert before[second_id]["אזהרות"]

    moved = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": first_id, "new_class": second_class + 1},
    )
    assert moved.status_code == 200

    after_rows = client.get("/api/results/students", headers=session_headers).json()["rows"]
    after = {row["מזהה"]: row for row in after_rows}
    assert after[first_id]["כיתה משובצת"] == second_class + 1
    assert after[first_id]["חברות מבוקשות באותה כיתה"] == 1
    assert after[second_id]["חברות מבוקשות באותה כיתה"] == 1
    assert after[first_id]["אזהרות"] == ""
    assert after[second_id]["אזהרות"] == ""


def test_versions_can_be_restored_and_approved(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    solved = client.post("/api/optimize", headers=session_headers).json()
    first_id = solved["version"]["id"]
    sess = store.get_or_create(SESSION_ID)
    first_assignment = dict(sess.adjustment_state.assignment)

    student_id, current_zero = next(iter(first_assignment.items()))
    new_class = 1 if current_zero + 1 != 1 else 2
    moved = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": student_id, "new_class": new_class},
    ).json()
    assert moved["version"]["number"] == solved["version"]["number"] + 1

    history = client.get("/api/versions", headers=session_headers).json()
    assert len(history["versions"]) == 2
    assert history["current_version_id"] == moved["version"]["id"]
    assert history["versions"][0]["metrics"]["academic_level_spread"] is not None
    assert history["versions"][0]["id"] == moved["version"]["id"]
    assert history["versions"][0]["is_current"] is True
    assert history["versions"][0]["moved_students_from_previous"] == 1
    assert history["versions"][1]["id"] == first_id
    assert history["versions"][1]["is_current"] is False
    assert history["versions"][1]["moved_students_from_previous"] is None

    restored = client.post(f"/api/versions/{first_id}/restore", headers=session_headers)
    assert restored.status_code == 200
    restored_session = store.get_or_create(SESSION_ID)
    assert restored_session.adjustment_state.assignment == first_assignment
    assert restored_session.decision_history[-1]["kind"] == "restore_version"
    assert restored_session.decision_history[-1]["decision"] == "applied"
    restored_history = client.get("/api/versions", headers=session_headers).json()
    assert next(v for v in restored_history["versions"] if v["id"] == first_id)["is_current"] is True

    draft_export = client.get("/api/export.xlsx", headers=session_headers)
    assert draft_export.status_code == 409

    approved = client.post(f"/api/versions/{first_id}/approve", headers=session_headers)
    assert approved.status_code == 200
    final_export = client.get("/api/export.xlsx", headers=session_headers)
    assert final_export.status_code == 200
    assert final_export.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    versions = client.get("/api/versions", headers=session_headers).json()["versions"]
    assert next(v for v in versions if v["id"] == first_id)["approved"] is True


def test_version_with_hard_constraint_violations_cannot_be_approved(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    solved = client.post("/api/optimize", headers=session_headers).json()
    assert solved["is_feasible"] is True

    sess = store.get_or_create(SESSION_ID)
    current = next(v for v in sess.assignment_versions if v.id == solved["version"]["id"])
    first_id, first_class = next(iter(current.assignment.items()))
    second_id, second_class = next((student_id, cls) for student_id, cls in current.assignment.items() if cls != first_class)
    separate = Constraint(
        type="separate",
        hard=True,
        args={"student_a": first_id, "student_b": second_id},
        label_hebrew="שתי התלמידות חייבות להיות בכיתות נפרדות",
        source="chat",
    )
    current.constraints.append(asdict(separate))
    current.assignment[first_id] = second_class
    current.metrics["violations_count"] = 0  # Approval must distrust a stale snapshot counter.

    response = client.post(f"/api/versions/{current.id}/approve", headers=session_headers)

    assert response.status_code == 409
    assert current.metrics["violations_count"] >= 1
    assert str(current.metrics["violations_count"]) in response.json()["detail"]
    assert current.approved is False


def test_manual_move_that_breaks_separation_is_visible_and_cannot_be_approved(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    with patch("backend.routers.optimize.narrate_result", return_value=None):
        solved = client.post("/api/optimize", headers=session_headers).json()
    assert solved["is_feasible"] is True

    sess = store.get_or_create(SESSION_ID)
    first_id, first_class = next(iter(sess.adjustment_state.assignment.items()))
    second_id, second_class = next(
        (student_id, cls) for student_id, cls in sess.adjustment_state.assignment.items() if cls != first_class
    )
    separate = Constraint(
        type="separate",
        hard=True,
        args={"student_a": first_id, "student_b": second_id},
        label_hebrew="שתי התלמידות חייבות להיות בכיתות נפרדות",
        source="chat",
    )
    sess.constraints.append(separate)

    moved = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": first_id, "new_class": second_class + 1},
    )

    assert moved.status_code == 200
    body = moved.json()
    assert body["metrics"]["violations_count"] >= 1
    report = client.get("/api/results/violations", headers=session_headers).json()["rows"]
    separation_row = next(row for row in report if row["כלל"] == separate.label_hebrew)
    assert separation_row["בפועל"] == "אותה כיתה"
    approval = client.post(f"/api/versions/{body['version']['id']}/approve", headers=session_headers)
    assert approval.status_code == 409


def test_manual_version_export_does_not_reuse_stale_solver_measurements(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    with patch("backend.routers.optimize.narrate_result", return_value=None):
        solved = client.post("/api/optimize", headers=session_headers).json()
    assert solved["is_feasible"] is True

    sess = store.get_or_create(SESSION_ID)
    student_id, current_zero = next(iter(sess.adjustment_state.assignment.items()))
    locked = client.post(
        "/api/adjustment/move",
        headers=session_headers,
        json={"student_id": student_id, "new_class": current_zero + 1, "locked": True},
    ).json()
    approved = client.post(f"/api/versions/{locked['version']['id']}/approve", headers=session_headers)
    assert approved.status_code == 200

    with patch("backend.routers.export.export_to_excel", return_value=b"workbook") as export:
        response = client.get("/api/export.xlsx", headers=session_headers)

    assert response.status_code == 200
    assert export.call_args.kwargs["solver_status"] == "MANUAL"
    assert export.call_args.kwargs["solver_wall_time"] == 0.0
    assert export.call_args.kwargs["objective_value"] is None


def test_current_assignment_and_workbook_restore_from_persisted_session(client, session_headers):
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    solved = client.post("/api/optimize", headers=session_headers).json()
    assert solved["is_feasible"] is True
    before = dict(store.get_or_create(SESSION_ID).adjustment_state.assignment)

    # Simulate a process restart without deleting the persisted session.
    with store._lock:
        store._sessions.pop(SESSION_ID, None)

    restored = store.get_or_create(SESSION_ID)
    assert restored.mapped_df is not None
    assert restored.adjustment_state is not None
    assert restored.adjustment_state.assignment == before
    assert restored.result_state()["has_result"] is True
    assert restored.friendship_result is not None
    metrics = client.get("/api/results/metrics", headers=session_headers)
    assert metrics.status_code == 200
    assert metrics.json()["total_students"] == len(restored.mapped_df)
