"""Column mapping between a raw workbook and the app's semantic student model.

The real source workbook only contains a subset of the fields the
application needs. Fields that don't exist in the source (differential
status, inclusion status, ח"מ status, friendship requests) are supported as
"not present / enter manually": the UI presents an editable table (keyed by
student id) with sensible defaults that the user can edit or bulk-import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

# Canonical (semantic) field names used throughout the app.
FIELD_STUDENT_ID = "student_id"
FIELD_LAST_NAME = "last_name"
FIELD_FIRST_NAME = "first_name"
FIELD_CURRENT_SCHOOL = "current_school"
FIELD_CURRENT_CLASS = "current_class"
FIELD_ETHIOPIAN_ORIGIN = "ethiopian_origin"
FIELD_ACADEMIC_LEVEL = "academic_level"
FIELD_DIFFERENTIAL = "differential"
FIELD_INCLUSION = "inclusion"
FIELD_HAMAR = "hamar"  # ח"מ (חדר מלא)
FIELD_FRIEND_REQUESTS = "friend_requests_raw"  # free-text list of names

REQUIRED_FIELDS = [
    FIELD_STUDENT_ID,
    FIELD_LAST_NAME,
    FIELD_FIRST_NAME,
    FIELD_CURRENT_SCHOOL,
    FIELD_CURRENT_CLASS,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_ACADEMIC_LEVEL,
]

OPTIONAL_MANUAL_FIELDS = [
    FIELD_DIFFERENTIAL,
    FIELD_INCLUSION,
    FIELD_HAMAR,
    FIELD_FRIEND_REQUESTS,
]

FIELD_LABELS_HE = {
    FIELD_STUDENT_ID: "מספר סידורי / מזהה",
    FIELD_LAST_NAME: "שם משפחה",
    FIELD_FIRST_NAME: "שם פרטי",
    FIELD_CURRENT_SCHOOL: 'ביה"ס נוכחי',
    FIELD_CURRENT_CLASS: "כיתה נוכחית",
    FIELD_ETHIOPIAN_ORIGIN: "מוצא (יוצאי אתיופיה)",
    FIELD_ACADEMIC_LEVEL: "הישגים לימודיים",
    FIELD_DIFFERENTIAL: "תלמידה דיפרנציאלית",
    FIELD_INCLUSION: "תלמידה בשילוב",
    FIELD_HAMAR: 'סטטוס ח"מ',
    FIELD_FRIEND_REQUESTS: "בקשות חברות (שמות, מופרד בפסיקים)",
}

# Default guesses for the real workbook's column names (post header-row load).
DEFAULT_GUESS_MAP = {
    FIELD_STUDENT_ID: "מספר סידורי",  # falls back to first column heuristics
    FIELD_LAST_NAME: "שם משפחה",
    FIELD_FIRST_NAME: "שם פרטי",
    FIELD_CURRENT_SCHOOL: 'ביה"ס נוכחי',
    FIELD_CURRENT_CLASS: "כיתה",
    FIELD_ETHIOPIAN_ORIGIN: "מוצא",
    FIELD_ACADEMIC_LEVEL: "הישגים לימודיים",
}

OPTIONAL_GUESS_MAP = {
    FIELD_DIFFERENTIAL: ("תלמידה דיפרנציאלית", "דיפרנציאלית"),
    FIELD_INCLUSION: ("תלמידה בשילוב", "שילוב"),
    FIELD_HAMAR: ('סטטוס ח"מ', 'ח"מ'),
    FIELD_FRIEND_REQUESTS: (
        "בקשות חברות (שמות, מופרד בפסיקים)",
        "בקשות חברות",
        "חברות מבוקשות",
    ),
}


class ColumnMappingError(Exception):
    """Raised when a column mapping is invalid or incomplete."""


@dataclass
class ColumnMapping:
    """Maps semantic field names to raw workbook column names.

    A value of None for a required field means it must be supplied via
    manual entry (only meaningful for the optional manual fields).
    """

    mapping: dict[str, Optional[str]] = field(default_factory=dict)
    manual_fields: set[str] = field(default_factory=set)

    def get(self, semantic_field: str) -> Optional[str]:
        return self.mapping.get(semantic_field)

    def set(self, semantic_field: str, raw_column: Optional[str]) -> None:
        self.mapping[semantic_field] = raw_column

    def mark_manual(self, semantic_field: str) -> None:
        self.manual_fields.add(semantic_field)
        self.mapping[semantic_field] = None

    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty if valid)."""
        problems = []
        for f in REQUIRED_FIELDS:
            if f in (FIELD_STUDENT_ID, FIELD_ETHIOPIAN_ORIGIN):
                continue  # id can be generated; origin may legitimately be absent
            col = self.mapping.get(f)
            if col is None and f not in self.manual_fields:
                problems.append(f"השדה '{FIELD_LABELS_HE.get(f, f)}' לא מופה.")
        return problems


def _is_unique_integer_column(series: pd.Series) -> bool:
    """True if the non-null values of `series` are all-integer and unique."""
    non_null = series.dropna()
    if non_null.empty:
        return False
    try:
        as_numeric = pd.to_numeric(non_null, errors="coerce")
    except Exception:
        return False
    if as_numeric.isna().any():
        return False
    if not (as_numeric == as_numeric.round()).all():
        return False
    return as_numeric.is_unique


