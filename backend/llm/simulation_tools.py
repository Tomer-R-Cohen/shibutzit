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

from src.constraints import Constraint, capacity_range_label_hebrew, class_size_label_hebrew, resolve_group_members
from src.metrics import compute_global_metrics
from src.optimizer import OptimizationError, optimize

from ..solver_inputs import build_locked_constraints, build_solver_inputs

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


SIM_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "simulate_capacity_change": SimulateCapacityChangeArgs,
    "simulate_class_count": SimulateClassCountArgs,
    "simulate_rule_toggle": SimulateRuleToggleArgs,
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

def _snapshot(df, assignment, constraints, cfg) -> dict:
    """The handful of figures worth comparing across a what-if."""
    gm = compute_global_metrics(df, assignment, {}, constraints, cfg.num_classes, cfg.denominator_all_students)
    return {
        "class_sizes": list(gm.class_sizes),
        "size_spread": gm.class_size_spread,
        "violations": gm.violations_count,
        "mutual_pct": gm.mutual_satisfied_pct,
        "two_friends_pct": gm.two_friends_satisfied_pct,
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
        "violations": gm.violations_count,
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


def _run(sess, constraints: list[Constraint], cfg, change_description: str) -> dict:
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
    after = _snapshot(df, result.assignment, constraints, sim_cfg)

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
            "violations": after["violations"] - before["violations"],
            "mutual_pct": round(after["mutual_pct"] - before["mutual_pct"], 1),
            "two_friends_pct": round(after["two_friends_pct"] - before["two_friends_pct"], 1),
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


_SIM_DISPATCH = {
    "simulate_capacity_change": _simulate_capacity_change,
    "simulate_class_count": _simulate_class_count,
    "simulate_rule_toggle": _simulate_rule_toggle,
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
