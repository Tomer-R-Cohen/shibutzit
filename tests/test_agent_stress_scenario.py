from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.provider import ChatCompletion
from backend.routers.workbook import _detect_uploaded_table
from backend.llm.read_tools import execute_read_tool
from backend.session_store import PendingProposal, Session, store
from sample_data.generate_agent_stress_scenario import generate
from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    apply_mapping,
    guess_mapping,
)
from src.constraints import Constraint, default_constraints
from src.excel_loader import DEFAULT_WORKBOOK_PATH, load_default_workbook, load_workbook
from src.friendship_graph import resolve_requests
from src.feasibility import analyze_feasibility
from src.optimizer import SolverConfig, optimize
from src.validation import validate_students


def _mapped_scenario(path: Path):
    sheet, header, first_data = _detect_uploaded_table(str(path))
    assert (sheet, header, first_data) == ("תלמידות", 4, 5)
    loaded = load_workbook(
        str(path),
        sheet_name=sheet,
        header_row_1indexed=header,
        first_data_row_1indexed=first_data,
    )
    mapping = guess_mapping(list(loaded.raw_df.columns), loaded.raw_df)
    return apply_mapping(loaded.raw_df, mapping)


def test_agent_stress_scenario_is_the_bundled_default_workbook():
    assert Path(DEFAULT_WORKBOOK_PATH).as_posix() == "sample_data/agent_stress_test_students.xlsx"
    loaded = load_default_workbook()
    assert loaded.active_sheet == "תלמידות"
    assert len(loaded.raw_df) == 84


