"""Pre-solve feasibility analysis for hard constraints.

Before invoking the CP-SAT solver, compute simple arithmetic feasibility
checks against actual population totals, so users get a clear explanation
of *why* a configuration is infeasible instead of a bare "no solution".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.column_mapping import (
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
)
from src.optimizer import SolverConfig


@dataclass
class FeasibilityFinding:
    rule: str
    feasible: bool
    message: str


@dataclass
class FeasibilityReport:
    findings: list[FeasibilityFinding] = field(default_factory=list)

    def add(self, rule: str, feasible: bool, message: str) -> None:
        self.findings.append(FeasibilityFinding(rule, feasible, message))

    @property
    def infeasible(self) -> list[FeasibilityFinding]:
        return [f for f in self.findings if not f.feasible]

    def all_feasible(self) -> bool:
        return len(self.infeasible) == 0

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"חוק": f.rule, "אפשרי": "כן" if f.feasible else "לא", "הסבר": f.message}
                for f in self.findings
            ]
        )


def analyze_feasibility(df: pd.DataFrame, config: SolverConfig) -> FeasibilityReport:
    """Check whether population totals can possibly satisfy each hard rule.

    Args:
        df: mapped student DataFrame.
        config: SolverConfig with class counts and per-class bounds.

    Returns:
        FeasibilityReport listing each checked rule as feasible/infeasible
        with a human-readable explanation of the arithmetic involved.
    """
    report = FeasibilityReport()
    n = len(df)
    k = config.num_classes

    # 1. Class size balance
    if config.class_size_hard:
        min_size = n // k
        max_size = -(-n // k)  # ceil
        spread = max_size - min_size
        ok = spread <= config.max_class_size_diff
        report.add(
            "איזון גודל כיתות",
            ok,
            f"{n} תלמידות ב-{k} כיתות => גדלים בין {min_size} ל-{max_size} "
            f"(פער {spread}). מגבלה מותרת: {config.max_class_size_diff}.",
        )

    # 2. Differential per class
    if config.differential_hard:
        total = int(df[FIELD_DIFFERENTIAL].sum()) if FIELD_DIFFERENTIAL in df.columns else 0
        capacity = k * config.max_differential_per_class
        ok = total <= capacity
        report.add(
            "תלמידות דיפרנציאליות",
            ok,
            f"{total} תלמידות דיפרנציאליות בסה\"כ; קיבולת מרבית {capacity} "
            f"({config.max_differential_per_class} x {k} כיתות).",
        )

    # 3. Ethiopian origin range
    if config.ethiopian_hard:
        total = int(df[FIELD_ETHIOPIAN_ORIGIN].sum()) if FIELD_ETHIOPIAN_ORIGIN in df.columns else 0
        min_needed = k * config.min_ethiopian_per_class
        max_capacity = k * config.max_ethiopian_per_class
        ok = min_needed <= total <= max_capacity
        report.add(
            "מוצא אתיופי",
            ok,
            f"{total} תלמידות ממוצא אתיופי; נדרש בין {min_needed} ל-{max_capacity} "
            f"בסה\"כ (טווח {config.min_ethiopian_per_class}-{config.max_ethiopian_per_class} לכיתה).",
        )

    # 4. Inclusion
    if config.inclusion_hard:
        total = int(df[FIELD_INCLUSION].sum()) if FIELD_INCLUSION in df.columns else 0
        min_needed = k * config.min_inclusion_per_class
        max_capacity = k * config.max_inclusion_per_class
        ok = min_needed <= total <= max_capacity
        report.add(
            "שילוב",
            ok,
            f"{total} תלמידות בשילוב; נדרש בין {min_needed} ל-{max_capacity} בסה\"כ "
            f"(טווח {config.min_inclusion_per_class}-{config.max_inclusion_per_class} לכיתה).",
        )

    # 5. Hamar
    if config.hamar_hard:
        total = int(df[FIELD_HAMAR].sum()) if FIELD_HAMAR in df.columns else 0
        min_needed = k * config.min_hamar_per_class
        max_capacity = k * config.max_hamar_per_class
        ok = min_needed <= total <= max_capacity
        report.add(
            'ח"מ',
            ok,
            f'{total} תלמידות ח"מ; נדרש בין {min_needed} ל-{max_capacity} בסה"כ '
            f"(טווח {config.min_hamar_per_class}-{config.max_hamar_per_class} לכיתה).",
        )

    if k < 1:
        report.add("מספר כיתות", False, "מספר הכיתות חייב להיות לפחות 1.")
    if n < k and k > 0:
        report.add(
            "מספר תלמידות מול כיתות",
            False,
            f"יש רק {n} תלמידות אך {k} כיתות - לא ניתן למלא כל כיתה.",
        )

    return report
