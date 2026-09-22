"""Independent verification and decision-support portfolio generation.

Nothing in this module trusts CP-SAT's status.  An assignment is valid only
when this evaluator can account for every student and every active hard rule.
The same evaluator is used for solver output, manual edits, and relaxed
what-if candidates.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from itertools import permutations
from typing import Any, Optional

import pandas as pd

from src.column_mapping import FIELD_STUDENT_ID
from src.constraints import Constraint, resolve_group_members
from src.metrics import academic_level_spread, compute_global_metrics
from src.optimizer import OptimizationResult, SolverConfig, optimize


@dataclass
class RuleCheck:
    constraint_id: str
    label: str
    rule_type: str
    hard: bool
    status: str  # satisfied | violated | not_applicable
    summary: str
    expected: Any = None
    actual: Any = None
    affected_students: list[int] = field(default_factory=list)
    affected_groups: list[int | str] = field(default_factory=list)


@dataclass
class VerificationReport:
    is_valid: bool
    summary: str
    students_expected: int
    students_assigned: int
    hard_rules_satisfied: int
    hard_rules_violated: int
    soft_rules_satisfied: int
    soft_rules_violated: int
    checks: list[RuleCheck]

    def to_dict(self) -> dict:
        return {**asdict(self), "checks": [asdict(check) for check in self.checks]}


@dataclass
class CandidateOption:
    id: str
    title: str
    strategy: str
    assignment: dict[int, int]
    verification: VerificationReport
    metrics: dict
    compromises: list[str]
    relaxed_constraint_ids: list[str]
    objective_value: Optional[float]
    wall_time_seconds: float
    differs_from_first: int = 0

    def to_dict(self, include_assignment: bool = False) -> dict:
        payload = asdict(self)
        payload["verification"] = self.verification.to_dict()
        if not include_assignment:
            payload.pop("assignment", None)
        return payload


def _subgroups(df: pd.DataFrame, group: dict) -> list[dict]:
    if group.get("kind") == "field_all_values":
        field = group["field"]
        return [{"kind": "field_value", "field": field, "value": value} for value in df[field].dropna().unique()]
    if group.get("kind") == "fields":
        return [{"kind": "field", "field": name} for name in group.get("fields", [])]
    return [group]


def verify_assignment(
    df: pd.DataFrame,
    assignment: dict[int, int],
    constraints: list[Constraint],
    num_classes: int,
    friendship_matched: Optional[dict[int, list[int]]] = None,
) -> VerificationReport:
    """Evaluate all active rules without using optimizer internals or status."""
    friendship_matched = friendship_matched or {}
    expected_students = [int(value) for value in df[FIELD_STUDENT_ID].tolist()]
    expected_set = set(expected_students)
    assigned_set = set(assignment)
    checks: list[RuleCheck] = []

    missing = sorted(expected_set - assigned_set)
    unknown = sorted(assigned_set - expected_set)
    out_of_range = sorted(student for student, cls in assignment.items() if not isinstance(cls, int) or not 0 <= cls < num_classes)
    structural_ok = not missing and not unknown and not out_of_range and num_classes > 0
    details = []
    if missing:
        details.append(f"{len(missing)} students are unassigned")
    if unknown:
        details.append(f"{len(unknown)} unknown students are assigned")
    if out_of_range:
        details.append(f"{len(out_of_range)} assignments use a nonexistent group")
    checks.append(RuleCheck(
        constraint_id="assignment_integrity", label="Complete assignment", rule_type="integrity", hard=True,
        status="satisfied" if structural_ok else "violated",
        summary="Every student is assigned exactly once to an available group." if structural_ok else "; ".join(details),
        expected={"students": len(expected_set), "groups": num_classes}, actual={"assigned": len(assigned_set)},
        affected_students=missing + unknown + out_of_range,
    ))

    class_members = [{sid for sid, cls in assignment.items() if cls == index} for index in range(max(0, num_classes))]

    def add(con: Constraint, ok: bool, summary: str, *, expected=None, actual=None, students=None, groups=None, na=False):
        checks.append(RuleCheck(
            constraint_id=con.id, label=con.label_hebrew, rule_type=con.type, hard=con.hard,
            status="not_applicable" if na else ("satisfied" if ok else "violated"), summary=summary,
            expected=expected, actual=actual, affected_students=sorted(set(students or [])), affected_groups=list(groups or []),
        ))

    for con in constraints:
        if not con.active:
            continue
        args = con.args
        if con.type == "capacity":
            members = set(resolve_group_members(df, args["group"]))
            counts = [len(members & group_members) for group_members in class_members]
            lo, hi = args.get("min"), args.get("max")
            bad = [index for index, count in enumerate(counts) if (lo is not None and count < lo) or (hi is not None and count > hi)]
            add(con, not bad, "All groups are within the required range." if not bad else f"{len(bad)} groups are outside the required range.",
                expected={"min": lo, "max": hi}, actual=counts,
                students=[sid for index in bad for sid in class_members[index] & members], groups=[index + 1 for index in bad])
        elif con.type in ("separate", "together"):
            first, second = args["student_a"], args["student_b"]
            applicable = first in expected_set and second in expected_set and first in assignment and second in assignment
            same = applicable and assignment[first] == assignment[second]
            ok = (not same) if con.type == "separate" else same
            add(con, ok, "The student pair satisfies the rule." if ok else "The student pair does not satisfy the rule.",
                expected="different groups" if con.type == "separate" else "same group",
                actual=[assignment.get(first), assignment.get(second)], students=[first, second], na=not applicable)
        elif con.type == "at_least_one_of":
            student = args["student"]
            candidates = [sid for sid in args.get("candidates", []) if sid in expected_set and sid != student]
            applicable = student in assignment and bool(candidates)
            colocated = [sid for sid in candidates if assignment.get(sid) == assignment.get(student)]
            add(con, bool(colocated), "At least one requested student is in the same group." if colocated else "No listed student is in the same group.",
                expected="at least 1", actual=len(colocated), students=[student] + candidates, na=not applicable)
        elif con.type == "locked":
            student, target = args["student"], args["class_index"]
            applicable = student in expected_set and student in assignment
            ok = applicable and assignment[student] == target
            add(con, ok, "The fixed placement was preserved." if ok else "The student is not in the fixed group.",
                expected=target + 1, actual=(assignment.get(student) + 1) if student in assignment else None, students=[student], na=not applicable)
        elif con.type == "balance":
            spreads, affected = [], []
            for subgroup in _subgroups(df, args["group"]):
                members = set(resolve_group_members(df, subgroup))
                counts = [len(members & group_members) for group_members in class_members]
                if counts:
                    spread = max(counts) - min(counts)
                    spreads.append(spread)
                    if spread:
                        affected.extend(index + 1 for index, count in enumerate(counts) if count in (min(counts), max(counts)))
            actual = max(spreads, default=0)
            add(con, actual == 0, "The selected population is evenly balanced." if actual == 0 else f"The largest group gap is {actual}.",
                expected="spread 0", actual=actual, groups=sorted(set(affected)))
        elif con.type == "friendship_objective":
            relevant = [sid for sid in expected_students if friendship_matched.get(sid)]
            mutual_hits = 0
            two_hits = 0
            unmet = []
            for sid in relevant:
                requested = [other for other in friendship_matched.get(sid, []) if other in expected_set and other != sid]
                same = [other for other in requested if assignment.get(other) == assignment.get(sid)]
                mutual = [other for other in same if sid in friendship_matched.get(other, [])]
                mutual_hits += bool(mutual)
                two_hits += len(same) >= 2
                if not mutual and len(same) < min(2, len(requested)):
                    unmet.append(sid)
            if not relevant:
                add(con, True, "No friendship requests were supplied; this rule was not scored.", actual={"students_with_requests": 0}, na=True)
            else:
                # A preference is marked satisfied when every applicable
                # student gets the benefits the objective can award.
                ok = not unmet
                add(con, ok, "All applicable friendship preferences were met." if ok else f"{len(unmet)} students have an unmet friendship preference.",
                    expected={"mutual": len(relevant), "two_friends": len(relevant)}, actual={"mutual": mutual_hits, "two_friends": two_hits}, students=unmet)
        else:
            add(con, False, f"Rule type '{con.type}' has no independent verifier.")

    hard_bad = sum(check.hard and check.status == "violated" for check in checks)
    hard_ok = sum(check.hard and check.status == "satisfied" for check in checks)
    soft_bad = sum(not check.hard and check.status == "violated" for check in checks)
    soft_ok = sum(not check.hard and check.status == "satisfied" for check in checks)
    valid = hard_bad == 0
    summary = (
        f"Valid assignment: all {hard_ok} mandatory checks passed."
        if valid else f"Invalid assignment: {hard_bad} mandatory checks failed; {hard_ok} passed."
    )
    return VerificationReport(valid, summary, len(expected_set), len(expected_set & assigned_set), hard_ok, hard_bad, soft_ok, soft_bad, checks)


def assignment_distance(first: dict[int, int], second: dict[int, int], num_classes: int) -> int:
    """Minimum moved students after accounting for arbitrary group labels."""
    students = sorted(set(first) & set(second))
    if num_classes <= 8:
        best_same = 0
        for mapping in permutations(range(num_classes)):
            best_same = max(best_same, sum(mapping[first[sid]] == second[sid] for sid in students))
        return len(students) - best_same + len(set(first) ^ set(second))
    # Greedy fallback avoids factorial work for unusually large group counts.
    pairs = sorted(((sum(first.get(sid) == a and second.get(sid) == b for sid in students), a, b)
                    for a in range(num_classes) for b in range(num_classes)), reverse=True)
    used_a, used_b, same = set(), set(), 0
    for count, a, b in pairs:
        if a not in used_a and b not in used_b:
            used_a.add(a); used_b.add(b); same += count
    return len(students) - same + len(set(first) ^ set(second))


def profile_constraints(constraints: list[Constraint], strategy: str) -> list[Constraint]:
    result = deepcopy(constraints)
    for con in result:
        if con.hard:
            continue
        if strategy == "preferences":
            if con.type == "friendship_objective":
                con.args["weight_mutual"] = float(con.args.get("weight_mutual", 5)) * 3
                con.args["weight_two_friends"] = float(con.args.get("weight_two_friends", 3)) * 3
            elif con.type == "balance":
                con.args["weight"] = float(con.args.get("weight", 1)) * .35
        elif strategy == "balance":
            if con.type == "balance":
                con.args["weight"] = float(con.args.get("weight", 1)) * 4
            elif con.type == "friendship_objective":
                con.args["weight_mutual"] = float(con.args.get("weight_mutual", 5)) * .4
                con.args["weight_two_friends"] = float(con.args.get("weight_two_friends", 3)) * .4
    return result


def _candidate(option_id: str, title: str, strategy: str, result: OptimizationResult, df, original_constraints,
               cfg, friendships, relaxed_ids, first_assignment=None) -> CandidateOption:
    report = verify_assignment(df, result.assignment, original_constraints, cfg.num_classes, friendships)
    metrics = asdict(compute_global_metrics(df, result.assignment, friendships, original_constraints, cfg.num_classes,
                                            cfg.denominator_all_students, result.status_name, result.wall_time_seconds,
                                            result.objective_value))
    compromises = [check.summary for check in report.checks if check.status == "violated"]
    return CandidateOption(option_id, title, strategy, result.assignment, report, metrics, compromises, relaxed_ids,
                           result.objective_value, result.wall_time_seconds,
                           assignment_distance(first_assignment, result.assignment, cfg.num_classes) if first_assignment else 0)


def generate_portfolio(df: pd.DataFrame, config: SolverConfig, constraints: list[Constraint],
                       friendship_matched: Optional[dict[int, list[int]]] = None,
                       max_options: int = 4) -> tuple[list[CandidateOption], list[str]]:
    """Generate distinct valid options, or measured one-rule compromises."""
    friendships = friendship_matched or {}
    options: list[CandidateOption] = []
    conflicts: list[str] = []
    profiles = [("balanced", "Option A — balanced priorities"),
                ("preferences", "Option B — student preferences"),
                ("balance", "Option C — group balance")]
    excluded: list[dict[int, int]] = []
    for strategy, title in profiles:
        cfg = deepcopy(config)
        cfg.random_seed += len(options)
        result = optimize(df, cfg, profile_constraints(constraints, strategy), friendships,
                          excluded_assignments=excluded, min_assignment_distance=max(1, len(df) // 20))
        if not result.is_feasible:
            conflicts = list(dict.fromkeys(conflicts + result.conflicting_constraint_ids))
            continue
        if any(assignment_distance(existing.assignment, result.assignment, cfg.num_classes) == 0 for existing in options):
            continue
        option = _candidate(f"option-{len(options) + 1}", title, strategy, result, df, constraints, cfg, friendships, [],
                            options[0].assignment if options else None)
        options.append(option)
        excluded.append(result.assignment)
        if len(options) >= max_options:
            break

    if options:
        return options, conflicts

    # No perfect solution: test one explicit relaxation at a time.  Each
    # candidate is verified against the untouched original rules so its exact
    # compromise remains visible and it can never be mistaken for valid.
    hard_candidates = [con for con in constraints if con.active and con.hard and (not conflicts or con.id in conflicts)]
    for con in hard_candidates:
        trial_constraints = deepcopy(constraints)
        target = next(item for item in trial_constraints if item.id == con.id)
        target.hard = False
        target.args.setdefault("weight", 100.0)
        result = optimize(df, deepcopy(config), trial_constraints, friendships)
        if not result.is_feasible:
            continue
        option = _candidate(f"option-{len(options) + 1}", f"Option {chr(65 + len(options))} — relax {con.label_hebrew}",
                            "single_rule_compromise", result, df, constraints, config, friendships, [con.id],
                            options[0].assignment if options else None)
        options.append(option)
        if len(options) >= max_options:
            break
    return options, conflicts


def negotiation_question(options: list[CandidateOption]) -> Optional[dict]:
    if len(options) < 2:
        return None
    first, second = options[0], options[1]
    if first.verification.is_valid and second.verification.is_valid:
        return {
            "question": "Which matters more in this case: satisfying more student preferences or achieving tighter balance between groups?",
            "options": [first.id, second.id],
            "reason": "Both assignments satisfy every mandatory rule but optimize different secondary goals.",
        }
    return {
        "question": f"Would you rather accept the compromise in {first.title}, or the different compromise in {second.title}?",
        "options": [first.id, second.id],
        "reason": "No assignment satisfies all mandatory rules simultaneously; each option changes a different rule.",
    }
