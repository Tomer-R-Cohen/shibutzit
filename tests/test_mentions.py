import pandas as pd

from src.chat.mentions import redact_text, resolve_mentions_in_text
from src.column_mapping import FIELD_FIRST_NAME, FIELD_LAST_NAME, FIELD_STUDENT_ID


def make_df():
    return pd.DataFrame(
        [
            {FIELD_STUDENT_ID: 1, FIELD_FIRST_NAME: "שרה", FIELD_LAST_NAME: "כהן"},
            {FIELD_STUDENT_ID: 2, FIELD_FIRST_NAME: "מיכל", FIELD_LAST_NAME: "לוי"},
            {FIELD_STUDENT_ID: 3, FIELD_FIRST_NAME: "תמר", FIELD_LAST_NAME: "מזרחי"},
        ]
    )


def test_simple_match_first_last():
    df = make_df()
    mentions = resolve_mentions_in_text("צריך להושיב את שרה כהן בכיתה נפרדת", df)
    assert len(mentions) == 1
    m = mentions[0]
    assert m.status == "matched"
    assert m.student_id == 1
    assert m.raw_text == "שרה כהן"


def test_reversed_order_match():
    df = make_df()
    mentions = resolve_mentions_in_text("כהן שרה צריכה עזרה", df)
    assert len(mentions) == 1
    assert mentions[0].student_id == 1


def test_prefix_conjunction_attached_to_name():
    df = make_df()
    mentions = resolve_mentions_in_text("שרה כהן ומיכל לוי לא יכולות להיות באותה כיתה", df)
    assert len(mentions) == 2
    first, second = mentions
    assert first.status == "matched" and first.student_id == 1
    assert first.raw_text == "שרה כהן"
    assert second.status == "matched" and second.student_id == 2
    # raw_text excludes the attached "ו" prefix -- only the name itself.
    assert second.raw_text == "מיכל לוי"
    assert second.start > first.end


def test_ambiguous_duplicate_name():
    df = pd.DataFrame(
        [
            {FIELD_STUDENT_ID: 1, FIELD_FIRST_NAME: "שרה", FIELD_LAST_NAME: "כהן"},
            {FIELD_STUDENT_ID: 2, FIELD_FIRST_NAME: "שרה", FIELD_LAST_NAME: "כהן"},
        ]
    )
    mentions = resolve_mentions_in_text("שרה כהן לא צריכה להיות עם שרה כהן", df)
    assert len(mentions) == 2
    for m in mentions:
        assert m.status == "ambiguous"
        assert m.candidate_ids == [1, 2]


def test_id_reference_matched_and_unmatched():
    df = make_df()
    mentions = resolve_mentions_in_text("שבצו את #2 עם #99", df)
    assert len(mentions) == 2
    assert mentions[0].status == "matched" and mentions[0].student_id == 2
    assert mentions[1].status == "unmatched"


def test_unrelated_text_produces_no_mentions():
    df = make_df()
    mentions = resolve_mentions_in_text("אני רוצה שהכיתות יהיו מאוזנות מבחינת מגדר", df)
    assert mentions == []


def test_redact_text_replaces_matched_mentions_with_tokens():
    df = make_df()
    text = "שרה כהן ומיכל לוי לא יכולות להיות באותה כיתה"
    mentions = resolve_mentions_in_text(text, df)
    tokens = {1: "STUDENT_aaa", 2: "STUDENT_bbb"}
    redacted = redact_text(text, mentions, tokens.get)
    assert "שרה כהן" not in redacted
    assert "מיכל לוי" not in redacted
    assert redacted.startswith("STUDENT_aaa")
    # the "ו" prefix conjunction is preserved (only the name span is redacted)
    idx = redacted.index("STUDENT_bbb")
    assert redacted[idx - 1] == "ו"


def test_redact_text_leaves_non_matched_mentions_untouched():
    df = pd.DataFrame(
        [
            {FIELD_STUDENT_ID: 1, FIELD_FIRST_NAME: "שרה", FIELD_LAST_NAME: "כהן"},
            {FIELD_STUDENT_ID: 2, FIELD_FIRST_NAME: "שרה", FIELD_LAST_NAME: "כהן"},
        ]
    )
    text = "שרה כהן צריכה עזרה"
    mentions = resolve_mentions_in_text(text, df)
    assert mentions[0].status == "ambiguous"
    redacted = redact_text(text, mentions, lambda sid: "TOKEN")
    assert redacted == text


def test_redact_text_no_mentions_returns_text_unchanged():
    assert redact_text("שלום עולם", [], lambda sid: "TOKEN") == "שלום עולם"
