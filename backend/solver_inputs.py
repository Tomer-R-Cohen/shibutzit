"""Session <-> solver-input glue.

The built-in rule set (class size, demographic capacity ranges, friendship
co-placement, balance objectives) is seeded into `Session.constraints`
exactly once, the first time a workbook is mapped -- not re-derived on
every request -- so it has stable ids a counselor's chat messages or direct
edits can reference and modify, the same as any exception added later.
`build_solver_inputs` is the one place every solve/feasibility/export call
site gets its inputs from, so they can never drift out of sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src.constraints import Constraint, class_size_label_hebrew, default_constraints, locked_constraints
from src.optimizer import SolverConfig

if TYPE_CHECKING:
    from .session_store import Session


def ensure_defaults_seeded(sess: "Session", df: pd.DataFrame) -> None:
    """Seed `sess.constraints` with the built-in rules exactly once. Safe to
    call on every mapping-apply -- a no-op once defaults already exist, so a
    counselor's edits (hard/soft toggles, bound tweaks, a removed default)
    are never clobbered by a later re-map."""
    if any(c.source == "builtin_default" for c in sess.constraints):
        return
    defaults = default_constraints(df, sess.run_config.num_classes)
    sess.constraints = defaults + sess.constraints


def sync_class_size_bounds(sess: "Session", df: pd.DataFrame) -> None:
    """The class-size rule's min/max are static numbers computed from
    roster size and num_classes at seed time; recompute them (preserving
    the counselor's size_diff tolerance) whenever either changes, instead
    of re-seeding -- re-seeding would lose any other edits already made to
    the constraint list."""
    n = len(df)
    k = sess.run_config.num_classes
    if k < 1:
        return
    for c in sess.constraints:
        group = c.args.get("group", {})
        if c.type == "capacity" and group.get("kind") == "all":
            diff = c.args.get("size_diff", 1)
            base = n // k
            c.args["max"] = -(-n // k) + diff
            c.args["min"] = max(0, base - diff)
            c.label_hebrew = class_size_label_hebrew(c.args["min"], c.args["max"])


def build_solver_inputs(sess: "Session") -> tuple[SolverConfig, list[Constraint]]:
    return sess.run_config, sess.constraints


def build_locked_constraints(sess: "Session") -> list[Constraint]:
    """Locked assignments stay a separate session field (edited via
    /api/locking), not part of `constraints` -- only translated to
    Constraint objects at solve time."""
    return locked_constraints(sess.locked_assignment, hard=True)
