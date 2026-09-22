import pandas as pd

from src.column_mapping import FIELD_STUDENT_ID
from src.constraints import Constraint
from src.decision_support import assignment_distance, generate_portfolio, verify_assignment
from src.optimizer import SolverConfig


def test_verifier_reports_every_rule_and_assignment_integrity_independently():
    df = pd.DataFrame({FIELD_STUDENT_ID: [1, 2, 3, 4], "support": [True, True, False, False]})
    constraints = [
        Constraint(type="capacity", hard=True, args={"group": {"kind": "all"}, "min": 2, "max": 2}, label_hebrew="group size"),
        Constraint(type="separate", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="separate"),
        Constraint(type="together", hard=False, args={"student_a": 3, "student_b": 4, "weight": 2}, label_hebrew="prefer together"),
        Constraint(type="balance", hard=False, args={"group": {"kind": "field", "field": "support"}, "weight": 1}, label_hebrew="balance support"),
    ]

    report = verify_assignment(df, {1: 0, 2: 0, 3: 1}, constraints, 2)

    assert report.is_valid is False
    assert report.hard_rules_violated == 3  # integrity, capacity, separation
    assert {check.constraint_id for check in report.checks} == {"assignment_integrity", *(c.id for c in constraints)}
    integrity = next(check for check in report.checks if check.constraint_id == "assignment_integrity")
    assert integrity.affected_students == [4]
    separation = next(check for check in report.checks if check.label == "separate")
    assert separation.affected_students == [1, 2]
    assert separation.affected_groups == []


def test_class_label_swaps_are_not_counted_as_meaningful_alternatives():
    first = {1: 0, 2: 0, 3: 1, 4: 1}
    relabeled = {1: 1, 2: 1, 3: 0, 4: 0}
    changed = {1: 0, 2: 1, 3: 0, 4: 1}

    assert assignment_distance(first, relabeled, 2) == 0
    assert assignment_distance(first, changed, 2) == 2


def test_impossible_case_yields_explicit_single_rule_compromises():
    df = pd.DataFrame({FIELD_STUDENT_ID: [1, 2, 3, 4]})
    together = Constraint(type="together", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="keep 1 and 2 together")
    separate = Constraint(type="separate", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="keep 1 and 2 separate")
    size = Constraint(type="capacity", hard=True, args={"group": {"kind": "all"}, "min": 2, "max": 2}, label_hebrew="two per group")

    options, conflicts = generate_portfolio(
        df,
        SolverConfig(num_classes=2, time_limit_seconds=5),
        [size, together, separate],
        max_options=4,
    )

    assert {together.id, separate.id}.issubset(set(conflicts))
    assert len(options) >= 2
    assert all(not option.verification.is_valid for option in options)
    assert all(len(option.relaxed_constraint_ids) == 1 for option in options)
    assert all(option.verification.hard_rules_violated == 1 for option in options)
    assert all(option.compromises for option in options)


def test_tight_capacity_portfolio_produces_distinct_verified_options():
    df = pd.DataFrame({FIELD_STUDENT_ID: list(range(1, 9)), "flag": [True, True, True, True, False, False, False, False]})
    constraints = [
        Constraint(type="capacity", hard=True, args={"group": {"kind": "all"}, "min": 4, "max": 4}, label_hebrew="exact size"),
        Constraint(type="balance", hard=False, args={"group": {"kind": "field", "field": "flag"}, "weight": 1}, label_hebrew="balance flag"),
        Constraint(type="together", hard=False, args={"student_a": 1, "student_b": 2, "weight": 3}, label_hebrew="prefer pair"),
    ]

    options, _ = generate_portfolio(df, SolverConfig(num_classes=2, time_limit_seconds=5), constraints, max_options=3)

    assert len(options) >= 2
    assert all(option.verification.is_valid for option in options)
    for index, option in enumerate(options):
        for other in options[index + 1:]:
            assert assignment_distance(option.assignment, other.assignment, 2) > 0
