"""Data validation: duplicate detection and basic data-quality checks.

Duplicates are detected but never silently dropped — callers must inspect
the ValidationReport and decide how to resolve them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_SCHOOL,
    FIELD_FIRST_NAME,
    FIELD_LAST_NAME,
    FIELD_STUDENT_ID,
)

VALID_ACADEMIC_LEVELS = {"מצטיינת", "בינונית", "חלשה"}


class ValidationError(Exception):
    """Raised for validation failures that block further processing."""


@dataclass
class Issue:
    """A single validation finding."""

    category: str
    severity: str  # "error" | "warning"
    message: str
    student_ids: list = field(default_factory=list)


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def add(self, category: str, severity: str, message: str, student_ids=None) -> None:
        self.issues.append(Issue(category, severity, message, student_ids or []))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "קטגוריה": i.category,
                    "חומרה": i.severity,
                    "הודעה": i.message,
                    "תלמידות": ", ".join(str(x) for x in i.student_ids),
                }
                for i in self.issues
            ]
        )


def find_duplicate_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows whose student_id repeats more than once."""
    counts = df[FIELD_STUDENT_ID].value_counts()
    dup_ids = counts[counts > 1].index.tolist()
    return df[df[FIELD_STUDENT_ID].isin(dup_ids)]


def find_duplicate_names(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows with identical (first, last) name pairs (possible dup records)."""
    key = df[FIELD_LAST_NAME].astype(str).str.strip() + "|" + df[FIELD_FIRST_NAME].astype(str).str.strip()
    counts = key.value_counts()
    dup_keys = counts[counts > 1].index.tolist()
    return df[key.isin(dup_keys)]


def validate_students(df: pd.DataFrame) -> ValidationReport:
    """Run all data-quality checks on a mapped student DataFrame.

    Checks performed:
      - duplicate student ids (error; must be resolved before optimizing)
      - duplicate (first, last) name pairs (warning; may be legitimate)
      - missing required identifying fields (error)
      - academic level values outside the known vocabulary (warning)
      - empty/blank current-class values (warning, informational only)

    Returns:
        A ValidationReport; callers should refuse to optimize while
        report.has_errors() is True.
    """
    report = ValidationReport()

    if df.empty:
        report.add("כללי", "error", "לא נמצאו נתוני תלמידות לאחר המיפוי.")
        return report

    dup_ids = find_duplicate_ids(df)
    if not dup_ids.empty:
        ids = sorted(set(dup_ids[FIELD_STUDENT_ID].tolist()))
        report.add(
            "כפילויות",
            "error",
            f"נמצאו {len(ids)} מספרי מזהה כפולים. יש לתקן לפני האופטימיזציה.",
            ids,
        )

    dup_names = find_duplicate_names(df)
    if not dup_names.empty:
        ids = sorted(set(dup_names[FIELD_STUDENT_ID].tolist()))
        report.add(
            "כפילויות",
            "warning",
            f"נמצאו {len(ids)} תלמידות עם שם זהה (שם פרטי + משפחה) - ייתכן כפילות רישום.",
            ids,
        )

    missing_names = df[
        df[FIELD_LAST_NAME].isna()
        | (df[FIELD_LAST_NAME].astype(str).str.strip() == "")
        | df[FIELD_FIRST_NAME].isna()
        | (df[FIELD_FIRST_NAME].astype(str).str.strip() == "")
    ]
    if not missing_names.empty:
        ids = sorted(set(missing_names[FIELD_STUDENT_ID].tolist()))
        report.add("שדות חסרים", "error", f"{len(ids)} תלמידות ללא שם מלא.", ids)

    if FIELD_ACADEMIC_LEVEL in df.columns:
        bad_levels = df[
            df[FIELD_ACADEMIC_LEVEL].notna()
            & ~df[FIELD_ACADEMIC_LEVEL].isin(VALID_ACADEMIC_LEVELS)
            & (df[FIELD_ACADEMIC_LEVEL].astype(str).str.strip() != "")
        ]
        if not bad_levels.empty:
            ids = sorted(set(bad_levels[FIELD_STUDENT_ID].tolist()))
            report.add(
                "ערכים לא תקינים",
                "warning",
                f"{len(ids)} תלמידות עם ערך 'הישגים לימודיים' לא מוכר.",
                ids,
            )

    if FIELD_CURRENT_SCHOOL in df.columns:
        missing_school = df[
            df[FIELD_CURRENT_SCHOOL].isna() | (df[FIELD_CURRENT_SCHOOL].astype(str).str.strip() == "")
        ]
        if not missing_school.empty:
            ids = sorted(set(missing_school[FIELD_STUDENT_ID].tolist()))
            report.add(
                "שדות חסרים",
                "warning",
                f"{len(ids)} תלמידות ללא בית ספר נוכחי רשום.",
                ids,
            )

    return report
