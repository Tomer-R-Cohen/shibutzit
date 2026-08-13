import pandas as pd

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
from src.constraints import Constraint, default_constraints, locked_constraints
from src.optimizer import OptimizationError, SolverConfig, optimize


def make_df():
    levels = ["מצטיינת", "בינונית", "חלשה"]
    schools = ["בית ספר א", "בית ספר ב"]
    rows = []
    for i in range(1, 13):
        rows.append(
            {
                FIELD_STUDENT_ID: i,
                FIELD_ETHIOPIAN_ORIGIN: i <= 7,
                FIELD_DIFFERENTIAL: i in (1, 2),
                FIELD_INCLUSION: i in (3, 4, 5, 6),
                FIELD_HAMAR: i in (8, 9, 10),
                FIELD_ACADEMIC_LEVEL: levels[i % 3],
                FIELD_CURRENT_SCHOOL: schools[i % 2],
                FIELD_CURRENT_CLASS: i % 4,
            }
        )
    return pd.DataFrame(rows)


def base_config(num_classes=2):
    return SolverConfig(num_classes=num_classes, time_limit_seconds=15, random_seed=42)


def base_constraints(df, num_classes=2):
    return default_constraints(
        df,
        num_classes,
        max_class_size_diff=1,
        max_differential_per_class=1,
        min_ethiopian_per_class=3,
        max_ethiopian_per_class=4,
        min_inclusion_per_class=2,
        max_inclusion_per_class=2,
        min_hamar_per_class=1,
        max_hamar_per_class=2,
    )


def test_all_students_assigned_exactly_once():
    df = make_df()
    result = optimize(df, base_config(), base_constraints(df))
    assert result.is_feasible
    assert set(result.assignment.keys()) == set(df[FIELD_STUDENT_ID])
    assert all(0 <= c < 2 for c in result.assignment.values())


def test_class_size_balanced():
    df = make_df()
    result = optimize(df, base_config(), base_constraints(df))
    sizes = [0, 0]
    for c in result.assignment.values():
        sizes[c] += 1
    assert abs(sizes[0] - sizes[1]) <= 1


def test_ethiopian_range_respected():
    df = make_df()
    result = optimize(df, base_config(), base_constraints(df))
    counts = [0, 0]
    for _, row in df.iterrows():
        if row[FIELD_ETHIOPIAN_ORIGIN]:
            counts[result.assignment[row[FIELD_STUDENT_ID]]] += 1
    assert all(3 <= c <= 4 for c in counts)


def test_inclusion_exactly_two_per_class():
    df = make_df()
    result = optimize(df, base_config(), base_constraints(df))
    counts = [0, 0]
    for _, row in df.iterrows():
        if row[FIELD_INCLUSION]:
            counts[result.assignment[row[FIELD_STUDENT_ID]]] += 1
    assert counts == [2, 2]


def test_differential_max_one_per_class():
    df = make_df()
    result = optimize(df, base_config(), base_constraints(df))
    counts = [0, 0]
    for _, row in df.iterrows():
        if row[FIELD_DIFFERENTIAL]:
            counts[result.assignment[row[FIELD_STUDENT_ID]]] += 1
    assert all(c <= 1 for c in counts)


def test_locked_assignment_respected():
    df = make_df()
    constraints = base_constraints(df) + locked_constraints({1: 1})
    result = optimize(df, base_config(), constraints)
    assert result.is_feasible
    assert result.assignment[1] == 1


def test_invalid_num_classes_raises():
    df = make_df()
    config = base_config()
    config.num_classes = 0
    try:
        optimize(df, config, base_constraints(df))
        assert False, "expected OptimizationError"
    except OptimizationError:
        pass


def test_locked_to_nonexistent_class_raises():
    df = make_df()
    constraints = base_constraints(df) + locked_constraints({1: 5})
    try:
        optimize(df, base_config(), constraints)
        assert False, "expected OptimizationError"
    except OptimizationError:
        pass


def test_friendship_objective_runs_without_error():
    df = make_df()
    # Use students 11 & 12: no conflicting hard-category membership so the
    # friendship reward is free to co-place them.
    friendship = {11: [12], 12: [11]}  # mutual pair
    result = optimize(df, base_config(), base_constraints(df), friendship_matched=friendship)
    assert result.is_feasible
    # mutual pair should typically end up co-placed given the reward objective
    assert result.assignment[11] == result.assignment[12]


