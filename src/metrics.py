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
from src.optimizer import SolverConfig, _academic_score


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
    solver_status: str = ""
    solver_wall_time: float = 0.0
    objective_value: Optional[float] = None


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

        warnings = []
        if row.get(FIELD_DIFFERENTIAL) and row.get(FIELD_INCLUSION):
            pass
        if not requested and (FIELD_STUDENT_ID in df.columns):
            pass

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
                "אזהרות": "; ".join(warnings),
            }
        )
    return pd.DataFrame(rows)


def class_overview_table(
    df: pd.DataFrame,
    assignment: dict[int, int],
    friendship_matched: dict[int, list[int]],
    config: SolverConfig,
) -> pd.DataFrame:
    """Build the per-class overview table required by the spec."""
    rows = []
    for c in range(config.num_classes):
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

        violations = 0
        if config.ethiopian_hard and not (config.min_ethiopian_per_class <= eth_count <= config.max_ethiopian_per_class):
            violations += 1
        if config.inclusion_hard and not (config.min_inclusion_per_class <= inc_count <= config.max_inclusion_per_class):
            violations += 1
        if config.hamar_hard and not (config.min_hamar_per_class <= hamar_count <= config.max_hamar_per_class):
            violations += 1
        if config.differential_hard and diff_count > config.max_differential_per_class:
            violations += 1

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
    config: SolverConfig,
    solver_status: str = "",
    solver_wall_time: float = 0.0,
    objective_value: Optional[float] = None,
) -> GlobalMetrics:
    """Compute the global metrics summary required by the spec."""
    class_sizes = [0] * config.num_classes
    for cls in assignment.values():
        if 0 <= cls < config.num_classes:
            class_sizes[cls] += 1

    satisfied = partial = unsatisfied = 0
    mutual_hits = two_hits = 0
    denom_students = 0

    for _, row in df.iterrows():
        sid = row[FIELD_STUDENT_ID]
        requested = [r for r in friendship_matched.get(sid, []) if r != sid]
        has_requests = len(requested) > 0
        if config.denominator_all_students or has_requests:
            denom_students += 1
        if not has_requests:
            continue
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

    class_overview = class_overview_table(df, assignment, friendship_matched, config)
    violations_count = int(class_overview["חריגות"].sum()) if not class_overview.empty else 0

    return GlobalMetrics(
        total_students=len(df),
        num_classes=config.num_classes,
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
        solver_status=solver_status,
        solver_wall_time=solver_wall_time,
        objective_value=objective_value,
    )


def violations_report(
    df: pd.DataFrame,
    assignment: dict[int, int],
    config: SolverConfig,
) -> pd.DataFrame:
    """Build the violations & exceptions report required by the spec."""
    rows = []
    for c in range(config.num_classes):
        members = [sid for sid, cls in assignment.items() if cls == c]
        sub = df[df[FIELD_STUDENT_ID].isin(members)]
        size = len(sub)
        eth = int(sub[FIELD_ETHIOPIAN_ORIGIN].sum()) if size else 0
        inc = int(sub[FIELD_INCLUSION].sum()) if size else 0
        hamar = int(sub[FIELD_HAMAR].sum()) if size else 0
        diff = int(sub[FIELD_DIFFERENTIAL].sum()) if size else 0

        def add_row(rule, expected, actual, severity, hard):
            rows.append(
                {
                    "כלל": rule,
                    "כיתה": c + 1,
                    "צפוי": expected,
                    "בפועל": actual,
                    "חומרה": severity,
                    "קשה/רכה": "קשה" if hard else "רכה",
                    "תיקון מוצע": "העברת תלמידה מתאימה לכיתה אחרת" if actual != expected else "",
                }
            )

        if not (config.min_ethiopian_per_class <= eth <= config.max_ethiopian_per_class):
            add_row(
                "מוצא אתיופי לכיתה",
                f"{config.min_ethiopian_per_class}-{config.max_ethiopian_per_class}",
                eth,
                "גבוהה",
                config.ethiopian_hard,
            )
        if not (config.min_inclusion_per_class <= inc <= config.max_inclusion_per_class):
            add_row(
                "שילוב לכיתה",
                f"{config.min_inclusion_per_class}-{config.max_inclusion_per_class}",
                inc,
                "גבוהה",
                config.inclusion_hard,
            )
        if not (config.min_hamar_per_class <= hamar <= config.max_hamar_per_class):
            add_row(
                'ח"מ לכיתה',
                f"{config.min_hamar_per_class}-{config.max_hamar_per_class}",
                hamar,
                "בינונית",
                config.hamar_hard,
            )
        if diff > config.max_differential_per_class:
            add_row("דיפרנציאלית לכיתה", f"<= {config.max_differential_per_class}", diff, "גבוהה", config.differential_hard)

    return pd.DataFrame(rows)