def test_default_workbook_api_loads_the_agent_stress_scenario():
    session_id = "default-agent-stress-workbook"
    store.reset(session_id)
    try:
        response = TestClient(backend_main.app).post(
            "/api/workbook/load",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        assert response.json()["row_count"] == 84
        assert response.json()["active_sheet"] == "תלמידות"
        assert store.get_or_create(session_id).source_filename == "agent_stress_test_students.xlsx"
    finally:
        store.reset(session_id)


def test_roster_correction_flow_resolves_guided_data_warnings_without_editing_source():
    session_id = "guided-roster-correction"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
    client = TestClient(backend_main.app)
    try:
        assert client.post("/api/workbook/load", headers=headers).status_code == 200
        guess = client.get("/api/mapping/guess", headers=headers).json()
        assert client.post(
            "/api/mapping/apply",
            headers=headers,
            json={"mapping": guess["mapping"], "manual_fields": guess["manual_fields"]},
        ).status_code == 200

        sess = store.get_or_create(session_id)
        source_path = Path(sess.source_path)
        source_bytes = source_path.read_bytes()
        bad_academic_id = int(
            sess.mapped_df.loc[~sess.mapped_df[FIELD_ACADEMIC_LEVEL].isin({"מצטיינת", "בינונית", "חלשה"}), "student_id"].iloc[0]
        )
        missing_school_id = int(
            sess.mapped_df.loc[sess.mapped_df[FIELD_CURRENT_SCHOOL].fillna("").astype(str).str.strip() == "", "student_id"].iloc[0]
        )

        academic_fix = client.patch(
            f"/api/students/{bad_academic_id}",
            headers=headers,
            json={"field": FIELD_ACADEMIC_LEVEL, "value": "בינונית"},
        )
        school_fix = client.patch(
            f"/api/students/{missing_school_id}",
            headers=headers,
            json={"field": FIELD_CURRENT_SCHOOL, "value": "בית ספר מקור ד"},
        )
        assert academic_fix.status_code == 200
        assert school_fix.status_code == 200

        messages = [str(issue["הודעה"]) for issue in client.get("/api/validation", headers=headers).json()["issues"]]
        assert not any("הישגים לימודיים' לא מוכר" in message for message in messages)
        assert not any("ללא בית ספר נוכחי" in message for message in messages)
        assert sess.student_data_edits[bad_academic_id][FIELD_ACADEMIC_LEVEL] == "בינונית"
        assert sess.student_data_edits[missing_school_id][FIELD_CURRENT_SCHOOL] == "בית ספר מקור ד"
        assert source_path.read_bytes() == source_bytes
    finally:
        store.reset(session_id)


def test_stress_scenario_has_intentional_conflicts_and_only_nonblocking_data_warnings(tmp_path):
    path = generate(tmp_path / "stress.xlsx")
    students = _mapped_scenario(path)

    assert len(students) == 84
    assert int(students[FIELD_DIFFERENTIAL].sum()) == 7
    assert int(students[FIELD_INCLUSION].sum()) == 11
    assert int(students[FIELD_ETHIOPIAN_ORIGIN].sum()) == 17
    assert int(students[FIELD_HAMAR].sum()) == 13

    validation = validate_students(students)
    assert not validation.has_errors()
    assert {issue.category for issue in validation.warnings} == {"ערכים לא תקינים", "שדות חסרים"}

    defaults = default_constraints(students, 6)
    infeasible = optimize(students, SolverConfig(num_classes=6, time_limit_seconds=3), defaults)
    assert not infeasible.is_feasible

    sess = Session(id="stress-feasibility-evidence")
    sess.mapped_df = students
    sess.constraints = defaults
    evidence = execute_read_tool("analyze_rule_feasibility", {}, sess)
    impossible = evidence["independently_impossible_rules"]
    assert evidence["independently_impossible_count"] == 4
    assert {item["students_in_group"] for item in impossible} == {7, 11, 13, 17}
    suggested_ranges = {
        item["students_in_group"]: (
            item["minimal_independent_relaxation"]["min"],
            item["minimal_independent_relaxation"]["max"],
        )
        for item in impossible
    }
    assert suggested_ranges == {7: (None, 2), 11: (1, 2), 13: (1, 3), 17: (2, 4)}


def test_known_minimal_relaxation_direction_is_solver_feasible(tmp_path):
    students = _mapped_scenario(generate(tmp_path / "stress.xlsx"))
    constraints = default_constraints(students, 6)

    for constraint in constraints:
        if constraint.type != "capacity":
            continue
        group = constraint.args.get("group", {})
        if group.get("kind") == "all":
            constraint.args.update({"min": 14, "max": 14, "size_diff": 0})
        elif group.get("field") == FIELD_DIFFERENTIAL:
            constraint.args.update({"min": None, "max": 2})
        elif group.get("field") == FIELD_INCLUSION:
            constraint.args.update({"min": 1, "max": 2})
        elif group.get("field") == FIELD_ETHIOPIAN_ORIGIN:
            constraint.args.update({"min": 2, "max": 3})
        elif group.get("field") == FIELD_HAMAR:
            constraint.args.update({"min": 2, "max": 3})

    constraints.append(
        Constraint(
            type="capacity",
            hard=True,
            args={
                "group": {"kind": "field_value", "field": FIELD_CURRENT_SCHOOL, "value": "בית ספר מקור א"},
                "min": None,
                "max": 5,
            },
            label_hebrew="עד 5 תלמידות מבית ספר מקור א בכיתה",
            source="chat",
        )
    )
    matched = resolve_requests(students).matched
    result = optimize(
        students,
        SolverConfig(num_classes=6, time_limit_seconds=12),
        constraints,
        friendship_matched=matched,
    )

    assert result.is_feasible
    sizes = [sum(assigned == class_index for assigned in result.assignment.values()) for class_index in range(6)]
    assert sizes == [14] * 6


def test_conversational_approval_applies_the_whole_feasibility_package_atomically(tmp_path):
    session_id = "stress-batch-package"
    store.reset(session_id)
    sess = store.get_or_create(session_id)
    sess.mapped_df = _mapped_scenario(generate(tmp_path / "stress.xlsx"))
    sess.constraints = default_constraints(sess.mapped_df, 6)
    headers = {"X-Session-Id": session_id}
    client = TestClient(backend_main.app)
    model_calls = 0

    def fake(system_prompt, messages, tools):
        nonlocal model_calls
        model_calls += 1
        answer = "מצאתי ארבעה שינויים מזעריים. האם לאשר את השינוי הראשון או את כל החבילה?"
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    try:
        with patch("backend.llm.agent.chat_completion", side_effect=fake):
            analyzed = client.post(
                "/api/chat/message",
                headers=headers,
                json={
                    "message": "תנתחי אילו כללים בלתי אפשריים בפני עצמם ותציעי את קבוצת השינויים הקטנה ביותר. אל תשני שום כלל בלי אישור שלי."
                },
            )
            applied = client.post(
                "/api/chat/message",
                headers=headers,
                json={"message": "את כל החבילה"},
            )

        assert analyzed.status_code == 200
        assert model_calls == 1, "package approval must not return to the model"
        assert applied.status_code == 200
        body = applied.json()
        assert body["pending_proposal"] is None
        assert body["solver_run_requested"] is True
        assert "4 כללי חובה" in body["reply"]

        ranges = {}
        for constraint in sess.constraints:
            if constraint.type != "capacity":
                continue
            field = constraint.args.get("group", {}).get("field")
            if field in {FIELD_DIFFERENTIAL, FIELD_ETHIOPIAN_ORIGIN, FIELD_INCLUSION, FIELD_HAMAR}:
                ranges[field] = (constraint.args.get("min"), constraint.args.get("max"))
        assert ranges == {
            FIELD_DIFFERENTIAL: (None, 2),
            FIELD_ETHIOPIAN_ORIGIN: (2, 4),
            FIELD_INCLUSION: (1, 2),
            FIELD_HAMAR: (1, 3),
        }
        decision = sess.decision_history[-1]
        assert decision["kind"] == "modify"
        assert len(decision["result"]["constraints"]) == 4
        assert sess.input_revision == 1
    finally:
        store.reset(session_id)


def test_optimizer_presents_every_known_arithmetic_conflict_in_one_proposal(tmp_path):
    session_id = "stress-optimize-package"
    store.reset(session_id)
    sess = store.get_or_create(session_id)
    sess.mapped_df = _mapped_scenario(generate(tmp_path / "stress.xlsx"))
    sess.constraints = default_constraints(sess.mapped_df, 6)
    headers = {"X-Session-Id": session_id}
    client = TestClient(backend_main.app)
    try:
        with patch("backend.routers.optimize.narrate_infeasibility", return_value="מצאתי כמה כללי חובה בלתי אפשריים."):
            response = client.post("/api/optimize", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["is_feasible"] is False
        proposal = body["relaxation_proposal"]
        assert proposal["evidence"]["basis"] == "arithmetic_feasibility_package"
        assert proposal["evidence"]["item_count"] == 4
        assert len(proposal["changes"]["batch"]) == 4
        assert sess.pending_proposal is not None

        confirmed = client.post("/api/chat/confirm", headers=headers).json()
        assert confirmed["solver_run_requested"] is True
        assert len(confirmed["result"]["constraints"]) == 4
    finally:
        store.reset(session_id)


def test_confirming_one_fix_does_not_rerun_while_other_known_conflicts_remain(tmp_path):
    session_id = "stress-incomplete-fix"
    store.reset(session_id)
    sess = store.get_or_create(session_id)
    sess.mapped_df = _mapped_scenario(generate(tmp_path / "stress.xlsx"))
    sess.constraints = default_constraints(sess.mapped_df, 6)
    differential = next(
        constraint
        for constraint in sess.constraints
        if constraint.args.get("group", {}).get("field") == FIELD_DIFFERENTIAL
    )
    next_args = {**differential.args, "max": 2}
    sess.pending_proposal = PendingProposal(
        kind="modify",
        summary_hebrew="להגדיל את המקסימום הדיפרנציאלי ל-2.",
        target_constraint_id=differential.id,
        changes={"args": next_args},
        evidence={"basis": "measured_trial", "changes_hard_rule": True},
    )
    try:
        response = TestClient(backend_main.app).post(
            "/api/chat/confirm",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["solver_run_requested"] is False
        assert "לא אריץ עדיין" in body["confirmation_message"]
        assert len(analyze_feasibility(sess.mapped_df, sess.constraints, 6).infeasible) == 3
    finally:
        store.reset(session_id)