def test_separate_hard_keeps_pair_apart():
    df = make_df()
    constraints = base_constraints(df) + [
        Constraint(type="separate", hard=True, args={"student_a": 11, "student_b": 12}, label_hebrew="הפרדה לבדיקה")
    ]
    result = optimize(df, base_config(), constraints)
    assert result.is_feasible
    assert result.assignment[11] != result.assignment[12]


def test_together_hard_forces_same_class():
    df = make_df()
    constraints = base_constraints(df) + [
        Constraint(type="together", hard=True, args={"student_a": 11, "student_b": 12}, label_hebrew="צירוף לבדיקה")
    ]
    result = optimize(df, base_config(), constraints)
    assert result.is_feasible
    assert result.assignment[11] == result.assignment[12]


def test_at_least_one_of_hard_satisfied():
    df = make_df()
    constraints = base_constraints(df) + [
        Constraint(type="together", hard=True, args={"student_a": 11, "student_b": 12}, label_hebrew="צירוף עוגן"),
        Constraint(
            type="at_least_one_of",
            hard=True,
            args={"student": 10, "candidates": [11, 12]},
            label_hebrew="10 עם 11 או 12",
        ),
    ]
    result = optimize(df, base_config(), constraints)
    assert result.is_feasible
    assert result.assignment[10] in (result.assignment[11], result.assignment[12])


def test_default_constraints_count_not_exploded_per_value():
    df = make_df()
    constraints = base_constraints(df)
    # class_size, differential, ethiopian, inclusion, hamar, friendship_objective,
    # balance_academic, balance_school, balance_curclass, balance_category = 10
    # -- one row per rule, not one per distinct school/academic-level/current-class value.
    assert len(constraints) == 10
    assert len([c for c in constraints if c.type == "balance"]) == 4


def test_balance_field_all_values_hard_forces_even_split_per_value():
    df = pd.DataFrame({FIELD_STUDENT_ID: list(range(1, 9)), "category": ["x", "x", "x", "x", "y", "y", "y", "y"]})
    config = SolverConfig(num_classes=2, time_limit_seconds=10, random_seed=1)
    constraints = [
        Constraint(type="capacity", hard=True, args={"group": {"kind": "all"}, "min": 4, "max": 4}, label_hebrew="size"),
        Constraint(
            type="balance",
            hard=True,
            args={"group": {"kind": "field_all_values", "field": "category"}, "weight": 1.0},
            label_hebrew="test",
        ),
    ]
    result = optimize(df, config, constraints)
    assert result.is_feasible
    counts = {"x": [0, 0], "y": [0, 0]}
    for _, row in df.iterrows():
        c = result.assignment[row[FIELD_STUDENT_ID]]
        counts[row["category"]][c] += 1
    assert counts["x"][0] == counts["x"][1] == 2
    assert counts["y"][0] == counts["y"][1] == 2


def test_balance_fields_hard_forces_even_split_across_fields():
    df = pd.DataFrame(
        {
            FIELD_STUDENT_ID: list(range(1, 9)),
            "flag_a": [True, True, False, False, True, False, True, False],
            "flag_b": [False, True, True, False, False, True, False, True],
        }
    )
    config = SolverConfig(num_classes=2, time_limit_seconds=10, random_seed=1)
    constraints = [
        Constraint(type="capacity", hard=True, args={"group": {"kind": "all"}, "min": 4, "max": 4}, label_hebrew="size"),
        Constraint(
            type="balance",
            hard=True,
            args={"group": {"kind": "fields", "fields": ["flag_a", "flag_b"]}, "weight": 1.0},
            label_hebrew="test",
        ),
    ]
    result = optimize(df, config, constraints)
    assert result.is_feasible
    a_counts = [0, 0]
    b_counts = [0, 0]
    for _, row in df.iterrows():
        c = result.assignment[row[FIELD_STUDENT_ID]]
        if row["flag_a"]:
            a_counts[c] += 1
        if row["flag_b"]:
            b_counts[c] += 1
    assert a_counts[0] == a_counts[1] == 2
    assert b_counts[0] == b_counts[1] == 2


def test_conflict_set_extraction_identifies_contradictory_constraints():
    df = make_df()
    together = Constraint(type="together", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="ביחד")
    separate = Constraint(type="separate", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="בנפרד")
    constraints = base_constraints(df) + [together, separate]
    result = optimize(df, base_config(), constraints)
    assert not result.is_feasible
    assert together.id in result.conflicting_constraint_ids
    assert separate.id in result.conflicting_constraint_ids
