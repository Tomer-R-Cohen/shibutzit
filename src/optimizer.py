"""CP-SAT based class-assignment optimizer.

Binary decision variables x[student, class] = 1 if student assigned to
class. Rules are supplied as a list of `src.constraints.Constraint` objects
(see that module) rather than fixed dataclass fields, so any mix of
built-in defaults and ad hoc exceptions can be compiled the same way. Each
hard constraint is reified behind its own CP-SAT "assumption" literal; if
the model turns out infeasible, `solver.SufficientAssumptionsForInfeasibility()`
identifies the minimal set of constraints jointly responsible, which we map
back to `Constraint.id`s for `OptimizationResult.conflicting_constraint_ids`.
Soft constraints contribute weighted terms to a single objective, scaled to
comparable magnitude (roughly 0..num_students) so no weight needs extreme
tuning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from ortools.sat.python import cp_model

from src.column_mapping import FIELD_STUDENT_ID
from src.constraints import Constraint, resolve_group_members


class OptimizationError(Exception):
    """Raised when the optimizer cannot be run (e.g. bad configuration)."""


@dataclass
class SolverConfig:
    """Run parameters. Rule/weight configuration now lives in the
    Constraint list passed to optimize(), not here."""

    num_classes: int = 6
    denominator_all_students: bool = True  # else only students with requests
    mutual_target_pct: float = 80.0
    two_friends_target_pct: float = 70.0
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
    conflicting_constraint_ids: list[str] = field(default_factory=list)


def _academic_score(level) -> int:
    mapping = {"מצטיינת": 3, "בינונית": 2, "חלשה": 1}
    return mapping.get(level, 2)


def optimize(
    df: pd.DataFrame,
    config: SolverConfig,
    constraints: list[Constraint],
    friendship_matched: Optional[dict[int, list[int]]] = None,
) -> OptimizationResult:
    """Run the CP-SAT optimizer over the given students.

    Args:
        df: mapped student DataFrame (must include FIELD_STUDENT_ID and all
            category columns referenced by any constraint's group selector).
        config: SolverConfig with run parameters (class count, time limit,
            seed).
        constraints: the full rule list to compile (built-ins + exceptions).
            Inactive constraints (`active=False`) are skipped.
        friendship_matched: optional {student_id: [requested_student_id,...]}
            directed friendship graph (already name-resolved), consumed by
            any "friendship_objective" constraint.

    Returns:
        An OptimizationResult with the assignment (empty dict if infeasible)
        and solver diagnostics, including which constraint ids conflict when
        infeasible.

    Raises:
        OptimizationError: if the configuration is structurally invalid
            (e.g. zero classes, a lock to a nonexistent class).
    """
    if config.num_classes < 1:
        raise OptimizationError("מספר הכיתות חייב להיות לפחות 1.")

    friendship_matched = friendship_matched or {}
    active = [c for c in constraints if c.active]

    students = df[FIELD_STUDENT_ID].tolist()
    student_set = set(students)
    n = len(students)
    k = config.num_classes

    for c in active:
        if c.type == "locked":
            cls = c.args["class_index"]
            if cls < 0 or cls >= k:
                raise OptimizationError(
                    f"נעילת תלמידה {c.args['student']} לכיתה {cls} שאינה קיימת (0..{k - 1})."
                )

    model = cp_model.CpModel()
    x: dict[tuple, cp_model.IntVar] = {}
    for sid in students:
        for c in range(k):
            x[sid, c] = model.NewBoolVar(f"x_{sid}_{c}")

    # Every student assigned exactly one class.
    for sid in students:
        model.Add(sum(x[sid, c] for c in range(k)) == 1)

    objective_terms = []
    assumption_lits: list[cp_model.IntVar] = []
    # SufficientAssumptionsForInfeasibility() returns CP-SAT *variable*
    # indices (lit.Index()), not positions in the list passed to
    # AddAssumptions -- confirmed empirically, not just from docs. Map by
    # index, not by list position.
    constraint_id_by_var_index: dict[int, str] = {}

    def enable_lit(constraint: Constraint) -> cp_model.IntVar:
        """A reified 'this hard constraint is active' literal, used both to
        gate the constraint's own Add() calls (.OnlyEnforceIf) and as a CP-SAT
        assumption so infeasibility can be traced back to specific rules."""
        lit = model.NewBoolVar(f"assume_{constraint.id}")
        assumption_lits.append(lit)
        constraint_id_by_var_index[lit.Index()] = constraint.id
        return lit

    # Co-placement indicator y[a,b] = 1 if a and b end up in the same class.
    same_class_vars: dict[tuple, cp_model.IntVar] = {}

    def get_same_class_var(a: int, b: int):
        key = (min(a, b), max(a, b))
        if key in same_class_vars:
            return same_class_vars[key]
        v = model.NewBoolVar(f"same_{key[0]}_{key[1]}")
        same_terms = []
        for c in range(k):
            both = model.NewBoolVar(f"both_{key[0]}_{key[1]}_{c}")
            model.AddMultiplicationEquality(both, [x[a, c], x[b, c]])
            same_terms.append(both)
        model.Add(v == sum(same_terms))
        same_class_vars[key] = v
        return v

    def class_counts_for_group(group: dict):
        members = [m for m in resolve_group_members(df, group) if m in student_set]
        return [sum(x[sid, c] for sid in members) for c in range(k)]

    def add_spread_var(counts, name_prefix):
        max_v = model.NewIntVar(0, n, f"{name_prefix}_max")
        min_v = model.NewIntVar(0, n, f"{name_prefix}_min")
        model.AddMaxEquality(max_v, counts)
        model.AddMinEquality(min_v, counts)
        spread = model.NewIntVar(0, n, f"{name_prefix}_spread")
        model.Add(spread == max_v - min_v)
        return spread

    # ---- per-type compilers ----

    def compile_capacity(c: Constraint):
        counts = class_counts_for_group(c.args["group"])
        lo = c.args.get("min")
        hi = c.args.get("max")
        if c.hard:
            lit = enable_lit(c)
            for expr in counts:
                if lo is not None:
                    model.Add(expr >= lo).OnlyEnforceIf(lit)
                if hi is not None:
                    model.Add(expr <= hi).OnlyEnforceIf(lit)
        else:
            weight = c.args.get("weight", 1.0)
            if weight <= 0:
                return
            spread = add_spread_var(counts, c.id)
            objective_terms.append(-weight * spread)

    def compile_balance(c: Constraint):
        weight = c.args.get("weight", 1.0)
        if not c.hard and weight <= 0:
            return
        group = c.args["group"]
        kind = group.get("kind")

        # "field_all_values"/"fields" cover several sub-groups (every
        # distinct value of a field, or several fields) under one
        # Constraint -- e.g. "balance by school" is one rule, not one rule
        # per school. Each sub-group gets its own spread var; the rule's
        # total is their sum, same math as if they were separate weighted
        # terms, just presented (and toggled hard/soft, and referenced by
        # id) as a single rule.
        if kind == "field_all_values":
            field_name = group["field"]
            sub_groups = [{"kind": "field_value", "field": field_name, "value": v} for v in df[field_name].dropna().unique()]
        elif kind == "fields":
            sub_groups = [{"kind": "field", "field": f} for f in group["fields"]]
        else:
            sub_groups = [group]

        spreads = [add_spread_var(class_counts_for_group(g), f"{c.id}_{i}") for i, g in enumerate(sub_groups)]
        if not spreads:
            return
        if c.hard:
            lit = enable_lit(c)
            for spread in spreads:
                model.Add(spread == 0).OnlyEnforceIf(lit)
        else:
            objective_terms.append(-weight * sum(spreads))

    def compile_separate(c: Constraint):
        a, b = c.args["student_a"], c.args["student_b"]
        if a not in student_set or b not in student_set:
            return
        if c.hard:
            lit = enable_lit(c)
            for cls in range(k):
                model.Add(x[a, cls] + x[b, cls] <= 1).OnlyEnforceIf(lit)
        else:
            weight = c.args.get("weight", 5.0)
            objective_terms.append(-weight * get_same_class_var(a, b))

    def compile_together(c: Constraint):
        a, b = c.args["student_a"], c.args["student_b"]
        if a not in student_set or b not in student_set:
            return
        if c.hard:
            lit = enable_lit(c)
            for cls in range(k):
                model.Add(x[a, cls] == x[b, cls]).OnlyEnforceIf(lit)
        else:
            weight = c.args.get("weight", 5.0)
            objective_terms.append(weight * get_same_class_var(a, b))

    def compile_at_least_one_of(c: Constraint):
        sid = c.args["student"]
        candidates = [m for m in c.args["candidates"] if m in student_set and m != sid]
        if sid not in student_set or not candidates:
            return
        co_vars = [get_same_class_var(sid, m) for m in candidates]
        if c.hard:
            lit = enable_lit(c)
            model.Add(sum(co_vars) >= 1).OnlyEnforceIf(lit)
        else:
            weight = c.args.get("weight", 5.0)
            satisfied = model.NewBoolVar(f"{c.id}_satisfied")
            model.Add(sum(co_vars) >= 1).OnlyEnforceIf(satisfied)
            model.Add(sum(co_vars) == 0).OnlyEnforceIf(satisfied.Not())
            objective_terms.append(weight * satisfied)

    def compile_locked(c: Constraint):
        sid = c.args["student"]
        cls = c.args["class_index"]
        if sid not in student_set:
            return
        if c.hard:
            lit = enable_lit(c)
            model.Add(x[sid, cls] == 1).OnlyEnforceIf(lit)
        else:
            weight = c.args.get("weight", 2.0)
            objective_terms.append(weight * x[sid, cls])

    def compile_friendship_objective(c: Constraint):
        weight_mutual = c.args.get("weight_mutual", 5.0)
        weight_two_friends = c.args.get("weight_two_friends", 3.0)
        for sid in students:
            requested = [r for r in friendship_matched.get(sid, []) if r in student_set and r != sid]
            if not requested:
                continue
            mutuals = [r for r in requested if sid in friendship_matched.get(r, [])]
            if mutuals and weight_mutual > 0:
                co_vars = [get_same_class_var(sid, m) for m in mutuals]
                hm = model.NewBoolVar(f"has_mutual_{sid}")
                model.Add(sum(co_vars) >= 1).OnlyEnforceIf(hm)
                model.Add(sum(co_vars) == 0).OnlyEnforceIf(hm.Not())
                objective_terms.append(weight_mutual * hm)
            if requested and weight_two_friends > 0:
                co_vars_all = [get_same_class_var(sid, r) for r in requested]
                cnt = model.NewIntVar(0, len(co_vars_all), f"friend_cnt_{sid}")
                model.Add(cnt == sum(co_vars_all))
                tf = model.NewBoolVar(f"two_friends_{sid}")
                model.Add(cnt >= 2).OnlyEnforceIf(tf)
                model.Add(cnt <= 1).OnlyEnforceIf(tf.Not())
                objective_terms.append(weight_two_friends * tf)

    COMPILERS = {
        "capacity": compile_capacity,
        "balance": compile_balance,
        "separate": compile_separate,
        "together": compile_together,
        "at_least_one_of": compile_at_least_one_of,
        "locked": compile_locked,
        "friendship_objective": compile_friendship_objective,
    }

    for c in active:
        compiler = COMPILERS.get(c.type)
        if compiler is None:
            raise OptimizationError(f"סוג מגבלה לא מוכר: {c.type}")
        compiler(c)

    if assumption_lits:
        model.AddAssumptions(assumption_lits)

    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_seconds
    # Pinned to a single worker: CP-SAT's parallel portfolio search is
    # inherently non-deterministic across separate solve() calls (workers
    # race and whichever finds/improves a solution first wins), even with a
    # fixed random_seed. The app's spec requires that identical inputs
    # (same data + same constraints, including seed) always produce the
    # exact same solution. Do not raise this above 1 without also fixing
    # reproducibility some other way (e.g. deterministic tie-breaking).
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.random_seed

    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    assignment: dict[int, int] = {}
    notes: list[str] = []
    conflicting_ids: list[str] = []
    is_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if is_feasible:
        for sid in students:
            for c in range(k):
                if solver.Value(x[sid, c]) == 1:
                    assignment[sid] = c
                    break
    else:
        if status == cp_model.INFEASIBLE and assumption_lits:
            try:
                conflicting_var_indices = solver.SufficientAssumptionsForInfeasibility()
                conflicting_ids = [
                    constraint_id_by_var_index[i]
                    for i in conflicting_var_indices
                    if i in constraint_id_by_var_index
                ]
            except Exception:
                conflicting_ids = []
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
        conflicting_constraint_ids=conflicting_ids,
    )
