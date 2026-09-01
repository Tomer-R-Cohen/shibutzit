"""Compute per-class, per-student, and global metrics for an assignment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

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
from src.constraints import Constraint, resolve_group_members
from src.optimizer import _academic_score


@dataclass
class GlobalMetrics:
    total_students: int
    num_classes: int
    class_sizes: list[int]
    class_size_min: int
    class_size_max: int
    class_size_spread: int
    mutual_satisfied_pct: float
    two_friends_satisfied_pct: float
    satisfied_requests: int
    partial_requests: int
    unsatisfied_requests: int
    violations_count: int
    # Sum, across the academic categories present in the workbook, of the
    # largest class count minus the smallest. Lower is more even. None means
    # the source data has no usable academic category to measure.
    academic_level_spread: Optional[int] = None
    # How many students submitted at least one friend request at all --
    # distinguishes "0% satisfied because no one asked" (this is 0) from
    # "0% satisfied because every request failed" (this is > 0). Callers
    # must not read mutual_satisfied_pct as a quality signal without
    # checking this first.
    students_with_requests: int = 0
    solver_status: str = ""
    solver_wall_time: float = 0.0
    objective_value: Optional[float] = None


def academic_level_spread(
    df: pd.DataFrame,
    assignment: dict[int, int],
    num_classes: int,
) -> Optional[int]:
    """Return a reproducible categorical academic-balance measure."""
    if FIELD_ACADEMIC_LEVEL not in df.columns or FIELD_STUDENT_ID not in df.columns:
        return None
    usable = df[[FIELD_STUDENT_ID, FIELD_ACADEMIC_LEVEL]].dropna()
    usable = usable[usable[FIELD_ACADEMIC_LEVEL].astype(str).str.strip().ne("")]
    levels = usable[FIELD_ACADEMIC_LEVEL].unique().tolist()
    if not levels:
        return None
    total = 0
    for level in levels:
        student_ids = set(usable.loc[usable[FIELD_ACADEMIC_LEVEL] == level, FIELD_STUDENT_ID].tolist())
        counts = [sum(1 for student_id in student_ids if assignment.get(student_id) == class_index) for class_index in range(num_classes)]
        if counts:
            total += max(counts) - min(counts)
    return total


def student_assignment_table(
    df: pd.DataFrame,
    assignment: dict[int, int],
    friendship_matched: dict[int, list[int]],
    locked: Optional[dict[int, int]] = None,
) -> pd.DataFrame:
    """Build the full per-student assignment table required by the spec."""
    locked = locked or {}
    rows = []
    for _, row in df.iterrows():
        sid = row[FIELD_STUDENT_ID]
        cls = assignment.get(sid)
        requested = [r for r in friendship_matched.get(sid, []) if r != sid]
        requested_same_class = [r for r in requested if assignment.get(r) == cls]
        mutual_same_class = [
            r for r in requested_same_class if sid in friendship_matched.get(r, [])
        ]
        satisfied_count = len(requested_same_class)
        has_mutual = len(mutual_same_class) >= 1
        has_two = satisfied_count >= 2
        attention = ""
        if requested and satisfied_count == 0:
            attention = f"אף אחת מ-{len(requested)} בקשות החברות לא קיבלה מענה"
        elif len(requested) >= 2 and satisfied_count == 1:
            attention = f"רק בקשת חברות אחת מתוך {len(requested)} קיבלה מענה"

        rows.append(
            {
                "מזהה": sid,
                "שם משפחה": row.get(FIELD_LAST_NAME),
                "שם פרטי": row.get(FIELD_FIRST_NAME),
                "כיתה משובצת": (cls + 1) if cls is not None else None,
                "ביה\"ס נוכחי": row.get(FIELD_CURRENT_SCHOOL),
                "כיתה נוכחית": row.get(FIELD_CURRENT_CLASS),
                "הישגים לימודיים": row.get(FIELD_ACADEMIC_LEVEL),
                "דיפרנציאלית": bool(row.get(FIELD_DIFFERENTIAL, False)),
                "מוצא אתיופי": bool(row.get(FIELD_ETHIOPIAN_ORIGIN, False)),
                "שילוב": bool(row.get(FIELD_INCLUSION, False)),
                'ח"מ': bool(row.get(FIELD_HAMAR, False)),
                "בקשות חברות": len(requested),
                "חברות מבוקשות באותה כיתה": satisfied_count,
                "חברות הדדיות באותה כיתה": len(mutual_same_class),
                "מספר בקשות שסופקו": satisfied_count,
                "לפחות חברה הדדית אחת": has_mutual,
                "לפחות 2 חברות מבוקשות": has_two,
                "נעולה": sid in locked,
                "אזהרות": attention,
            }
        )
    return pd.DataFrame(rows)


def _active_hard_capacity_constraints(constraints: list[Constraint]) -> list[Constraint]:
    return [c for c in constraints if c.active and c.hard and c.type == "capacity"]


def _capacity_violations_per_class(
    df: pd.DataFrame,
    assignment: dict[int, int],
    constraints: list[Constraint],
    num_classes: int,
) -> list[int]:
    """Count, per class, how many active hard capacity constraints it breaks."""
    class_members = [
        {sid for sid, cls in assignment.items() if cls == c} for c in range(num_classes)
    ]
    counts = [0] * num_classes
    for con in _active_hard_capacity_constraints(constraints):
        group_members = set(resolve_group_members(df, con.args["group"]))
        lo = con.args.get("min")
        hi = con.args.get("max")
        for c in range(num_classes):
            n_in_class = len(group_members & class_members[c])
            if (lo is not None and n_in_class < lo) or (hi is not None and n_in_class > hi):
                counts[c] += 1
    return counts


def class_overview_table(
    df: pd.DataFrame,
    assignment: dict[int, int],
    friendship_matched: dict[int, list[int]],
    constraints: list[Constraint],
    num_classes: int,
) -> pd.DataFrame:
    """Build the per-class overview table required by the spec."""
    violations_per_class = _capacity_violations_per_class(df, assignment, constraints, num_classes)
    rows = []
    for c in range(num_classes):
        members = [sid for sid, cls in assignment.items() if cls == c]
        sub = df[df[FIELD_STUDENT_ID].isin(members)]
        size = len(sub)
        avg_score = sub[FIELD_ACADEMIC_LEVEL].apply(_academic_score).mean() if size else 0.0
        level_dist = sub[FIELD_ACADEMIC_LEVEL].value_counts().to_dict() if size else {}
        diff_count = int(sub[FIELD_DIFFERENTIAL].sum()) if size else 0
        eth_count = int(sub[FIELD_ETHIOPIAN_ORIGIN].sum()) if size else 0
        inc_count = int(sub[FIELD_INCLUSION].sum()) if size else 0
        hamar_count = int(sub[FIELD_HAMAR].sum()) if size else 0
        school_dist = sub[FIELD_CURRENT_SCHOOL].value_counts().to_dict() if size else {}
        curclass_dist = sub[FIELD_CURRENT_CLASS].value_counts().to_dict() if size else {}

        mutual_ok = 0
        two_ok = 0
        with_requests = 0
        for sid in members:
            requested = [r for r in friendship_matched.get(sid, []) if r != sid]
            if not requested:
                continue
            with_requests += 1
            same = [r for r in requested if assignment.get(r) == c]
            mutual = [r for r in same if sid in friendship_matched.get(r, [])]
            if mutual:
                mutual_ok += 1
            if len(same) >= 2:
                two_ok += 1

        violations = violations_per_class[c]
        quality_score = max(0.0, 100.0 - violations * 15.0)
        if with_requests:
            quality_score = quality_score * 0.5 + 50.0 * (mutual_ok / with_requests)

        rows.append(
            {
                "כיתה": c + 1,
                "גודל": size,
                "ציון לימודי ממוצע": round(avg_score, 2),
                "התפלגות הישגים": level_dist,
                "דיפרנציאליות": diff_count,
                "מוצא אתיופי": eth_count,
                "שילוב": inc_count,
                'ח"מ': hamar_count,
                "התפלגות ביה\"ס": school_dist,
                "התפלגות כיתה נוכחית": curclass_dist,
                "אחוז חברות הדדית": round(100.0 * mutual_ok / with_requests, 1) if with_requests else None,
                "אחוז 2+ חברות": round(100.0 * two_ok / with_requests, 1) if with_requests else None,
                "חריגות": violations,
                "ציון איכות": round(quality_score, 1),
            }
        )
    return pd.DataFrame(rows)


def compute_global_metrics(
    df: pd.DataFrame,
    assignment: dict[int, int],
    friendship_matched: dict[int, list[int]],
    constraints: list[Constraint],
    num_classes: int,
    denominator_all_students: bool = True,
    solver_status: str = "",
    solver_wall_time: float = 0.0,
    objective_value: Optional[float] = None,
) -> GlobalMetrics:
    """Compute the global metrics summary required by the spec."""
    class_sizes = [0] * num_classes
    for cls in assignment.values():
        if 0 <= cls < num_classes:
            class_sizes[cls] += 1

    satisfied = partial = unsatisfied = 0
    mutual_hits = two_hits = 0
    denom_students = 0
    students_with_requests = 0

    for _, row in df.iterrows():
        sid = row[FIELD_STUDENT_ID]
        requested = [r for r in friendship_matched.get(sid, []) if r != sid]
        has_requests = len(requested) > 0
        if denominator_all_students or has_requests:
            denom_students += 1
        if not has_requests:
            continue
        students_with_requests += 1
        cls = assignment.get(sid)
        same = [r for r in requested if assignment.get(r) == cls]
        mutual = [r for r in same if sid in friendship_matched.get(r, [])]
        if mutual:
            mutual_hits += 1
        if len(same) >= 2:
            two_hits += 1
        if len(same) == len(requested) and requested:
            satisfied += 1
        elif same:
            partial += 1
        else:
            unsatisfied += 1

    mutual_pct = 100.0 * mutual_hits / denom_students if denom_students else 0.0
    two_pct = 100.0 * two_hits / denom_students if denom_students else 0.0

    violations_count = len(violations_report(df, assignment, constraints, num_classes))

    return GlobalMetrics(
        total_students=len(df),
        num_classes=num_classes,
        class_sizes=class_sizes,
        class_size_min=min(class_sizes) if class_sizes else 0,
        class_size_max=max(class_sizes) if class_sizes else 0,
        class_size_spread=(max(class_sizes) - min(class_sizes)) if class_sizes else 0,
        mutual_satisfied_pct=round(mutual_pct, 1),
        two_friends_satisfied_pct=round(two_pct, 1),
        satisfied_requests=satisfied,
        partial_requests=partial,
        unsatisfied_requests=unsatisfied,
        violations_count=violations_count,
        academic_level_spread=academic_level_spread(df, assignment, num_classes),
        students_with_requests=students_with_requests,
        solver_status=solver_status,
        solver_wall_time=solver_wall_time,
        objective_value=objective_value,
    )


def violations_report(
    df: pd.DataFrame,
    assignment: dict[int, int],
    constraints: list[Constraint],
    num_classes: int,
) -> pd.DataFrame:
    """Build one authoritative report covering every supported hard rule.

    Capacity violations are class-specific. Relationship, lock, and exact
    balance rules produce a row when their solver semantics are not met.
    This report drives approval safety, so omitting a rule type here would
    allow a manual edit to look valid even though the solver would reject it.
    """
    class_members = [
        {sid for sid, cls in assignment.items() if cls == c} for c in range(num_classes)
    ]
    rows = []
    def add(con: Constraint, class_value, expected, actual, suggestion) -> None:
        rows.append(
            {
                "כלל": con.label_hebrew,
                "כיתה": class_value,
                "צפוי": expected,
                "בפועל": actual,
                "חומרה": "גבוהה",
                "קשה/רכה": "קשה",
                "תיקון מוצע": suggestion,
            }
        )

    known_students = set(assignment)
    for con in constraints:
        if not con.active or not con.hard:
            continue
        args = con.args
        if con.type == "capacity":
            group_members = set(resolve_group_members(df, args["group"]))
            lo = args.get("min")
            hi = args.get("max")
            expected = f"{lo if lo is not None else 0}-{hi if hi is not None else '∞'}"
            for class_index in range(num_classes):
                actual = len(group_members & class_members[class_index])
                if (lo is not None and actual < lo) or (hi is not None and actual > hi):
                    add(con, class_index + 1, expected, actual, "העברת תלמידה מתאימה לכיתה אחרת")
        elif con.type == "separate":
            first, second = args["student_a"], args["student_b"]
            if first in known_students and second in known_students and assignment.get(first) == assignment.get(second):
                add(con, assignment[first] + 1, "כיתות נפרדות", "אותה כיתה", "העברת אחת התלמידות לכיתה אחרת")
        elif con.type == "together":
            first, second = args["student_a"], args["student_b"]
            if first in known_students and second in known_students and assignment.get(first) != assignment.get(second):
                actual = f"כיתות {assignment[first] + 1} ו-{assignment[second] + 1}"
                add(con, actual, "אותה כיתה", "כיתות שונות", "שיבוץ שתי התלמידות יחד")
        elif con.type == "at_least_one_of":
            student = args["student"]
            candidates = [candidate for candidate in args.get("candidates", []) if candidate in known_students and candidate != student]
            if student in known_students and candidates and not any(assignment.get(candidate) == assignment.get(student) for candidate in candidates):
                add(con, assignment[student] + 1, "לפחות חברה אחת מהרשימה", "אף חברה", "שיבוץ חברה אחת לפחות באותה כיתה")
        elif con.type == "locked":
            student, target = args["student"], args["class_index"]
            if student in known_students and assignment.get(student) != target:
                add(con, assignment[student] + 1, f"כיתה {target + 1}", f"כיתה {assignment[student] + 1}", "החזרת התלמידה לכיתה המקובעת")
        elif con.type == "balance":
            group = args["group"]
            if group.get("kind") == "field_all_values":
                subgroups = [
                    {"kind": "field_value", "field": group["field"], "value": value}
                    for value in df[group["field"]].dropna().unique()
                ]
            elif group.get("kind") == "fields":
                subgroups = [{"kind": "field", "field": field} for field in group["fields"]]
            else:
                subgroups = [group]
            spreads = []
            for subgroup in subgroups:
                members = set(resolve_group_members(df, subgroup))
                counts = [len(members & class_members[index]) for index in range(num_classes)]
                if counts:
                    spreads.append(max(counts) - min(counts))
            if any(spread != 0 for spread in spreads):
                add(con, "כל הכיתות", "פער 0", f"פער מרבי {max(spreads)}", "איזון מחדש בין הכיתות")

    return pd.DataFrame(rows)
