import pandas as pd

from src.column_mapping import (
    FIELD_FIRST_NAME,
    FIELD_FRIEND_REQUESTS,
    FIELD_LAST_NAME,
    FIELD_STUDENT_ID,
)
from src.friendship_graph import (
    build_edges,
    is_mutual,
    normalize_name,
    resolve_requests,
    split_requested_names,
)


def make_df():
    return pd.DataFrame(
        [
            {FIELD_STUDENT_ID: 1, FIELD_FIRST_NAME: "אביגיל", FIELD_LAST_NAME: "כהן", FIELD_FRIEND_REQUESTS: "שרה לוי, תמר מזרחי"},
            {FIELD_STUDENT_ID: 2, FIELD_FIRST_NAME: "שרה", FIELD_LAST_NAME: "לוי", FIELD_FRIEND_REQUESTS: "אביגיל כהן"},
            {FIELD_STUDENT_ID: 3, FIELD_FIRST_NAME: "תמר", FIELD_LAST_NAME: "מזרחי", FIELD_FRIEND_REQUESTS: ""},
            {FIELD_STUDENT_ID: 4, FIELD_FIRST_NAME: "נועה", FIELD_LAST_NAME: "אבן", FIELD_FRIEND_REQUESTS: "שם לא קיים כלל"},
        ]
    )


def test_normalize_name_handles_whitespace_and_quotes():
    assert normalize_name("  שם   עם   רווחים  ") == "שם עם רווחים"
    assert normalize_name("ד׳ר") == normalize_name("ד'ר")


def test_split_requested_names():
    assert split_requested_names("a, b;c\nd") == ["a", "b", "c", "d"]
    assert split_requested_names(None) == []
    assert split_requested_names("") == []


def test_resolve_requests_matches_by_name():
    df = make_df()
    result = resolve_requests(df)
    assert result.matched[1] == [2, 3]
    assert result.matched[2] == [1]


def test_mutual_detection():
    df = make_df()
    result = resolve_requests(df)
    assert is_mutual(1, 2, result.matched) is True
    assert is_mutual(1, 3, result.matched) is False


def test_unmatched_names_are_flagged():
    df = make_df()
    result = resolve_requests(df)
    unmatched_names = [n for _, n in result.unmatched]
    assert "שם לא קיים כלל" in unmatched_names


def test_build_edges_marks_mutuality():
    df = make_df()
    result = resolve_requests(df)
    edges = build_edges(result.matched)
    edge_map = {(a, b): m for a, b, m in edges}
    assert edge_map[(1, 2)] is True
    assert edge_map[(2, 1)] is True
    assert edge_map[(1, 3)] is False
