"""Audited edits to the project's working copy of uploaded student data.

The source workbook is immutable. Confirmed corrections are stored as a
small overlay keyed by student id and reapplied whenever the mapped roster is
rebuilt. This keeps the original recoverable while making the corrected data
authoritative for validation, friendship resolution, solving, and export.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_FRIEND_REQUESTS,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_STUDENT_ID,
)
from src.friendship_graph import resolve_requests, unmatched_report
from src.validation import VALID_ACADEMIC_LEVELS, validate_students


BOOLEAN_FIELDS = {
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_INCLUSION,
    FIELD_HAMAR,
}


class DataEditError(ValueError):
    pass


def normalize_student_value(df: pd.DataFrame, field: str, value: Any, extra_field_kinds: dict[str, str] | None = None) -> Any:
    if field == FIELD_STUDENT_ID:
        raise DataEditError("Student identifiers cannot be edited. Correct the source file and upload it again.")
    if field not in df.columns:
        raise DataEditError(f"Column '{field}' does not exist in the mapped workbook.")

    kind = (extra_field_kinds or {}).get(field)
    if field in BOOLEAN_FIELDS or kind == "flag":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().casefold()
        if normalized in {"true", "1", "yes", "כן", "כּן"}:
            return True
        if normalized in {"false", "0", "no", "לא", ""}:
            return False
        raise DataEditError("This field accepts only yes/no values.")

    if field == FIELD_ACADEMIC_LEVEL:
        normalized = str(value).strip()
        if normalized not in VALID_ACADEMIC_LEVELS:
            allowed = ", ".join(sorted(VALID_ACADEMIC_LEVELS))
            raise DataEditError(f"Academic level must be one of: {allowed}.")
        return normalized

    if field == FIELD_FRIEND_REQUESTS:
        return "" if value is None else str(value).strip()

    if value is None:
        return ""
    return str(value).strip()


def apply_student_data_edits(df: pd.DataFrame, edits: dict[int, dict[str, Any]] | None) -> pd.DataFrame:
    if not edits:
        return df
    out = df.copy()
    for raw_student_id, field_values in edits.items():
        student_id = int(raw_student_id)
        mask = out[FIELD_STUDENT_ID] == student_id
        if not mask.any():
            continue
        for field, value in field_values.items():
            if field in out.columns and field != FIELD_STUDENT_ID:
                out.loc[mask, field] = value
    return out


def apply_confirmed_student_edit(sess, student_id: int, field: str, value: Any) -> tuple[Any, Any]:
    if sess.mapped_df is None:
        raise DataEditError("No mapped workbook is available.")
    row = sess.mapped_df.loc[sess.mapped_df[FIELD_STUDENT_ID] == student_id]
    if row.empty:
        raise DataEditError("The student no longer exists in the project data.")

    extra_kinds = {item.key: item.kind for item in getattr(sess.dataset_schema, "extras", [])}
    normalized = normalize_student_value(sess.mapped_df, field, value, extra_kinds)
    old_value = row.iloc[0][field]
    if pd.isna(old_value):
        old_value = None
    if old_value == normalized:
        raise DataEditError("The requested value is already active.")

    sess.student_data_edits.setdefault(int(student_id), {})[field] = normalized
    sess.mapped_df.loc[sess.mapped_df[FIELD_STUDENT_ID] == student_id, field] = normalized
    # Invalidate stale solve/data diagnostics first, then rebuild the reports
    # from the corrected authoritative frame. Reversing this order makes
    # mark_inputs_changed immediately discard the fresh validation result.
    sess.mark_inputs_changed(data_changed=True, clear_result=True)
    sess.validation_report = validate_students(sess.mapped_df)
    sess.friendship_result = resolve_requests(sess.mapped_df)
    sess.unmatched_df = unmatched_report(sess.friendship_result)
    return old_value, normalized
