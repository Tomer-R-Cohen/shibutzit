"""Manual locking and reassignment of students after an optimizer run."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.column_mapping import FIELD_STUDENT_ID


class ManualAdjustmentError(Exception):
    """Raised when a manual adjustment request is invalid."""


@dataclass
class AdjustmentState:
    """Tracks the current (possibly manually edited) assignment and locks."""

    assignment: dict[int, int] = field(default_factory=dict)
    locked: set[int] = field(default_factory=set)

    def move_student(self, student_id: int, new_class: int, num_classes: int) -> None:
        """Move a student to a new class (0-based index)."""
        if student_id not in self.assignment:
            raise ManualAdjustmentError("התלמידה אינה קיימת בשיבוץ הנוכחי.")
        if new_class < 0 or new_class >= num_classes:
            raise ManualAdjustmentError(f"כיתה {new_class + 1} אינה קיימת (יש לבחור 1..{num_classes}).")
        self.assignment[student_id] = new_class

    def lock(self, student_id: int) -> None:
        self.locked.add(student_id)

    def unlock(self, student_id: int) -> None:
        self.locked.discard(student_id)

    def lock_all_current(self) -> None:
        self.locked = set(self.assignment.keys())

    def locked_assignment(self) -> dict[int, int]:
        return {sid: cls for sid, cls in self.assignment.items() if sid in self.locked}


def apply_editor_dataframe(
    state: AdjustmentState, edited_df: pd.DataFrame, class_column: str, id_column: str = FIELD_STUDENT_ID
) -> AdjustmentState:
    """Apply changes from an editor-style (one-row-per-student) DataFrame back into state.

    Args:
        state: current AdjustmentState (mutated in place and returned).
        edited_df: DataFrame with at least id_column and class_column
            (class values are 1-based in the UI; converted to 0-based here).
        class_column: name of the column holding the (1-based) class number.
        id_column: name of the student-id column.

    Returns:
        The mutated AdjustmentState.

    Raises:
        ManualAdjustmentError: if a row has a missing/invalid class value.
    """
    for _, row in edited_df.iterrows():
        sid = row[id_column]
        cls_raw = row[class_column]
        if pd.isna(cls_raw):
            raise ManualAdjustmentError(f"לא נבחרה כיתה עבור תלמידה {sid}.")
        cls0 = int(cls_raw) - 1
        state.assignment[sid] = cls0
    return state
