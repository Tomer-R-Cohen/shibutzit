"""Arbitrary spreadsheet columns: detection, and whether a rule about one
actually reaches the solver.

The app knew exactly four categories by name, and `apply_mapping` dropped
every other column in the uploaded workbook. That made it a tool for one
school's spreadsheet. The solver never had that limitation -- src/optimizer.py
contains no reference to any category -- so these tests are mostly about the
plumbing on either side of it.

The end-to-end test at the bottom is the one that matters: a school-specific
column, turned into a rule through the same tool path the chat uses, actually
constraining a real solve.
"""

import io

import pandas as pd
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.read_tools import execute_read_tool, groupable_fields
from backend.llm.tools import ProposeCapacityArgs, ToolArgumentError, args_to_constraint
from backend.routers.optimize import _review_groups
from backend.session_store import store
from src.column_mapping import FIELD_STUDENT_ID
from src.constraints import resolve_group_members
from src.dataset_schema import (
    attach_extra_columns,
    classify_series,
    detect_extra_columns,
    sanitize_key,
)
from src.optimizer import SolverConfig, optimize


# ------------------------------------------------------------------ detection

@pytest.mark.parametrize(
    "values,expected",
    [
        (["כן", "", "כן", ""], "flag"),
        ([1, 0, 1, 0], "flag"),
        (["V", "", "V"], "flag"),
        (["א", "", "א"], "flag"),
        (["רמת אביב", "צפון", "רמת אביב"], "category"),
        ([3.5, 2.0, 4.25], "number"),
        ([f"note number {i}" for i in range(40)], None),  # free text
        (["", "", ""], None),  # empty
        ([0, 0, 0], None),  # nobody flagged -> describes no subgroup
        (["כן", "כן", "כן"], None),  # everybody flagged -> same
        (["צפון", "צפון", "צפון"], None),  # a constant, not a category
    ],
)
def test_classify_series(values, expected):
    kind, _values, _true = classify_series(pd.Series(values))
    assert kind == expected


def test_detect_skips_mapped_layout_and_note_columns():
    raw = pd.DataFrame(
        {
            "שם פרטי": ["א", "ב", "ג"],
            "Unnamed: 3": [1, 2, 3],
            "הערות": ["טקסט חופשי ארוך " + str(i) for i in range(3)],
            "תאומות": ["כן", "", "כן"],
            "שכונה": ["צפון", "דרום", "צפון"],
        }
    )
    schema = detect_extra_columns(raw, mapped_source_columns={"שם פרטי"})
    labels = {c.label for c in schema.extras}

    assert labels == {"תאומות", "שכונה"}, "mapped, layout and note columns must be skipped"
    assert schema.get("x_תאומות").kind == "flag"
    assert schema.get("x_תאומות").true_count == 2
    assert schema.get("x_שכונה").kind == "category"
    assert set(schema.get("x_שכונה").values) == {"צפון", "דרום"}


def test_keys_are_prefixed_and_collision_free():
    """`x_` keeps an extra column from ever shadowing a semantic field."""
    taken: set[str] = set()
    a = sanitize_key("תאומות", taken)
    taken.add(a)
    b = sanitize_key("תאומות", taken)
    assert a == "x_תאומות"
    assert b != a and b.startswith("x_תאומות")
    assert sanitize_key("student_id", set()) == "x_student_id"


def test_flag_columns_become_real_booleans():
    """The bug this prevents: any non-empty string is truthy in Python, so
    leaving a column of "כן"/"" as strings would make resolve_group_members
    match every student, silently."""
    raw = pd.DataFrame({"תאומות": ["כן", "", "כן", None]})
    mapped = pd.DataFrame({FIELD_STUDENT_ID: [1, 2, 3, 4]})
    schema = detect_extra_columns(raw, set())
    out = attach_extra_columns(mapped, raw, schema)

    assert out["x_תאומות"].tolist() == [True, False, True, False]
    members = resolve_group_members(out, {"kind": "field", "field": "x_תאומות"})
    assert members == [1, 3], "only the flagged students belong to the group"


def test_row_count_mismatch_is_refused():
    """Extras are assigned positionally, so a length mismatch would silently
    attach every value to the wrong student."""
    raw = pd.DataFrame({"תאומות": ["כן", ""]})
    schema = detect_extra_columns(raw, set())
    with pytest.raises(ValueError):
        attach_extra_columns(pd.DataFrame({FIELD_STUDENT_ID: [1, 2, 3]}), raw, schema)


# ------------------------------------------------------- the full chain

@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def session_with_extra_column(client):
    """The real roster, plus a school-specific column the app has never
    heard of, attached the same way an upload would."""
    session_id = "dataset-schema-test-session"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
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

    sess = store.get_or_create(session_id)
    n = len(sess.mapped_df)
    # Every 20th student is a "twin" -- 11 of 217. A cap of 2 across 6 classes
    # allows at most 12, so the rule genuinely binds: the solver has to spread
    # them almost perfectly evenly or fail.
    raw = pd.DataFrame({"תאומות": ["כן" if i % 20 == 0 else "" for i in range(n)]})
    schema = detect_extra_columns(raw, set())
    sess.mapped_df = attach_extra_columns(sess.mapped_df, raw, schema)
    sess.dataset_schema = schema
    yield headers, sess
    store.reset(session_id)


