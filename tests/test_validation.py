import pandas as pd

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_CLASS,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_FIRST_NAME,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_LAST_NAME,
    FIELD_STUDENT_ID,
)
from src.validation import validate_students


def make_df(rows):
    return pd.DataFrame(rows)


def base_row(**overrides):
    row = {
        FIELD_STUDENT_ID: 1,
        FIELD_LAST_NAME: "דוגמה",
        FIELD_FIRST_NAME: "בדיקה",
        FIELD_CURRENT_SCHOOL: "בית ספר",
        FIELD_CURRENT_CLASS: 1,
        FIELD_ETHIOPIAN_ORIGIN: False,
        FIELD_ACADEMIC_LEVEL: "בינונית",
        FIELD_DIFFERENTIAL: False,
        FIELD_INCLUSION: False,
        FIELD_HAMAR: False,
    }
    row.update(overrides)
    return row


def test_no_issues_on_clean_data():
    df = make_df([base_row(**{FIELD_STUDENT_ID: 1}), base_row(**{FIELD_STUDENT_ID: 2, FIELD_LAST_NAME: "אחרת"})])
    report = validate_students(df)
    assert not report.has_errors()


def test_duplicate_id_detected():
    df = make_df([base_row(FIELD_STUDENT_ID=1), base_row(FIELD_STUDENT_ID=1)])
    report = validate_students(df)
    assert report.has_errors()
    assert any(i.category == "כפילויות" for i in report.errors)


def test_duplicate_name_is_warning_not_error():
    df = make_df(
        [
            base_row(**{FIELD_STUDENT_ID: 1}),
            base_row(**{FIELD_STUDENT_ID: 2}),
        ]
    )
    report = validate_students(df)
    assert not report.has_errors()
    assert any(i.category == "כפילויות" and i.severity == "warning" for i in report.warnings)


def test_missing_name_is_error():
    df = make_df([base_row(**{FIELD_STUDENT_ID: 1, FIELD_FIRST_NAME: ""})])
    report = validate_students(df)
    assert report.has_errors()


def test_empty_dataframe_reports_error():
    df = pd.DataFrame(columns=[FIELD_STUDENT_ID, FIELD_LAST_NAME, FIELD_FIRST_NAME])
    report = validate_students(df)
    assert report.has_errors()


def test_unknown_academic_level_is_warning():
    df = make_df([base_row(**{FIELD_STUDENT_ID: 1, FIELD_ACADEMIC_LEVEL: "משהו אחר"})])
    report = validate_students(df)
    assert not report.has_errors()
    assert any(i.category == "ערכים לא תקינים" for i in report.warnings)