def _guess_student_id_column(columns: list[str], raw_df: Optional[pd.DataFrame]) -> Optional[str]:
    """Data-driven fallback for locating the student id column.

    Used when no column matches the expected name ("מספר סידורי") exactly.
    Prefers a pandas auto-named blank-header column (e.g. "Unnamed: 1") if it
    is a plausible unique integer id column, otherwise falls back to the
    first all-unique-integer column found.
    """
    if raw_df is None:
        return None

    unnamed_candidates = [c for c in columns if isinstance(c, str) and c.startswith("Unnamed: ")]
    for c in unnamed_candidates:
        if c in raw_df.columns and _is_unique_integer_column(raw_df[c]):
            return c

    for c in columns:
        if c in raw_df.columns and _is_unique_integer_column(raw_df[c]):
            return c

    return None


def guess_mapping(columns: list[str], raw_df: Optional[pd.DataFrame] = None) -> ColumnMapping:
    """Produce a best-effort default mapping given the raw column names.

    Args:
        columns: the raw workbook's column names.
        raw_df: optional raw DataFrame. When provided, used as a fallback
            heuristic to locate the student-id column by data shape (unique
            integer values) when no column matches the expected name.
    """
    cm = ColumnMapping()
    for semantic, guess in DEFAULT_GUESS_MAP.items():
        if guess in columns:
            cm.set(semantic, guess)
        else:
            cm.set(semantic, None)

    if cm.get(FIELD_STUDENT_ID) is None:
        guessed = _guess_student_id_column(columns, raw_df)
        if guessed is not None:
            cm.set(FIELD_STUDENT_ID, guessed)

    # Optional fields are mapped when the workbook names them explicitly;
    # otherwise they remain available through the manual-entry workflow.
    for field_name in OPTIONAL_MANUAL_FIELDS:
        source_column = next(
            (candidate for candidate in OPTIONAL_GUESS_MAP[field_name] if candidate in columns),
            None,
        )
        if source_column is not None:
            cm.set(field_name, source_column)
            cm.manual_fields.discard(field_name)
        else:
            cm.mark_manual(field_name)
    if cm.get(FIELD_ETHIOPIAN_ORIGIN) is None:
        cm.mark_manual(FIELD_ETHIOPIAN_ORIGIN)
    return cm


def apply_mapping(
    raw_df: pd.DataFrame,
    mapping: ColumnMapping,
    manual_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build a standardized student DataFrame using semantic column names.

    Args:
        raw_df: the raw workbook DataFrame (post header row).
        mapping: a ColumnMapping describing which raw columns map to which
            semantic fields.
        manual_df: optional DataFrame keyed by FIELD_STUDENT_ID providing
            values for fields marked manual (differential/inclusion/hamar/
            friend_requests/ethiopian_origin etc). Merged in by student id.

    Returns:
        A DataFrame with one column per semantic field (required fields
        always present; optional fields present with defaults if not
        manually supplied).

    Raises:
        ColumnMappingError: if required fields are missing and not manual.
    """
    problems = mapping.validate()
    if problems:
        raise ColumnMappingError("; ".join(problems))

    out = pd.DataFrame(index=raw_df.index)

    for f in REQUIRED_FIELDS:
        col = mapping.get(f)
        if col is not None:
            out[f] = raw_df[col]
        else:
            out[f] = None

    # student_id: if not mapped, synthesize from row position.
    if out[FIELD_STUDENT_ID].isna().all():
        out[FIELD_STUDENT_ID] = range(1, len(out) + 1)

    for f in OPTIONAL_MANUAL_FIELDS:
        col = mapping.get(f)
        if col is not None and col in raw_df.columns:
            out[f] = raw_df[col]
        else:
            out[f] = _default_for(f)

    out[FIELD_ETHIOPIAN_ORIGIN] = out[FIELD_ETHIOPIAN_ORIGIN].apply(_normalize_origin)
    for bool_field in (FIELD_DIFFERENTIAL, FIELD_INCLUSION, FIELD_HAMAR):
        out[bool_field] = out[bool_field].apply(_normalize_bool)

    if manual_df is not None and not manual_df.empty and FIELD_STUDENT_ID in manual_df.columns:
        manual_df = manual_df.set_index(FIELD_STUDENT_ID)
        out = out.set_index(FIELD_STUDENT_ID, drop=False)
        for col in manual_df.columns:
            # A persisted manual table contains every optional field for UI
            # convenience. It may override only fields explicitly configured
            # as manual; a mapped workbook column remains the source of truth.
            if col in out.columns and col in mapping.manual_fields:
                out[col] = manual_df[col].combine_first(out[col]) if col in out else manual_df[col]
                out.update(manual_df[[col]])
        out = out.reset_index(drop=True)

    return out


def _default_for(field_name: str):
    if field_name == FIELD_FRIEND_REQUESTS:
        return ""
    return False


def _normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip()
    if text in ("", "nan", "None"):
        return False
    return text in ("1", "כן", "True", "true", "V", "v", "✓", "א")


def _normalize_origin(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return text == "א"


def build_empty_manual_frame(student_ids: list) -> pd.DataFrame:
    """Build an editable manual-entry DataFrame with sensible defaults."""
    return pd.DataFrame(
        {
            FIELD_STUDENT_ID: student_ids,
            FIELD_DIFFERENTIAL: [False] * len(student_ids),
            FIELD_INCLUSION: [False] * len(student_ids),
            FIELD_HAMAR: [False] * len(student_ids),
            FIELD_FRIEND_REQUESTS: [""] * len(student_ids),
        }
    )