def test_unknown_column_is_reported_as_such(session_with_extra_column):
    """Since group_field stopped being a closed enum, nothing else stops the
    model inventing a column -- and an invented one would produce a rule that
    matches zero students and looks like it worked."""
    _headers, sess = session_with_extra_column
    args = ProposeCapacityArgs(group_field="x_לא_קיים", max=2, hard=True, rationale_hebrew="בדיקה")

    with pytest.raises(ToolArgumentError) as e:
        args_to_constraint("propose_capacity", args, sess.token_map.id_for, allowed_fields=groupable_fields(sess))
    assert "x_לא_קיים" in str(e.value)


def test_groupable_fields_includes_builtins_and_extras(session_with_extra_column):
    _headers, sess = session_with_extra_column
    fields = groupable_fields(sess)
    assert "inclusion" in fields and "ethiopian_origin" in fields
    assert "x_תאומות" in fields
    assert "academic_level" in fields, "descriptive columns should be constrainable too"


def test_get_dataset_columns_lists_builtins_and_extras(session_with_extra_column):
    _headers, sess = session_with_extra_column
    out = execute_read_tool("get_dataset_columns", {}, sess)
    by_key = {c["key"]: c for c in out["columns"]}

    assert by_key["x_תאומות"]["kind"] == "flag"
    assert by_key["x_תאומות"]["label"] == "תאומות"
    assert by_key["x_תאומות"]["builtin"] is False
    assert by_key["inclusion"]["builtin"] is True
    assert by_key["academic_level"]["kind"] == "category"


def test_query_roster_filters_on_a_school_specific_column(session_with_extra_column):
    _headers, sess = session_with_extra_column
    sess.token_map.ensure_all(sess.mapped_df[FIELD_STUDENT_ID].tolist())

    out = execute_read_tool("query_roster", {"column": "x_תאומות", "limit": 5}, sess)
    assert out["count"] == int(sess.mapped_df["x_תאומות"].sum())
    assert all(t.startswith("STUDENT_") for t in out["tokens"])

    bad = execute_read_tool("query_roster", {"column": "x_nope"}, sess)
    assert bad["error"] == "unknown_column"


def test_a_rule_on_an_unknown_column_actually_constrains_the_solve(session_with_extra_column):
    """The whole point. A column this app has never heard of, turned into a
    rule through the same path the chat uses, enforced by the solver."""
    _headers, sess = session_with_extra_column
    df = sess.mapped_df
    total_twins = int(df["x_תאומות"].sum())
    # Tight but possible: 11 students, 6 classes, at most 2 each = 12 seats.
    assert 6 < total_twins <= 12, f"{total_twins} flagged -- cap of 2 must bind without being impossible"

    args = ProposeCapacityArgs(
        group_field="x_תאומות", max=2, hard=True, rationale_hebrew="עד שתי תאומות בכיתה"
    )
    constraint = args_to_constraint(
        "propose_capacity", args, sess.token_map.id_for, allowed_fields=groupable_fields(sess)
    )
    assert constraint.args["group"] == {"kind": "field", "field": "x_תאומות"}
    review = _review_groups(sess, [constraint])
    assert review[0]["label"] == "תאומות"
    assert review[0]["hard"] is True
    assert review[0]["max"] == 2
    assert len(review[0]["member_ids"]) == total_twins

    cfg = SolverConfig(num_classes=6, time_limit_seconds=15)
    result = optimize(df, cfg, sess.constraints + [constraint], friendship_matched={})
    assert result.is_feasible, result.status_name

    per_class = [0] * cfg.num_classes
    for sid, cls in result.assignment.items():
        if bool(df.loc[df[FIELD_STUDENT_ID] == sid, "x_תאומות"].iloc[0]):
            per_class[cls] += 1
    assert max(per_class) <= 2, f"cap of 2 not honoured: {per_class}"


def test_category_column_rule_uses_a_single_value(session_with_extra_column):
    """A category column only becomes a group once you say which value."""
    _headers, sess = session_with_extra_column
    args = ProposeCapacityArgs(
        group_field="academic_level", group_value="מצטיינת", max=8, hard=False, rationale_hebrew="לפזר מצטיינות"
    )
    constraint = args_to_constraint(
        "propose_capacity", args, sess.token_map.id_for, allowed_fields=groupable_fields(sess)
    )
    assert constraint.args["group"] == {"kind": "field_value", "field": "academic_level", "value": "מצטיינת"}

    review = _review_groups(sess, [constraint])
    assert review[0]["label"] == "הישגים לימודיים: מצטיינת"
    assert review[0]["hard"] is False

    members = resolve_group_members(sess.mapped_df, constraint.args["group"])
    assert len(members) > 0
