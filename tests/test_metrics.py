import pandas as pd

from src.column_mapping import FIELD_ACADEMIC_LEVEL, FIELD_FIRST_NAME, FIELD_LAST_NAME, FIELD_STUDENT_ID
from src.constraints import Constraint
from src.metrics import academic_level_spread, student_assignment_table, violations_report


def test_academic_level_spread_is_zero_for_even_category_distribution():
    df = pd.DataFrame(
        {
            FIELD_STUDENT_ID: list(range(8)),
            FIELD_ACADEMIC_LEVEL: ["גבוה"] * 4 + ["בינוני"] * 4,
        }
    )
    assignment = {0: 0, 1: 0, 2: 1, 3: 1, 4: 0, 5: 0, 6: 1, 7: 1}

    assert academic_level_spread(df, assignment, 2) == 0


def test_academic_level_spread_measures_skew_and_reports_missing_data():
    df = pd.DataFrame(
        {
            FIELD_STUDENT_ID: list(range(8)),
            FIELD_ACADEMIC_LEVEL: ["גבוה"] * 4 + ["בינוני"] * 4,
        }
    )
    skewed = {student_id: (0 if student_id < 4 else 1) for student_id in range(8)}

    assert academic_level_spread(df, skewed, 2) == 8
    assert academic_level_spread(df.assign(**{FIELD_ACADEMIC_LEVEL: ""}), skewed, 2) is None


def test_student_assignment_attention_is_grounded_in_unsatisfied_friend_requests():
    df = pd.DataFrame(
        {
            FIELD_STUDENT_ID: [1, 2, 3],
            FIELD_FIRST_NAME: ["א", "ב", "ג"],
            FIELD_LAST_NAME: ["א", "ב", "ג"],
        }
    )
    assignment = {1: 0, 2: 1, 3: 1}
    friendships = {1: [2, 3], 2: [1], 3: []}

    rows = student_assignment_table(df, assignment, friendships).set_index("מזהה")

    assert rows.loc[1, "אזהרות"] == "אף אחת מ-2 בקשות החברות לא קיבלה מענה"
    assert rows.loc[2, "אזהרות"] == "אף אחת מ-1 בקשות החברות לא קיבלה מענה"
    assert rows.loc[3, "אזהרות"] == ""


def test_student_assignment_attention_marks_partial_response_without_flagging_success():
    df = pd.DataFrame(
        {
            FIELD_STUDENT_ID: [1, 2, 3],
            FIELD_FIRST_NAME: ["א", "ב", "ג"],
            FIELD_LAST_NAME: ["א", "ב", "ג"],
        }
    )
    friendships = {1: [2, 3], 2: [], 3: []}

    partial = student_assignment_table(df, {1: 0, 2: 0, 3: 1}, friendships).set_index("מזהה")
    satisfied = student_assignment_table(df, {1: 0, 2: 0, 3: 0}, friendships).set_index("מזהה")

    assert partial.loc[1, "אזהרות"] == "רק בקשת חברות אחת מתוך 2 קיבלה מענה"
    assert satisfied.loc[1, "אזהרות"] == ""


def test_violation_report_covers_relationship_and_lock_rules_not_only_capacity():
    df = pd.DataFrame({FIELD_STUDENT_ID: [1, 2, 3]})
    assignment = {1: 0, 2: 0, 3: 1}
    constraints = [
        Constraint(type="separate", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="נפרדות"),
        Constraint(type="together", hard=True, args={"student_a": 1, "student_b": 3}, label_hebrew="ביחד"),
        Constraint(type="at_least_one_of", hard=True, args={"student": 3, "candidates": [1, 2]}, label_hebrew="לפחות חברה"),
        Constraint(type="locked", hard=True, args={"student": 3, "class_index": 0}, label_hebrew="קיבוע"),
        Constraint(type="together", hard=False, args={"student_a": 1, "student_b": 3}, label_hebrew="העדפה בלבד"),
    ]

    report = violations_report(df, assignment, constraints, 2)

    assert set(report["כלל"]) == {"נפרדות", "ביחד", "לפחות חברה", "קיבוע"}
    assert "העדפה בלבד" not in set(report["כלל"])
