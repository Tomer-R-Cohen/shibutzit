"""Unified constraint representation for the class-assignment optimizer.

Every rule the solver can apply -- built-in defaults (class size, category
capacity ranges, friendship co-placement, balance objectives) and ad hoc
exceptions added later (pairwise separation, "at least one of a group",
locks) -- is represented the same way: a `Constraint` with a type-specific
`args` dict. This lets the optimizer, conflict reporting, metrics, and
export all operate over one list instead of a fixed set of hard-coded
dataclass fields, so new rule types (and eventually chat-derived ones) don't
require touching every one of those call sites again.

`default_constraints()` builds the app's ten built-in rules (class size,
four demographic capacity ranges, friendship co-placement, and four balance
objectives) as instances of this representation. It's called once, when a
session's workbook is first mapped, and the result is persisted on the
session from then on -- not re-derived on every request -- so chat and a
constraint-list UI can reference and modify the built-ins by a stable id
exactly like any exception they add later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_CLASS,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_LABELS_HE,
    FIELD_STUDENT_ID,
)

ConstraintType = Literal[
    "capacity", "separate", "together", "at_least_one_of", "balance", "locked", "friendship_objective"
]
ConstraintSource = Literal["builtin_default", "chat", "manual"]

# Group selector shapes (used by "capacity" and "balance" args["group"]):
#   {"kind": "field", "field": FIELD_X}                      -> boolean column sum
#   {"kind": "field_value", "field": FIELD_X, "value": v}     -> count of rows where field == v
#   {"kind": "members", "members": [id, ...], "label": str}   -> an explicit, ad hoc named group
#   {"kind": "all"}                                           -> every student (used by class-size)
#   {"kind": "field_all_values", "field": FIELD_X}            -> "balance" only: spread each distinct
#                                                                 value of FIELD_X evenly (one rule,
#                                                                 not one per value -- e.g. "balance
#                                                                 by school" instead of 14 near-identical
#                                                                 per-school rules)
#   {"kind": "fields", "fields": [FIELD_X, FIELD_Y, ...]}     -> "balance" only: spread each field's
#                                                                 true-count evenly, summed under one rule


@dataclass
class Constraint:
    type: ConstraintType
    hard: bool
    args: dict
    label_hebrew: str
    source: ConstraintSource = "manual"
    active: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


_CAPACITY_RANGE_LABELS = {
    FIELD_ETHIOPIAN_ORIGIN: "תלמידות ממוצא אתיופי לכיתה",
    FIELD_INCLUSION: "תלמידות שילוב לכיתה",
    FIELD_HAMAR: 'תלמידות ח"מ לכיתה',
}


def capacity_range_label_hebrew(field: str, lo, hi) -> str:
    """The "{min}-{max} <category> לכיתה" label shared by default_constraints()
    and any later min/max edit (e.g. clamp_zero_minimums), so a bound change
    never leaves the displayed label stale relative to the enforced values."""
    return f"{lo}-{hi} {_CAPACITY_RANGE_LABELS[field]}"


def class_size_label_hebrew(lo, hi) -> str:
    """Shared by default_constraints() and sync_class_size_bounds (backend/
    solver_inputs.py), same reasoning as capacity_range_label_hebrew."""
    return f"גודל כיתה בין {lo} ל-{hi}"


def resolve_group_members(df: pd.DataFrame, group: dict) -> list:
    """Return the list of student ids belonging to a group selector."""
    kind = group.get("kind")
    if kind == "field":
        field_name = group["field"]
        return [row[FIELD_STUDENT_ID] for _, row in df.iterrows() if bool(row.get(field_name, False))]
    if kind == "field_value":
        field_name = group["field"]
        value = group["value"]
        return [row[FIELD_STUDENT_ID] for _, row in df.iterrows() if row.get(field_name) == value]
    if kind == "members":
        known = set(df[FIELD_STUDENT_ID].tolist())
        return [m for m in group["members"] if m in known]
    if kind == "all":
        return df[FIELD_STUDENT_ID].tolist()
    raise ValueError(f"unknown group kind: {kind!r}")


# ---- defaults matching today's SolverConfig field defaults ----
DEFAULT_MAX_CLASS_SIZE_DIFF = 1
DEFAULT_MAX_DIFFERENTIAL_PER_CLASS = 1
DEFAULT_MIN_ETHIOPIAN_PER_CLASS = 3
DEFAULT_MAX_ETHIOPIAN_PER_CLASS = 4
DEFAULT_MIN_INCLUSION_PER_CLASS = 2
DEFAULT_MAX_INCLUSION_PER_CLASS = 2
DEFAULT_MIN_HAMAR_PER_CLASS = 1
DEFAULT_MAX_HAMAR_PER_CLASS = 2
DEFAULT_WEIGHT_MUTUAL = 5.0
DEFAULT_WEIGHT_TWO_FRIENDS = 3.0
DEFAULT_WEIGHT_ACADEMIC_BALANCE = 2.0
DEFAULT_WEIGHT_SCHOOL_BALANCE = 2.0
DEFAULT_WEIGHT_CURRENT_CLASS_BALANCE = 1.5
DEFAULT_WEIGHT_CATEGORY_BALANCE = 1.0


def default_constraints(
    df: pd.DataFrame,
    num_classes: int,
    *,
    class_size_hard: bool = True,
    max_class_size_diff: int = DEFAULT_MAX_CLASS_SIZE_DIFF,
    differential_hard: bool = True,
    max_differential_per_class: int = DEFAULT_MAX_DIFFERENTIAL_PER_CLASS,
    ethiopian_hard: bool = True,
    min_ethiopian_per_class: int = DEFAULT_MIN_ETHIOPIAN_PER_CLASS,
    max_ethiopian_per_class: int = DEFAULT_MAX_ETHIOPIAN_PER_CLASS,
    inclusion_hard: bool = True,
    min_inclusion_per_class: int = DEFAULT_MIN_INCLUSION_PER_CLASS,
    max_inclusion_per_class: int = DEFAULT_MAX_INCLUSION_PER_CLASS,
    hamar_hard: bool = True,
    min_hamar_per_class: int = DEFAULT_MIN_HAMAR_PER_CLASS,
    max_hamar_per_class: int = DEFAULT_MAX_HAMAR_PER_CLASS,
    weight_mutual: float = DEFAULT_WEIGHT_MUTUAL,
    weight_two_friends: float = DEFAULT_WEIGHT_TWO_FRIENDS,
    weight_academic_balance: float = DEFAULT_WEIGHT_ACADEMIC_BALANCE,
    weight_school_balance: float = DEFAULT_WEIGHT_SCHOOL_BALANCE,
    weight_current_class_balance: float = DEFAULT_WEIGHT_CURRENT_CLASS_BALANCE,
    weight_category_balance: float = DEFAULT_WEIGHT_CATEGORY_BALANCE,
) -> list[Constraint]:
    """Build the ten built-in rules as generic Constraints.

    Called once, when a workbook is first mapped (backend/session_store.py);
    the results are then persisted directly on the session like any other
    constraint, not re-derived on every request. Bounds/weights default to
    the values this app has always shipped with, but every knob is
    overridable.
    """
    n = len(df)
    k = max(int(num_classes), 1)
    constraints: list[Constraint] = []

    base = n // k
    upper = -(-n // k) + max_class_size_diff
    lower = max(0, base - max_class_size_diff)
    constraints.append(
        Constraint(
            type="capacity",
            hard=class_size_hard,
            # size_diff is carried alongside min/max (redundant with them at
            # creation time) so a later num_classes/roster-size change can
            # recompute min/max without losing the counselor's tolerance.
            args={"group": {"kind": "all"}, "min": lower, "max": upper, "size_diff": max_class_size_diff},
            label_hebrew=class_size_label_hebrew(lower, upper),
            source="builtin_default",
        )
    )

    if FIELD_DIFFERENTIAL in df.columns:
        constraints.append(
            Constraint(
                type="capacity",
                hard=differential_hard,
                args={"group": {"kind": "field", "field": FIELD_DIFFERENTIAL}, "min": None, "max": max_differential_per_class},
                label_hebrew=f"עד {max_differential_per_class} תלמידות דיפרנציאליות לכיתה",
                source="builtin_default",
            )
        )

    if FIELD_ETHIOPIAN_ORIGIN in df.columns:
        constraints.append(
            Constraint(
                type="capacity",
                hard=ethiopian_hard,
                args={
                    "group": {"kind": "field", "field": FIELD_ETHIOPIAN_ORIGIN},
                    "min": min_ethiopian_per_class,
                    "max": max_ethiopian_per_class,
                },
                label_hebrew=capacity_range_label_hebrew(FIELD_ETHIOPIAN_ORIGIN, min_ethiopian_per_class, max_ethiopian_per_class),
                source="builtin_default",
            )
        )

    if FIELD_INCLUSION in df.columns:
        constraints.append(
            Constraint(
                type="capacity",
                hard=inclusion_hard,
                args={
                    "group": {"kind": "field", "field": FIELD_INCLUSION},
                    "min": min_inclusion_per_class,
                    "max": max_inclusion_per_class,
                },
                label_hebrew=capacity_range_label_hebrew(FIELD_INCLUSION, min_inclusion_per_class, max_inclusion_per_class),
                source="builtin_default",
            )
        )

    if FIELD_HAMAR in df.columns:
        constraints.append(
            Constraint(
                type="capacity",
                hard=hamar_hard,
                args={"group": {"kind": "field", "field": FIELD_HAMAR}, "min": min_hamar_per_class, "max": max_hamar_per_class},
                label_hebrew=capacity_range_label_hebrew(FIELD_HAMAR, min_hamar_per_class, max_hamar_per_class),
                source="builtin_default",
            )
        )

    constraints.append(
        Constraint(
            type="friendship_objective",
            hard=False,
            args={"weight_mutual": weight_mutual, "weight_two_friends": weight_two_friends},
            label_hebrew="עידוד שיבוץ לפי בקשות חברות",
            source="builtin_default",
        )
    )

    # Each of these is ONE Constraint covering every distinct value of the
    # field (or every field in the list), not one per value -- ~10 rows
    # total for a counselor to see/edit, matching the original rules-drawer's
    # granularity (one slider per category), not one row per school.
    if FIELD_ACADEMIC_LEVEL in df.columns and weight_academic_balance > 0:
        constraints.append(
            Constraint(
                type="balance",
                hard=False,
                args={"group": {"kind": "field_all_values", "field": FIELD_ACADEMIC_LEVEL}, "weight": weight_academic_balance},
                label_hebrew="איזון רמת הישגים לימודיים",
                source="builtin_default",
            )
        )

    if FIELD_CURRENT_SCHOOL in df.columns and weight_school_balance > 0:
        constraints.append(
            Constraint(
                type="balance",
                hard=False,
                args={"group": {"kind": "field_all_values", "field": FIELD_CURRENT_SCHOOL}, "weight": weight_school_balance},
                label_hebrew="איזון בית ספר מקור",
                source="builtin_default",
            )
        )

    if FIELD_CURRENT_CLASS in df.columns and weight_current_class_balance > 0:
        constraints.append(
            Constraint(
                type="balance",
                hard=False,
                args={"group": {"kind": "field_all_values", "field": FIELD_CURRENT_CLASS}, "weight": weight_current_class_balance},
                label_hebrew="שימור כיתה נוכחית",
                source="builtin_default",
            )
        )

    category_fields = [f for f in (FIELD_DIFFERENTIAL, FIELD_ETHIOPIAN_ORIGIN, FIELD_INCLUSION, FIELD_HAMAR) if f in df.columns]
    if category_fields and weight_category_balance > 0:
        labels = ", ".join(FIELD_LABELS_HE.get(f, f) for f in category_fields)
        constraints.append(
            Constraint(
                type="balance",
                hard=False,
                args={"group": {"kind": "fields", "fields": category_fields}, "weight": weight_category_balance},
                label_hebrew=f"איזון קטגוריות: {labels}",
                source="builtin_default",
            )
        )

    return constraints


def locked_constraints(locked: Optional[dict[int, int]], hard: bool = True) -> list[Constraint]:
    """Build one 'locked' Constraint per manually-fixed student -> class entry."""
    locked = locked or {}
    return [
        Constraint(
            type="locked",
            hard=hard,
            args={"student": sid, "class_index": cls},
            label_hebrew=f"תלמידה {sid} נעולה לכיתה {cls + 1}",
            source="manual",
        )
        for sid, cls in locked.items()
    ]
