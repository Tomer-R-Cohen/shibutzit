"""Per-session state for the FastAPI backend.

Single-process, single-user-per-session, no auth, no DB. Sessions are keyed
by an opaque id the frontend generates and sends via the X-Session-Id
header. A session is created lazily on first use of an unknown id.

The user-provided *inputs* (tuned rules, pre-locks, manually typed category
data, and any custom column mapping) are persisted to disk per session so
they survive a browser refresh, a backend restart, or a machine reboot —
retyping category data for ~200 students was the single biggest rework risk.
Derived state (the loaded workbook, mapped table, validation/feasibility
reports, the solved assignment) is NOT persisted: it is cheaply rebuilt by
re-loading the source file and re-running the solver with one click.
"""

from __future__ import annotations

import os
import pickle
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd

from src.column_mapping import ColumnMapping
from src.excel_loader import LoadedWorkbook
from src.friendship_graph import NameResolutionResult
from src.manual_adjustments import AdjustmentState
from src.optimizer import OptimizationResult, SolverConfig

PERSIST_DIR = os.path.join(os.path.dirname(__file__), ".sessions")


def _safe_name(session_id: str) -> str:
    """Session ids are opaque uuids, but sanitize so a hostile id can't escape
    the persistence directory."""
    cleaned = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return cleaned or "default"


@dataclass
class Session:
    id: str
    loaded_wb: Optional[LoadedWorkbook] = None
    col_mapping: Optional[ColumnMapping] = None
    mapped_df: Optional[pd.DataFrame] = None
    manual_entry_df: Optional[pd.DataFrame] = None
    validation_report: Any = None
    friendship_result: Optional[NameResolutionResult] = None
    unmatched_df: Optional[pd.DataFrame] = None
    target_distribution_df: Optional[pd.DataFrame] = None
    feasibility_report: Any = None
    solver_config: SolverConfig = field(default_factory=SolverConfig)
    locked_assignment: dict = field(default_factory=dict)
    opt_result: Optional[OptimizationResult] = None
    adjustment_state: Optional[AdjustmentState] = None


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        try:
            os.makedirs(PERSIST_DIR, exist_ok=True)
        except OSError:
            pass

    def _path(self, session_id: str) -> str:
        return os.path.join(PERSIST_DIR, _safe_name(session_id) + ".pkl")

    def get_or_create(self, session_id: str) -> Session:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                sess = Session(id=session_id)
                self._restore(sess)
                self._sessions[session_id] = sess
            return sess

    def reset(self, session_id: str) -> Session:
        with self._lock:
            sess = Session(id=session_id)
            self._sessions[session_id] = sess
            try:
                os.remove(self._path(session_id))
            except FileNotFoundError:
                pass
            except OSError:
                pass
            return sess

    # ---- persistence (best-effort; never breaks a request) ----

    def save(self, sess: Session) -> None:
        """Persist the user-provided inputs of a session to disk. Only stores
        plain data (dicts, lists, a DataFrame) — never live domain objects — so
        the file stays readable across code changes."""
        cm = sess.col_mapping
        payload = {
            "solver_config": asdict(sess.solver_config) if sess.solver_config else None,
            "locked_assignment": sess.locked_assignment,
            "manual_entry": sess.manual_entry_df,
            "col_mapping": (
                {"mapping": dict(cm.mapping), "manual_fields": sorted(cm.manual_fields)}
                if cm is not None
                else None
            ),
        }
        try:
            with self._lock:
                with open(self._path(sess.id), "wb") as f:
                    pickle.dump(payload, f)
        except Exception:
            # Persistence is a convenience, not a correctness requirement.
            pass

    def _restore(self, sess: Session) -> None:
        """Load persisted inputs into a freshly-created session. Called while
        holding the store lock (from get_or_create)."""
        path = self._path(sess.id)
        if not os.path.exists(path):
            return
        try:
            with open(path, "rb") as f:
                payload = pickle.load(f)
        except Exception:
            return

        sc = payload.get("solver_config")
        if sc:
            try:
                sess.solver_config = SolverConfig(**sc)
            except Exception:
                pass

        locks = payload.get("locked_assignment")
        if locks:
            sess.locked_assignment = locks

        manual = payload.get("manual_entry")
        if manual is not None:
            sess.manual_entry_df = manual

        cm_data = payload.get("col_mapping")
        if cm_data:
            try:
                cm = ColumnMapping()
                manual_fields = set(cm_data.get("manual_fields", []))
                for fld, col in cm_data.get("mapping", {}).items():
                    if fld in manual_fields or col is None:
                        cm.mark_manual(fld)
                    else:
                        cm.set(fld, col)
                sess.col_mapping = cm
            except Exception:
                pass


store = SessionStore()
