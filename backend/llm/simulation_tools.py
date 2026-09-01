"""What-if tools: run the real solver on a hypothetical, throw the result away.

This is the half of the agent that does work rather than reading. The model
can take a question like "what if we tightened the class-size rule to 35-36"
and actually find out, instead of reasoning about it.

Three rules hold for everything in here:

1. **Nothing is ever applied.** The session's constraints, run config and
   assignment are deep-copied before anything is changed, and the result is
   discarded once the numbers are extracted. A simulation cannot alter what
   the counselor is looking at. Applying a change still goes through the
   normal propose -> confirm card.

2. **A short time budget.** A real run gets the full 60s; a simulation gets
   SIM_TIME_LIMIT. It is answering "roughly what happens", not producing the
   final assignment. Every payload carries a caveat saying so, because a
   short solve can land on a worse-but-valid answer and the model must not
   report that as the true cost of a change.

3. **Infeasible is a useful answer.** "Tightening that rule makes the
   problem impossible, and here is which rule it collides with" is exactly
   what a counselor needs to hear, so it is a normal result here, not an
   error.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import replace
from typing import Optional

from pydantic import BaseModel, Field

from src.column_mapping import FIELD_STUDENT_ID
from src.constraints import Constraint, capacity_range_label_hebrew, class_size_label_hebrew, resolve_group_members
from src.metrics import compute_global_metrics, violations_report
from src.optimizer import OptimizationError, optimize

from ..solver_inputs import build_locked_constraints, build_solver_inputs
from ..utils import df_records

logger = logging.getLogger(__name__)

# A trial run, not the real thing. Long enough on a ~220-student roster to
# show whether a change is feasible and roughly what it costs; short enough
# that an agent turn stays inside a conversational wait.
SIM_TIME_LIMIT = 10.0

CAVEAT = (
    f"Trial run only: solved with a {int(SIM_TIME_LIMIT)}s budget instead of the full one, and nothing was "
    "applied. Treat the numbers as indicative -- a full run may do slightly better. Report the direction "
    "and rough size of the effect, not these figures as final."
)


# ---------------------------------------------------------------- arg models

class SimulateCapacityChangeArgs(BaseModel):
    constraint_id: str = Field(description="id of the capacity rule to try changing, from get_active_rules")
    min: Optional[int] = Field(default=None, description="Proposed new minimum per class; omit to leave unchanged")
    max: Optional[int] = Field(default=None, description="Proposed new maximum per class; omit to leave unchanged")


class SimulateClassCountArgs(BaseModel):
    num_classes: int = Field(description="Proposed number of classes to try, e.g. 7")


class SimulateRuleToggleArgs(BaseModel):
    constraint_id: str = Field(description="id of the rule to try toggling, from get_active_rules")
    hard: Optional[bool] = Field(default=None, description="Try making the rule mandatory (true) or a preference (false)")
    active: Optional[bool] = Field(default=None, description="Try switching the rule off (false) or on (true)")


class SimulateFriendshipPriorityArgs(BaseModel):
    constraint_id: str = Field(description="id of the friendship objective from get_active_rules")
    weight_mutual: Optional[int] = Field(default=None, ge=0, description="Trial weight for at least one mutual friend")
    weight_two_friends: Optional[int] = Field(default=None, ge=0, description="Trial weight for at least two requested friends")


class SimulateBalancePriorityArgs(BaseModel):
    constraint_id: str = Field(description="id of an active balance preference from get_active_rules")
    weight: float = Field(gt=0, description="Trial importance for this balance preference")


class FindClassSizeBalanceMovesArgs(BaseModel):
    pass


class SimulateStudentMoveArgs(BaseModel):
    student: str = Field(description="Anonymized student token")
    class_number: int = Field(ge=1, description="Destination class number shown to the counselor, 1-based")


SIM_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "simulate_capacity_change": SimulateCapacityChangeArgs,
    "simulate_class_count": SimulateClassCountArgs,
    "simulate_rule_toggle": SimulateRuleToggleArgs,
    "simulate_friendship_priority": SimulateFriendshipPriorityArgs,
    "simulate_balance_priority": SimulateBalancePriorityArgs,
    "find_class_size_balance_moves": FindClassSizeBalanceMovesArgs,
    "simulate_student_move": SimulateStudentMoveArgs,
}

SIM_TOOL_DESCRIPTIONS: dict[str, str] = {
    "simulate_capacity_change": (
        "בדיקה בפועל: הרץ שיבוץ ניסיוני עם גבולות מין/מקס אחרים לחוק מכסה קיים (למשל להדק את גודל הכיתה), "
        "וקבל השוואה למצב הנוכחי. לא מחיל כלום."
    ),
    "simulate_class_count": "בדיקה בפועל: הרץ שיבוץ ניסיוני עם מספר כיתות אחר וקבל השוואה למצב הנוכחי. לא מחיל כלום.",
    "simulate_rule_toggle": (
        "בדיקה בפועל: הרץ שיבוץ ניסיוני כשחוק קיים הופך לחובה/העדפה או מכובה, וקבל השוואה למצב הנוכחי. לא מחיל כלום."
    ),
    "simulate_friendship_priority": (
        "בדיקה בפועל: הרץ שיבוץ ניסיוני עם עדיפות אחרת לבקשה הדדית או ללפחות שתי חברות, "
        "והשווה למצב הנוכחי. לא מחיל שום שינוי."
    ),
    "simulate_balance_priority": (
        "Run a real trial assignment with a different weight for one active balance preference, such as academic "
        "level or source-school balance. Returns the measured targeted spread and the trade-offs against the current "
        "assignment. Nothing is applied."
    ),
    "find_class_size_balance_moves": (
        "Exhaustively evaluate direct one-student moves from the largest class to the smallest class. Returns the "
        "best measured candidates that preserve every mandatory rule, with exact friendship and academic before/after "
        "effects. Nothing is applied. Use this when the counselor wants a specific correction, not only a rule change."
    ),
    "simulate_student_move": (
        "Test moving one student to a requested class without changing the assignment. Reports exact new mandatory-rule "
        "violations and measured friendship/academic effects. If the direct move is blocked, also searches for safe "
        "one-for-one swaps with that class. Use for questions such as 'what happens if I move Maya to class 4?'."
    ),
}


def build_simulation_tool_definitions() -> list[dict]:
    tools = []
    for name, model in SIM_TOOL_MODELS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("properties", {})
        tools.append(
            {"type": "function", "function": {"name": name, "description": SIM_TOOL_DESCRIPTIONS[name], "parameters": schema}}
        )
    return tools


# ------------------------------------------------------------------ helpers

def _snapshot(df, assignment, matched, constraints, cfg) -> dict:
    """The handful of figures worth comparing across a what-if."""
    gm = compute_global_metrics(df, assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students)
    return {
        "class_sizes": list(gm.class_sizes),
        "size_spread": gm.class_size_spread,
        "academic_spread": gm.academic_level_spread,
        "violations": gm.violations_count,
        "friendship_available": gm.students_with_requests > 0,
        "students_with_requests": gm.students_with_requests,
        "mutual_pct": gm.mutual_satisfied_pct,
        "two_friends_pct": gm.two_friends_satisfied_pct,
    }


def _balance_diagnostic(df, assignment, num_classes: int, constraint: Constraint) -> dict:
    """Measure the exact dimensions represented by one balance objective."""
    group = constraint.args.get("group", {})
    dimensions: list[tuple[str, set]] = []
    kind = group.get("kind")
    if kind == "field_all_values":
        field = group.get("field")
        if field in df.columns:
            for value in df[field].dropna().unique().tolist():
                if str(value).strip():
                    ids = set(df.loc[df[field] == value, FIELD_STUDENT_ID].tolist())
                    dimensions.append((str(value), ids))
    elif kind == "fields":
        for field in group.get("fields", []):
            if field in df.columns:
                dimensions.append((str(field), set(resolve_group_members(df, {"kind": "field", "field": field}))))
    elif kind in {"field", "field_value", "members", "all"}:
        try:
            dimensions.append((constraint.label_hebrew, set(resolve_group_members(df, group))))
        except Exception:
            pass

    measured = []
    for label, members in dimensions:
        counts = [sum(1 for sid in members if assignment.get(sid) == cls) for cls in range(num_classes)]
        measured.append({"dimension": label, "counts_by_class": counts, "spread": max(counts) - min(counts) if counts else 0})
    measured.sort(key=lambda item: item["spread"], reverse=True)
    return {
        "constraint_id": constraint.id,
        "label_hebrew": constraint.label_hebrew,
        "weight": constraint.args.get("weight"),
        "total_spread": sum(item["spread"] for item in measured),
        "worst_dimensions": measured[:8],
    }


def _baseline(sess, constraints, cfg) -> Optional[dict]:
    if sess.adjustment_state is None or sess.opt_result is None or not sess.opt_result.is_feasible:
        return None
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    gm = compute_global_metrics(
        sess.mapped_df, sess.adjustment_state.assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students
    )
    return {
        "class_sizes": list(gm.class_sizes),
        "size_spread": gm.class_size_spread,
        "academic_spread": gm.academic_level_spread,
        "violations": gm.violations_count,
        "friendship_available": gm.students_with_requests > 0,
        "students_with_requests": gm.students_with_requests,
        "mutual_pct": gm.mutual_satisfied_pct,
        "two_friends_pct": gm.two_friends_satisfied_pct,
    }


def _counting_impossibility(df, constraints: list[Constraint], k: int) -> Optional[str]:
    """Catch changes that fail on arithmetic, before spending 10s proving it.

    CP-SAT reports infeasibility as an assumption set, which for this model
    is "all the capacity rules" -- true but useless, and the model dutifully
    reads the whole list out to the counselor. Most impossible what-ifs here
    are actually one multiplication: 6 classes capped at 36 hold 216 seats
    and there are 217 students. Saying *that* is the difference between a
    real answer and a shrug.
    """
    for c in constraints:
        if c.type != "capacity" or not (c.hard and c.active):
            continue
        group = c.args.get("group", {})
        try:
            available = len(df) if group.get("kind") == "all" else len(resolve_group_members(df, group))
        except Exception:
            continue
        lo, hi = c.args.get("min"), c.args.get("max")
        who = "תלמידות" if group.get("kind") == "all" else f'תלמידות בקבוצה "{c.label_hebrew}"'
        if hi is not None and hi * k < available:
            return (
                f"Arithmetic: the rule '{c.label_hebrew}' caps each class at {hi}, so {k} classes hold at most "
                f"{hi * k} {who} -- but {available} must be placed. Impossible regardless of anything else."
            )
        if lo is not None and lo * k > available:
            return (
                f"Arithmetic: the rule '{c.label_hebrew}' requires at least {lo} per class, so {k} classes need "
                f"{lo * k} {who} -- but only {available} exist. Impossible regardless of anything else."
            )
    return None


def _run(
    sess,
    constraints: list[Constraint],
    cfg,
    change_description: str,
    diagnostic_constraint: Optional[Constraint] = None,
) -> dict:
    """Solve a hypothetical and report it against the current result."""
    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    sim_cfg = replace(cfg, time_limit_seconds=SIM_TIME_LIMIT)

    reason = _counting_impossibility(df, constraints, sim_cfg.num_classes)
    if reason is not None:
        return {
            "change": change_description,
            "feasible": False,
            "solver_status": "INFEASIBLE_BY_COUNTING",
            "detail": reason,
            "caveat": "No solve was needed -- this fails on the numbers alone.",
        }

    try:
        result = optimize(df, sim_cfg, constraints, friendship_matched=matched)
    except OptimizationError as e:
        return {"change": change_description, "error": "solver_error", "detail": str(e), "caveat": CAVEAT}

    if not result.is_feasible:
        conflicting = [c.label_hebrew for c in constraints if c.id in (result.conflicting_constraint_ids or [])]
        return {
            "change": change_description,
            "feasible": False,
            "solver_status": result.status_name,
            "conflicting_rules": conflicting,
            "detail": "This change makes the problem unsolvable -- no assignment satisfies all mandatory rules.",
            "caveat": CAVEAT,
        }

    _cfg_now, current_constraints = build_solver_inputs(sess)
    before = _baseline(sess, current_constraints, _cfg_now)
    after = _snapshot(df, result.assignment, matched, constraints, sim_cfg)

    out = {
        "change": change_description,
        "feasible": True,
        "solver_status": result.status_name,
        "after": after,
        "caveat": CAVEAT,
    }
    if before is not None:
        out["before"] = before
        out["deltas"] = {
            "size_spread": after["size_spread"] - before["size_spread"],
            "academic_spread": after["academic_spread"] - before["academic_spread"],
            "violations": after["violations"] - before["violations"],
            "mutual_pct": round(after["mutual_pct"] - before["mutual_pct"], 1),
            "two_friends_pct": round(after["two_friends_pct"] - before["two_friends_pct"], 1),
        }
        if diagnostic_constraint is not None:
            current_target = next(
                (c for c in current_constraints if c.id == diagnostic_constraint.id),
                diagnostic_constraint,
            )
            out["targeted_balance"] = {
                "before": _balance_diagnostic(df, sess.adjustment_state.assignment, _cfg_now.num_classes, current_target),
                "after": _balance_diagnostic(df, result.assignment, sim_cfg.num_classes, diagnostic_constraint),
            }
    else:
        out["note"] = "No current result to compare against; these are the figures the change would produce."
    return out


def _prepared(sess) -> tuple:
    """Deep-copied constraints + config, plus locks, so a simulation can
    never write through to the session."""
    cfg, constraints = build_solver_inputs(sess)
    sim_constraints = copy.deepcopy(list(constraints)) + build_locked_constraints(sess)
    return cfg, sim_constraints


def _relabel(c: Constraint) -> None:
    """Keep a capacity rule's Hebrew label in step with bounds we just
    changed. The label is not decoration here -- it is what comes back in
    `conflicting_rules` and what the model quotes to the counselor, so a
    stale one means confidently reporting the wrong numbers."""
    lo, hi = c.args.get("min"), c.args.get("max")
    group = c.args.get("group", {})
    if group.get("kind") == "all":
        c.label_hebrew = class_size_label_hebrew(lo, hi)
    elif group.get("kind") == "field":
        c.label_hebrew = capacity_range_label_hebrew(group.get("field"), lo, hi)


# -------------------------------------------------------------- tool bodies

def _simulate_capacity_change(sess, args: SimulateCapacityChangeArgs) -> dict:
    cfg, constraints = _prepared(sess)
    target = next((c for c in constraints if c.id == args.constraint_id), None)
    if target is None:
        return {"error": "unknown_constraint", "detail": "No active rule with that id; call get_active_rules first."}
    if target.type != "capacity":
        return {"error": "not_a_capacity_rule", "detail": f"Rule {args.constraint_id} is of type {target.type}."}
    if args.min is None and args.max is None:
        return {"error": "bad_arguments", "detail": "Provide at least one of min or max."}

    old_label = target.label_hebrew
    old_min, old_max = target.args.get("min"), target.args.get("max")
    if args.min is not None:
        target.args["min"] = args.min
    if args.max is not None:
        target.args["max"] = args.max
    new_min, new_max = target.args.get("min"), target.args.get("max")
    if new_min is not None and new_max is not None and new_min > new_max:
        return {"error": "bad_arguments", "detail": f"min ({new_min}) cannot exceed max ({new_max})."}
    _relabel(target)

    desc = f'"{old_label}": {old_min}-{old_max} -> {new_min}-{new_max}'
    return _run(sess, constraints, cfg, desc)


def _simulate_class_count(sess, args: SimulateClassCountArgs) -> dict:
    cfg, constraints = _prepared(sess)
    if not 2 <= args.num_classes <= 20:
        return {"error": "bad_arguments", "detail": "num_classes must be between 2 and 20."}

    sim_cfg = replace(cfg, num_classes=args.num_classes)
    # The overall class-size rule's bounds are derived from roster size and
    # class count, so leaving them at the old numbers would make this
    # measure the wrong thing -- it would look infeasible for a reason the
    # counselor never asked about. Recompute them the same way
    # solver_inputs.sync_class_size_bounds does for a real change.
    n, k = len(sess.mapped_df), args.num_classes
    for c in constraints:
        if c.type == "capacity" and c.args.get("group", {}).get("kind") == "all":
            diff = c.args.get("size_diff", 1)
            c.args["max"] = -(-n // k) + diff
            c.args["min"] = max(0, (n // k) - diff)
            _relabel(c)

    # Per-category minimums do NOT get rescaled, on purpose. If "3 Ethiopian-
    # origin students per class" times the new class count exceeds how many
    # there are, that is the real reason the change is impossible and the
    # counselor needs to hear it -- quietly relaxing the minimum to make the
    # trial succeed would answer a question nobody asked.
    desc = f"number of classes: {cfg.num_classes} -> {args.num_classes}"
    return _run(sess, constraints, sim_cfg, desc)


def _simulate_rule_toggle(sess, args: SimulateRuleToggleArgs) -> dict:
    cfg, constraints = _prepared(sess)
    target = next((c for c in constraints if c.id == args.constraint_id), None)
    if target is None:
        return {"error": "unknown_constraint", "detail": "No rule with that id; call get_active_rules first."}
    if args.hard is None and args.active is None:
        return {"error": "bad_arguments", "detail": "Provide at least one of hard or active."}

    parts = []
    if args.hard is not None and args.hard != target.hard:
        parts.append("mandatory" if args.hard else "preference")
        target.hard = args.hard
    if args.active is not None and args.active != target.active:
        parts.append("on" if args.active else "off")
        target.active = args.active
    if not parts:
        return {"error": "no_change", "detail": "The rule is already in that state."}

    desc = f'"{target.label_hebrew}" -> {", ".join(parts)}'
    return _run(sess, constraints, cfg, desc)


def _simulate_friendship_priority(sess, args: SimulateFriendshipPriorityArgs) -> dict:
    cfg, constraints = _prepared(sess)
    target = next((c for c in constraints if c.id == args.constraint_id), None)
    if target is None:
        return {"error": "unknown_constraint", "detail": "No active rule with that id; call get_active_rules first."}
    if target.type != "friendship_objective":
        return {"error": "not_friendship_objective", "detail": f"Rule {args.constraint_id} is of type {target.type}."}
    if args.weight_mutual is None and args.weight_two_friends is None:
        return {"error": "bad_arguments", "detail": "Provide at least one friendship weight."}

    old_mutual = int(target.args.get("weight_mutual", 0))
    old_two = int(target.args.get("weight_two_friends", 0))
    new_mutual = old_mutual if args.weight_mutual is None else args.weight_mutual
    new_two = old_two if args.weight_two_friends is None else args.weight_two_friends
    if new_mutual == old_mutual and new_two == old_two:
        return {"error": "no_change", "detail": "The friendship priorities already have those values."}
    target.args["weight_mutual"] = new_mutual
    target.args["weight_two_friends"] = new_two
    desc = f"friendship priorities: mutual {old_mutual}->{new_mutual}, two friends {old_two}->{new_two}"
    return _run(sess, constraints, cfg, desc)


def _simulate_balance_priority(sess, args: SimulateBalancePriorityArgs) -> dict:
    cfg, constraints = _prepared(sess)
    target = next((c for c in constraints if c.id == args.constraint_id), None)
    if target is None:
        return {"error": "unknown_constraint", "detail": "No active rule with that id; call get_active_rules first."}
    if target.type != "balance":
        return {"error": "not_balance_objective", "detail": f"Rule {args.constraint_id} is of type {target.type}."}
    old_weight = float(target.args.get("weight", 1))
    if float(args.weight) == old_weight:
        return {"error": "no_change", "detail": "The balance preference already has that weight."}
    target.args["weight"] = float(args.weight)
    desc = f'priority of "{target.label_hebrew}": {old_weight:g}->{float(args.weight):g}'
    return _run(sess, constraints, cfg, desc, diagnostic_constraint=target)


def _find_class_size_balance_moves(sess, _args: FindClassSizeBalanceMovesArgs) -> dict:
    """Find specific, safe single moves that close the current size gap."""
    if sess.adjustment_state is None or sess.opt_result is None or not sess.opt_result.is_feasible:
        return {"error": "no_assignment_yet", "detail": "A current assignment is required."}
    cfg, constraints = _prepared(sess)
    assignment = sess.adjustment_state.assignment
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    before = _snapshot(sess.mapped_df, assignment, matched, constraints, cfg)
    sizes = before["class_sizes"]
    if not sizes or max(sizes) == min(sizes):
        return {"already_balanced": True, "before": before, "candidates": []}

    largest = {index for index, size in enumerate(sizes) if size == max(sizes)}
    smallest = {index for index, size in enumerate(sizes) if size == min(sizes)}
    candidates = []
    checked = 0
    for student_id, source_class in assignment.items():
        if source_class not in largest or student_id in (sess.locked_assignment or {}):
            continue
        for target_class in smallest:
            checked += 1
            candidate_assignment = dict(assignment)
            candidate_assignment[student_id] = target_class
            after = _snapshot(sess.mapped_df, candidate_assignment, matched, constraints, cfg)
            if after["violations"] != 0 or after["size_spread"] >= before["size_spread"]:
                continue
            candidates.append(
                {
                    "student": sess.token_map.token_for(student_id),
                    "from_class": source_class + 1,
                    "to_class": target_class + 1,
                    "after": after,
                    "deltas": {
                        "size_spread": after["size_spread"] - before["size_spread"],
                        "academic_spread": (
                            after["academic_spread"] - before["academic_spread"]
                            if after["academic_spread"] is not None and before["academic_spread"] is not None
                            else None
                        ),
                        "mutual_pct": round(after["mutual_pct"] - before["mutual_pct"], 1),
                        "two_friends_pct": round(after["two_friends_pct"] - before["two_friends_pct"], 1),
                    },
                }
            )

    def rank(item):
        delta = item["deltas"]
        academic = delta["academic_spread"] if delta["academic_spread"] is not None else 0
        return (
            item["after"]["size_spread"],
            academic,
            -delta["mutual_pct"],
            -delta["two_friends_pct"],
            item["student"],
        )

    candidates.sort(key=rank)
    return {
        "before": before,
        "largest_classes": [index + 1 for index in sorted(largest)],
        "smallest_classes": [index + 1 for index in sorted(smallest)],
        "checked_direct_moves": checked,
        "safe_direct_moves_found": len(candidates),
        "candidates": candidates[:5],
        "method": (
            "Every unlocked student in a largest class was tested in every smallest class. Candidates shown create "
            "no mandatory-rule violation and are ranked by resulting size spread, academic spread, then friendship."
        ),
        "causality_limit": (
            "These are measured correction options, not an explanation of why the original solver selected its exact assignment."
        ),
    }


def _student_social_snapshot(student_id, assignment, matched) -> dict:
    class_index = assignment.get(student_id)
    requested = [other for other in matched.get(student_id, []) if other != student_id]
    together = [other for other in requested if assignment.get(other) == class_index]
    mutual = [other for other in together if student_id in matched.get(other, [])]
    return {
        "class": class_index + 1 if class_index is not None else None,
        "requests_made": len(requested),
        "requested_friends_together": len(together),
        "mutual_friends_together": len(mutual),
    }


def _simulate_student_move(sess, args: SimulateStudentMoveArgs) -> dict:
    """Measure a direct move and, when useful, all compensating swaps."""
    if sess.adjustment_state is None or sess.opt_result is None or not sess.opt_result.is_feasible:
        return {"error": "no_assignment_yet", "detail": "A current assignment is required."}
    student_id = sess.token_map.id_for(args.student)
    if student_id is None or student_id not in sess.adjustment_state.assignment:
        return {"error": "unknown_student_token", "detail": "That student token is not part of the current assignment."}

    cfg, constraints = _prepared(sess)
    target_class = args.class_number - 1
    if target_class < 0 or target_class >= cfg.num_classes:
        return {"error": "bad_arguments", "detail": f"Class must be between 1 and {cfg.num_classes}."}

    assignment = sess.adjustment_state.assignment
    source_class = assignment[student_id]
    if source_class == target_class:
        return {"error": "no_change", "detail": "The student is already in that class."}
    if student_id in (sess.locked_assignment or {}):
        return {
            "error": "student_locked",
            "detail": "The student's current placement is manually locked. It must be explicitly unlocked before testing a move.",
        }

    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    before = _snapshot(df, assignment, matched, constraints, cfg)
    before_violation_rows = df_records(violations_report(df, assignment, constraints, cfg.num_classes))
    before_social = _student_social_snapshot(student_id, assignment, matched)

    direct_assignment = dict(assignment)
    direct_assignment[student_id] = target_class
    direct = _snapshot(df, direct_assignment, matched, constraints, cfg)
    direct_violation_rows = df_records(violations_report(df, direct_assignment, constraints, cfg.num_classes))
    direct_social = _student_social_snapshot(student_id, direct_assignment, matched)
    direct_result = {
        "preserves_all_mandatory_rules": direct["violations"] == 0,
        "after": direct,
        "student_outcome": direct_social,
        "student_outcome_deltas": {
            "requested_friends_together": direct_social["requested_friends_together"] - before_social["requested_friends_together"],
            "mutual_friends_together": direct_social["mutual_friends_together"] - before_social["mutual_friends_together"],
        },
        "global_deltas": {
            "size_spread": direct["size_spread"] - before["size_spread"],
            "academic_spread": (
                direct["academic_spread"] - before["academic_spread"]
                if direct["academic_spread"] is not None and before["academic_spread"] is not None
                else None
            ),
            "mutual_pct": round(direct["mutual_pct"] - before["mutual_pct"], 1),
            "two_friends_pct": round(direct["two_friends_pct"] - before["two_friends_pct"], 1),
        },
        "mandatory_violations_after": direct_violation_rows,
    }

    swap_candidates = []
    checked_swaps = 0
    for other_id, other_class in assignment.items():
        if other_class != target_class or other_id == student_id or other_id in (sess.locked_assignment or {}):
            continue
        checked_swaps += 1
        swapped = dict(assignment)
        swapped[student_id] = target_class
        swapped[other_id] = source_class
        after = _snapshot(df, swapped, matched, constraints, cfg)
        if after["violations"] != 0:
            continue
        student_after = _student_social_snapshot(student_id, swapped, matched)
        other_before = _student_social_snapshot(other_id, assignment, matched)
        other_after = _student_social_snapshot(other_id, swapped, matched)
        swap_candidates.append(
            {
                "swap_with": sess.token_map.token_for(other_id),
                "student_move": {"from_class": source_class + 1, "to_class": target_class + 1},
                "other_student_move": {"from_class": target_class + 1, "to_class": source_class + 1},
                "after": after,
                "global_deltas": {
                    "size_spread": after["size_spread"] - before["size_spread"],
                    "academic_spread": (
                        after["academic_spread"] - before["academic_spread"]
                        if after["academic_spread"] is not None and before["academic_spread"] is not None
                        else None
                    ),
                    "mutual_pct": round(after["mutual_pct"] - before["mutual_pct"], 1),
                    "two_friends_pct": round(after["two_friends_pct"] - before["two_friends_pct"], 1),
                },
                "requested_student_outcome": student_after,
                "requested_student_deltas": {
                    "requested_friends_together": student_after["requested_friends_together"] - before_social["requested_friends_together"],
                    "mutual_friends_together": student_after["mutual_friends_together"] - before_social["mutual_friends_together"],
                },
                "swap_partner_outcome": other_after,
                "swap_partner_deltas": {
                    "requested_friends_together": other_after["requested_friends_together"] - other_before["requested_friends_together"],
                    "mutual_friends_together": other_after["mutual_friends_together"] - other_before["mutual_friends_together"],
                },
            }
        )

    def swap_rank(item):
        global_delta = item["global_deltas"]
        requested_delta = item["requested_student_deltas"]
        partner_delta = item["swap_partner_deltas"]
        academic = global_delta["academic_spread"] if global_delta["academic_spread"] is not None else 0
        return (
            -requested_delta["mutual_friends_together"],
            -requested_delta["requested_friends_together"],
            -partner_delta["mutual_friends_together"],
            academic,
            -global_delta["mutual_pct"],
            item["swap_with"],
        )

    swap_candidates.sort(key=swap_rank)
    return {
        "student": args.student,
        "requested_move": {"from_class": source_class + 1, "to_class": target_class + 1},
        "before": before,
        "student_before": before_social,
        "mandatory_violations_before": before_violation_rows,
        "direct_move": direct_result,
        "compensating_swap_search": {
            "checked": checked_swaps,
            "safe_swaps_found": len(swap_candidates),
            "best_candidates": swap_candidates[:5],
        },
        "method": (
            "The direct move was measured with everyone else fixed. Every unlocked student in the destination class was then "
            "tested as a one-for-one swap; only swaps with zero mandatory-rule violations are shown."
        ),
        "causality_limit": "These are measured alternatives, not proof of why the solver chose the current placement.",
    }


_SIM_DISPATCH = {
    "simulate_capacity_change": _simulate_capacity_change,
    "simulate_class_count": _simulate_class_count,
    "simulate_rule_toggle": _simulate_rule_toggle,
    "simulate_friendship_priority": _simulate_friendship_priority,
    "simulate_balance_priority": _simulate_balance_priority,
    "find_class_size_balance_moves": _find_class_size_balance_moves,
    "simulate_student_move": _simulate_student_move,
}


def is_simulation_tool(name: str) -> bool:
    return name in _SIM_DISPATCH


def execute_simulation_tool(name: str, raw_args: dict, sess) -> dict:
    """Validate + run one what-if. Like the read tools, model mistakes come
    back as data rather than exceptions so the turn can recover."""
    model_cls = SIM_TOOL_MODELS.get(name)
    if model_cls is None:
        return {"error": "unknown_tool", "detail": name}
    if sess.mapped_df is None:
        return {"error": "no_roster", "detail": "No roster loaded, so nothing can be simulated."}
    try:
        args = model_cls(**(raw_args or {}))
    except Exception as e:
        return {"error": "bad_arguments", "detail": str(e)}
    try:
        return _SIM_DISPATCH[name](sess, args)
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("simulation tool %s failed", name)
        return {"error": "tool_failed", "detail": str(e)}
