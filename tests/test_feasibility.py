import pandas as pd

from src.column_mapping import (
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_STUDENT_ID,
)
from src.constraints import default_constraints
from src.feasibility import analyze_feasibility


def make_df(n=30, eth_count=10, diff_count=2, inc_count=12, hamar_count=6):
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                FIELD_STUDENT_ID: i,
                FIELD_ETHIOPIAN_ORIGIN: i <= eth_count,
                FIELD_DIFFERENTIAL: i <= diff_count,
                FIELD_INCLUSION: i <= inc_count,
                FIELD_HAMAR: i <= hamar_count,
            }
        )
    return pd.DataFrame(rows)


def test_feasible_configuration_reports_all_feasible():
    df = make_df(n=30, eth_count=18, diff_count=6, inc_count=12, hamar_count=9)
    constraints = default_constraints(df, 6)
    report = analyze_feasibility(df, constraints, 6)
    assert report.all_feasible(), report.to_dataframe()


def test_infeasible_ethiopian_min_detected():
    # 6 classes need >=3 each = 18 minimum, but only 5 Ethiopian-origin students total.
    df = make_df(n=30, eth_count=5, diff_count=2, inc_count=12, hamar_count=6)
    constraints = default_constraints(df, 6)
    report = analyze_feasibility(df, constraints, 6)
    assert not report.all_feasible()
    assert any("אתיופי" in f.rule for f in report.infeasible)


def test_infeasible_differential_max_detected():
    # 6 classes allow max 1 each = 6 total capacity, but 10 differential students exist.
    df = make_df(n=30, eth_count=18, diff_count=10, inc_count=12, hamar_count=9)
    constraints = default_constraints(df, 6)
    report = analyze_feasibility(df, constraints, 6)
    assert not report.all_feasible()
    assert any("דיפרנציאלי" in f.rule for f in report.infeasible)


def test_demoting_to_soft_removes_check():
    df = make_df(n=30, eth_count=5, diff_count=2, inc_count=12, hamar_count=6)
    constraints = default_constraints(df, 6, ethiopian_hard=False)
    report = analyze_feasibility(df, constraints, 6)
    assert not any("אתיופי" in f.rule for f in report.findings)


def test_class_size_feasibility():
    df = make_df(n=31)
    constraints = default_constraints(df, 6, max_class_size_diff=1)
    report = analyze_feasibility(df, constraints, 6)
    size_finding = [f for f in report.findings if "גודל כיתה" in f.rule][0]
    assert size_finding.feasible
