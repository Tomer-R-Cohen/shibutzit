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


def base_config():
    return SolverConfig(
        num_classes=2,
        max_class_size_diff=1,
        max_differential_per_class=1,
        min_ethiopian_per_class=3,
        max_ethiopian_per_class=4,
        min_inclusion_per_class=2,
        max_inclusion_per_class=2,
        min_hamar_per_class=1,
        max_hamar_per_class=2,
        time_limit_seconds=15,
        random_seed=42,
    )


def test_all_students_assigned_exactly_once():
    df = make_df()
    result = optimize(df, base_config())
    assert result.is_feasible
    assert set(result.assignment.keys()) == set(df[FIELD_STUDENT_ID])
    assert all(0 <= c < 2 for c in result.assignment.values())


def test_class_size_balanced():
    df = make_df()
    result = optimize(df, base_config())
    sizes = [0, 0]
    for c in result.assignment.values():
        sizes[c] += 1
    assert abs(sizes[0] - sizes[1]) <= 1


def test_ethiopian_range_respected():
    df = make_df()
    result = optimize(df, base_config())
    counts = [0, 0]
    for _, row in df.iterrows():
        if row[FIELD_ETHIOPIAN_ORIGIN]:
            counts[result.assignment[row[FIELD_STUDENT_ID]]] += 1
    assert all(3 <= c <= 4 for c in counts)


def test_inclusion_exactly_two_per_class():
    df = make_df()
    result = optimize(df, base_config())
    counts = [0, 0]
    for _, row in df.iterrows():
        if row[FIELD_INCLUSION]:
            counts[result.assignment[row[FIELD_STUDENT_ID]]] += 1
    assert counts == [2, 2]


def test_differential_max_one_per_class():
    df = make_df()
    result = optimize(df, base_config())
    counts = [0, 0]
    for _, row in df.iterrows():
        if row[FIELD_DIFFERENTIAL]:
            counts[result.assignment[row[FIELD_STUDENT_ID]]] += 1
    assert all(c <= 1 for c in counts)


def test_locked_assignment_respected():
    df = make_df()
    config = base_config()
    locked = {1: 1}
    result = optimize(df, config, locked=locked)
    assert result.is_feasible
    assert result.assignment[1] == 1


def test_invalid_num_classes_raises():
    df = make_df()
    config = base_config()
    config.num_classes = 0
    try:
        optimize(df, config)
        assert False, "expected OptimizationError"
    except OptimizationError:
        pass


def test_locked_to_nonexistent_class_raises():
    df = make_df()
    config = base_config()
    try:
        optimize(df, config, locked={1: 5})
        assert False, "expected OptimizationError"
    except OptimizationError:
        pass


def test_friendship_objective_runs_without_error():
    df = make_df()
    config = base_config()
    # Use students 11 & 12: no conflicting hard-category membership so the
    # friendship reward is free to co-place them.
    friendship = {11: [12], 12: [11]}  # mutual pair
    result = optimize(df, config, friendship_matched=friendship)
    assert result.is_feasible
    # mutual pair should typically end up co-placed given the reward objective
    assert result.assignment[11] == result.assignment[12]
