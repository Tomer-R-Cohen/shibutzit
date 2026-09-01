"""Tests for src/column_mapping.py, in particular the student-id guess
heuristic used when the real workbook's index column has a blank header
(pandas auto-names it "Unnamed: N")."""

import pandas as pd

from src.column_mapping import (
    FIELD_DIFFERENTIAL,
    FIELD_FRIEND_REQUESTS,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_STUDENT_ID,
    FIELD_LAST_NAME,
    FIELD_FIRST_NAME,
    guess_mapping,
    apply_mapping,
)


def test_exact_name_match_still_wins():
    columns = ["מספר סידורי", "שם משפחה", "שם פרטי"]
    raw_df = pd.DataFrame(
        {
            "מספר סידורי": [1, 2, 3],
            "שם משפחה": ["א", "ב", "ג"],
            "שם פרטי": ["ד", "ה", "ו"],
        }
    )
    cm = guess_mapping(columns, raw_df)
    assert cm.get(FIELD_STUDENT_ID) == "מספר סידורי"


def test_unnamed_unique_integer_column_is_auto_mapped_to_student_id():
    # Simulates the real workbook: first data column has no header text in
    # row 4, so pandas names it "Unnamed: 1".
    columns = ["Unnamed: 1", "שם משפחה", "שם פרטי"]
    raw_df = pd.DataFrame(
        {
            "Unnamed: 1": list(range(1, 218)),
            "שם משפחה": ["שם"] * 217,
            "שם פרטי": ["פרטי"] * 217,
        }
    )
    cm = guess_mapping(columns, raw_df)
    assert cm.get(FIELD_STUDENT_ID) == "Unnamed: 1"


def test_falls_back_to_first_unique_integer_column_when_no_unnamed_match():
    columns = ["idx", "שם משפחה"]
    raw_df = pd.DataFrame({"idx": [10, 20, 30], "שם משפחה": ["א", "ב", "ג"]})
    cm = guess_mapping(columns, raw_df)
    assert cm.get(FIELD_STUDENT_ID) == "idx"


def test_no_raw_df_falls_back_to_manual_entry():
    columns = ["שם משפחה", "שם פרטי"]
    cm = guess_mapping(columns)
    assert cm.get(FIELD_STUDENT_ID) is None


def test_no_plausible_id_column_falls_back_to_manual_entry():
    # Synthetic sample dataset style: no unique-integer column present at all
    # (e.g. all text columns), so mapping should stay unmapped/manual.
    columns = ["שם משפחה", "שם פרטי"]
    raw_df = pd.DataFrame({"שם משפחה": ["א", "ב"], "שם פרטי": ["ג", "ד"]})
    cm = guess_mapping(columns, raw_df)
    assert cm.get(FIELD_STUDENT_ID) is None


def test_duplicate_integers_are_not_treated_as_id_column():
    columns = ["Unnamed: 1", "class_num"]
    raw_df = pd.DataFrame({"Unnamed: 1": [1, 1, 2], "class_num": [1, 2, 3]})
    cm = guess_mapping(columns, raw_df)
    # "Unnamed: 1" has duplicates so it's rejected; falls back to class_num.
    assert cm.get(FIELD_STUDENT_ID) == "class_num"


def test_optional_fields_are_auto_mapped_when_present_in_workbook():
    columns = [
        "מספר סידורי",
        "תלמידה דיפרנציאלית",
        "תלמידה בשילוב",
        'סטטוס ח"מ',
        "בקשות חברות (שמות, מופרד בפסיקים)",
    ]
    raw_df = pd.DataFrame({column: [1] for column in columns})
    cm = guess_mapping(columns, raw_df)
    assert cm.get(FIELD_DIFFERENTIAL) == "תלמידה דיפרנציאלית"
    assert cm.get(FIELD_INCLUSION) == "תלמידה בשילוב"
    assert cm.get(FIELD_HAMAR) == 'סטטוס ח"מ'
    assert cm.get(FIELD_FRIEND_REQUESTS) == "בקשות חברות (שמות, מופרד בפסיקים)"
    assert not ({FIELD_DIFFERENTIAL, FIELD_INCLUSION, FIELD_HAMAR, FIELD_FRIEND_REQUESTS} & cm.manual_fields)


def test_blank_excel_cells_in_mapped_optional_flags_are_false():
    raw_df = pd.DataFrame(
        {
            "מספר סידורי": [1, 2],
            "שם משפחה": ["א", "ב"],
            "שם פרטי": ["ג", "ד"],
            'ביה"ס נוכחי': ["מקור", "מקור"],
            "כיתה": [1, 1],
            "מוצא": [None, None],
            "הישגים לימודיים": ["בינונית", "בינונית"],
            "תלמידה דיפרנציאלית": ["כן", float("nan")],
            "תלמידה בשילוב": [None, "כן"],
            'סטטוס ח"מ': [float("nan"), None],
            "בקשות חברות (שמות, מופרד בפסיקים)": ["", ""],
        }
    )
    mapping = guess_mapping(list(raw_df.columns), raw_df)
    mapped = apply_mapping(raw_df, mapping)
    assert mapped[FIELD_DIFFERENTIAL].tolist() == [True, False]
    assert mapped[FIELD_INCLUSION].tolist() == [False, True]
    assert mapped[FIELD_HAMAR].tolist() == [False, False]


def test_stale_manual_defaults_do_not_overwrite_mapped_source_fields():
    raw_df = pd.DataFrame(
        {
            "מספר סידורי": [1],
            "שם משפחה": ["א"],
            "שם פרטי": ["ב"],
            'ביה"ס נוכחי': ["מקור"],
            "כיתה": [1],
            "מוצא": [None],
            "הישגים לימודיים": ["בינונית"],
            "תלמידה דיפרנציאלית": ["כן"],
            "תלמידה בשילוב": ["כן"],
            'סטטוס ח"מ': ["כן"],
            "בקשות חברות (שמות, מופרד בפסיקים)": ["חברה מדומה"],
        }
    )
    mapping = guess_mapping(list(raw_df.columns), raw_df)
    manual_df = pd.DataFrame(
        {
            FIELD_STUDENT_ID: [1],
            FIELD_DIFFERENTIAL: [False],
            FIELD_INCLUSION: [False],
            FIELD_HAMAR: [False],
            FIELD_FRIEND_REQUESTS: [""],
        }
    )
    mapped = apply_mapping(raw_df, mapping, manual_df=manual_df)
    assert mapped.loc[0, FIELD_DIFFERENTIAL]
    assert mapped.loc[0, FIELD_INCLUSION]
    assert mapped.loc[0, FIELD_HAMAR]
    assert mapped.loc[0, FIELD_FRIEND_REQUESTS] == "חברה מדומה"
