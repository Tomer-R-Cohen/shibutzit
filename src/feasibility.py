"""Pre-solve feasibility analysis for hard 'capacity' constraints.

Only capacity-type hard constraints have a simple closed-form arithmetic
pre-check (total group size vs. k*min / k*max) worth doing before invoking
the solver. Everything else (pairwise separate/together, at-least-one-of,
and any interaction between multiple hard constraints) has no such closed
form -- infeasibility there is only knowable by actually solving, and is
explained afterward via the solver's own conflict-set extraction (see
`OptimizationResult.conflicting_constraint_ids` in src/optimizer.py) rather
than pre-checked here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.constraints import Constraint, resolve_group_members


@dataclass
class FeasibilityFinding:
    rule: str
    feasible: bool
    message: str
    constraint_id: str = ""


@dataclass
class FeasibilityReport:
    findings: list[FeasibilityFinding] = field(default_factory=list)

    def add(self, rule: str, feasible: bool, message: str, constraint_id: str = "") -> None:
        self.findings.append(FeasibilityFinding(rule, feasible, message, constraint_id))

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


def analyze_feasibility(df: pd.DataFrame, constraints: list[Constraint], num_classes: int) -> FeasibilityReport:
    """Check whether population totals can possibly satisfy each active,
    hard "capacity" constraint, independent of the solver and of any other
    rule (no cross-constraint interaction is considered here).

    Args:
        df: mapped student DataFrame.
        constraints: full rule list; only active, hard, "capacity"-type
            entries are checked.
        num_classes: number of classes.

    Returns:
        FeasibilityReport listing each checked rule as feasible/infeasible
        with a human-readable explanation of the arithmetic involved.
    """
    report = FeasibilityReport()
    n = len(df)
    k = num_classes

    if k < 1:
        report.add("מספר כיתות", False, "מספר הכיתות חייב להיות לפחות 1.")
        return report

    if n < k:
        report.add(
            "מספר תלמידות מול כיתות",
            False,
            f"יש רק {n} תלמידות אך {k} כיתות - לא ניתן למלא כל כיתה.",
        )

    for c in constraints:
        if not c.active or not c.hard or c.type != "capacity":
            continue
        total = len(resolve_group_members(df, c.args["group"]))
        lo = c.args.get("min")
        hi = c.args.get("max")
        ok = True
        parts = [f'{total} תלמידות בקבוצה בסה"כ.']
        if lo is not None:
            needed = k * lo
            ok = ok and total >= needed
            parts.append(f"נדרש לפחות {needed} ({lo} x {k} כיתות).")
        if hi is not None:
            capacity = k * hi
            ok = ok and total <= capacity
            parts.append(f"קיבולת מרבית {capacity} ({hi} x {k} כיתות).")
        report.add(c.label_hebrew, ok, " ".join(parts), constraint_id=c.id)

    return report
