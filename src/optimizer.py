"""CP-SAT based class-assignment optimizer.

Binary decision variables x[student, class] = 1 if student assigned to
class. Hard constraints for each enabled hard rule are added directly to
the model; soft rules contribute penalty/reward terms to a single weighted
objective. All soft terms are scaled to comparable magnitude (roughly
0..num_students) before their weight is applied so that no single weight
value needs extreme tuning; this scaling is documented inline below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from ortools.sat.python import cp_model

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_CLASS,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_STUDENT_ID,
)


class OptimizationError(Exception):
    """Raised when the optimizer cannot be run (e.g. bad configuration)."""


@dataclass
class SolverConfig:
    """All tunable parameters for constraints, weights, and the solver."""

    num_classes: int = 6

    # Hard/soft toggles
    class_size_hard: bool = True
    differential_hard: bool = True
    ethiopian_hard: bool = True
    inclusion_hard: bool = True
    hamar_hard: bool = True
    locked_hard: bool = True

    # Bounds
    max_class_size_diff: int = 1
    max_differential_per_class: int = 1
    min_ethiopian_per_class: int = 3
    max_ethiopian_per_class: int = 4
    min_inclusion_per_class: int = 2
    max_inclusion_per_class: int = 2
    min_hamar_per_class: int = 1
    max_hamar_per_class: int = 2

    # Social targets
    mutual_target_pct: float = 80.0
    two_friends_target_pct: float = 70.0
    denominator_all_students: bool = True  # else only students with requests

    # Weights
    weight_mutual: float = 5.0
    weight_two_friends: float = 3.0
    weight_academic_balance: float = 2.0
    weight_school_balance: float = 2.0
    weight_current_class_balance: float = 1.5
    weight_category_balance: float = 1.0
    weight_target_distribution: float = 1.0

    time_limit_seconds: float = 30.0
    random_seed: int = 42


@dataclass
class OptimizationResult:
    status_name: str
    is_feasible: bool
    assignment: dict[int, int]  # student_id -> class index (0-based)
    objective_value: Optional[float]
    wall_time_seconds: float
    solver_log: str = ""
    infeasibility_notes: list[str] = field(default_factory=list)


def _academic_score(level) -> int:
    mapping = {"מצטיינת": 3, "בינונית": 2, "חלשה": 1}
    return mapping.get(level, 2)


def optimize(
    df: pd.DataFrame,
    config: SolverConfig,
    locked: Optional[dict[int, int]] = None,
    friendship_matched: Optional[dict[int, list[int]]] = None,
) -> OptimizationResult:
    """Run the CP-SAT optimizer over the given students.

    Args:
        df: mapped student DataFrame (must include FIELD_STUDENT_ID and all
            category columns used by hard/soft rules).
        config: SolverConfig describing constraints, weights, and solver
            parameters.
        locked: optional {student_id: class_index} of manually fixed
            assignments (class_index is 0-based).
        friendship_matched: optional {student_id: [requested_student_id,...]}
            directed friendship graph (already name-resolved).

    Returns:
        An OptimizationResult with the assignment (empty dict if infeasible)
        and solver diagnostics.

    Raises:
        OptimizationError: if the configuration is structurally invalid
            (e.g. zero classes, locked assignment to a nonexistent class).
    """
    if config.num_classes < 1:
        raise OptimizationError("מספר הכיתות חייב להיות לפחות 1.")

    locked = locked or {}
    friendship_matched = friendship_matched or {}

    students = df[FIELD_STUDENT_ID].tolist()
    n = len(students)
    k = config.num_classes

    for sid, cls in locked.items():
        if cls < 0 or cls >= k:
            raise OptimizationError(f"נעילת תלמידה {sid} לכיתה {cls} שאינה קיימת (0..{k - 1}).")

    model = cp_model.CpModel()
    x: dict[tuple, cp_model.IntVar] = {}
    for sid in students:
        for c in range(k):
            x[sid, c] = model.NewBoolVar(f"x_{sid}_{c}")

    # 1. Every student assigned exactly one class.
    for sid in students:
        model.Add(sum(x[sid, c] for c in range(k)) == 1)

    # 7. Locked assignments (hard by construction unless disabled).
    if config.locked_hard:
        for sid, cls in locked.items():
            if sid in students:
                model.Add(x[sid, cls] == 1)

    class_size = [sum(x[sid, c] for sid in students) for c in range(k)]

    # 2. Class-size balance.
    if config.class_size_hard:
        base = n // k
        upper = -(-n // k) + config.max_class_size_diff
        lower = max(0, base - config.max_class_size_diff)
        for c in range(k):
            model.Add(class_size[c] <= upper)
            model.Add(class_size[c] >= lower)

    def _bool_col_sum(field_name: str, c: int):
        return sum(
            x[row[FIELD_STUDENT_ID], c]
            for _, row in df.iterrows()
            if bool(row.get(field_name, False))
        )

    # 3. Differential per class.
    if config.differential_hard and FIELD_DIFFERENTIAL in df.columns:
        for c in range(k):
            model.Add(_bool_col_sum(FIELD_DIFFERENTIAL, c) <= config.max_differential_per_class)

    # 4. Ethiopian-origin range per class.
    if config.ethiopian_hard and FIELD_ETHIOPIAN_ORIGIN in df.columns:
        for c in range(k):
            s = _bool_col_sum(FIELD_ETHIOPIAN_ORIGIN, c)
            model.Add(s >= config.min_ethiopian_per_class)
            model.Add(s <= config.max_ethiopian_per_class)

    # 5. Inclusion range per class.
    if config.inclusion_hard and FIELD_INCLUSION in df.columns:
        for c in range(k):
            s = _bool_col_sum(FIELD_INCLUSION, c)
            model.Add(s >= config.min_inclusion_per_class)
            model.Add(s <= config.max_inclusion_per_class)

    # 6. Hamar range per class.
    if config.hamar_hard and FIELD_HAMAR in df.columns:
        for c in range(k):
            s = _bool_col_sum(FIELD_HAMAR, c)
            model.Add(s >= config.min_hamar_per_class)
            model.Add(s <= config.max_hamar_per_class)

    objective_terms = []

    # ---- Social objectives ----
    # Co-placement indicator y[a,b] = 1 if a and b end up in the same class.
    # Scaled per-student so the term magnitude is O(n), matching balance terms.
    same_class_vars: dict[tuple, cp_model.IntVar] = {}

    def get_same_class_var(a: int, b: int):
        key = (min(a, b), max(a, b))
        if key in same_class_vars:
            return same_class_vars[key]
        v = model.NewBoolVar(f"same_{key[0]}_{key[1]}")
        # v == 1 iff sum over c of x[a,c]*x[b,c] == 1; linearize with AddMultiplicationEquality-free approach.
        same_terms = []
        for c in range(k):
            both = model.NewBoolVar(f"both_{key[0]}_{key[1]}_{c}")
            model.AddMultiplicationEquality(both, [x[a, c], x[b, c]])
            same_terms.append(both)
        model.Add(v == sum(same_terms))
        same_class_vars[key] = v
        return v

    has_mutual_vars = []
    has_two_friends_vars = []
    for sid in students:
        requested = friendship_matched.get(sid, [])
        requested = [r for r in requested if r in students and r != sid]
        if not requested:
            continue
        mutuals = [r for r in requested if sid in friendship_matched.get(r, [])]
        # has_mutual: satisfied if co-placed with >=1 mutual friend
        if mutuals:
            co_vars = [get_same_class_var(sid, m) for m in mutuals]
            hm = model.NewBoolVar(f"has_mutual_{sid}")
            model.Add(sum(co_vars) >= 1).OnlyEnforceIf(hm)
            model.Add(sum(co_vars) == 0).OnlyEnforceIf(hm.Not())
            has_mutual_vars.append(hm)
            objective_terms.append(config.weight_mutual * hm)

        # two_friends: satisfied if co-placed with >=2 requested friends (any direction)
        co_vars_all = [get_same_class_var(sid, r) for r in requested]
        if len(co_vars_all) >= 1:
            cnt = model.NewIntVar(0, len(co_vars_all), f"friend_cnt_{sid}")
            model.Add(cnt == sum(co_vars_all))
            tf = model.NewBoolVar(f"two_friends_{sid}")
            model.Add(cnt >= 2).OnlyEnforceIf(tf)
            model.Add(cnt <= 1).OnlyEnforceIf(tf.Not())
            has_two_friends_vars.append(tf)
            objective_terms.append(config.weight_two_friends * tf)
            # Prefer mutual over one-sided: small bonus already via weight_mutual > per-edge scale.

    # ---- Balance objectives (soft): minimize spread of category counts across classes ----
    def add_balance_penalty(counts_expr_per_class, weight, name):
        if weight <= 0:
            return
        max_v = model.NewIntVar(0, n, f"{name}_max")
        min_v = model.NewIntVar(0, n, f"{name}_min")
        model.AddMaxEquality(max_v, counts_expr_per_class)
        model.AddMinEquality(min_v, counts_expr_per_class)
        spread = model.NewIntVar(0, n, f"{name}_spread")
        model.Add(spread == max_v - min_v)
        objective_terms.append(-weight * spread)

    if FIELD_ACADEMIC_LEVEL in df.columns:
        for level in ("מצטיינת", "בינונית", "חלשה"):
            per_class = [
                sum(x[row[FIELD_STUDENT_ID], c] for _, row in df.iterrows() if row.get(FIELD_ACADEMIC_LEVEL) == level)
                for c in range(k)
            ]
            add_balance_penalty(per_class, config.weight_academic_balance, f"academic_{level}")

    if FIELD_CURRENT_SCHOOL in df.columns:
        for school in df[FIELD_CURRENT_SCHOOL].dropna().unique():
            per_class = [
                sum(x[row[FIELD_STUDENT_ID], c] for _, row in df.iterrows() if row.get(FIELD_CURRENT_SCHOOL) == school)
                for c in range(k)
            ]
            add_balance_penalty(per_class, config.weight_school_balance, f"school_{school}")

    if FIELD_CURRENT_CLASS in df.columns:
        for cur_cls in df[FIELD_CURRENT_CLASS].dropna().unique():
            per_class = [
                sum(x[row[FIELD_STUDENT_ID], c] for _, row in df.iterrows() if row.get(FIELD_CURRENT_CLASS) == cur_cls)
                for c in range(k)
            ]
            add_balance_penalty(per_class, config.weight_current_class_balance, f"curclass_{cur_cls}")

    for cat_field in (FIELD_DIFFERENTIAL, FIELD_ETHIOPIAN_ORIGIN, FIELD_INCLUSION, FIELD_HAMAR):
        if cat_field in df.columns:
            per_class = [_bool_col_sum(cat_field, c) for c in range(k)]
            add_balance_penalty(per_class, config.weight_category_balance, f"cat_{cat_field}")

    model.Maximize(sum(objective_terms)) if objective_terms else None

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_seconds
    # Pinned to a single worker: CP-SAT's parallel portfolio search is
    # inherently non-deterministic across separate solve() calls (workers
    # race and whichever finds/improves a solution first wins), even with a
    # fixed random_seed. The app's spec requires that identical inputs
    # (same data + same config, including seed) always produce the exact
    # same solution. Do not raise this above 1 without also fixing
    # reproducibility some other way (e.g. deterministic tie-breaking).
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.random_seed

    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    assignment: dict[int, int] = {}
    notes: list[str] = []
    is_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if is_feasible:
        for sid in students:
            for c in range(k):
                if solver.Value(x[sid, c]) == 1:
                    assignment[sid] = c
                    break
    else:
        notes.append(
            "הפתרון בלתי אפשרי (INFEASIBLE) או שהזמן לא הספיק. בדקו את דוח האפשרות "
            "(Feasibility) לפני ההרצה, או הפכו מגבלות קשות למגבלות רכות."
        )

    return OptimizationResult(
        status_name=status_name,
        is_feasible=is_feasible,
        assignment=assignment,
        objective_value=solver.ObjectiveValue() if is_feasible and objective_terms else None,
        wall_time_seconds=solver.WallTime(),
        infeasibility_notes=notes,
    )
