"""In-memory per-session state, mirroring what st.session_state held in app.py.

Single-process, single-user-per-session, no auth, no DB. Sessions are keyed
by an opaque id the frontend generates and sends via the X-Session-Id
header. A session is created lazily on first use of an unknown id.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from src.column_mapping import ColumnMapping
from src.excel_loader import LoadedWorkbook
from src.friendship_graph import NameResolutionResult
from src.manual_adjustments import AdjustmentState
from src.optimizer import OptimizationResult, SolverConfig


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

    def get_or_create(self, session_id: str) -> Session:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                sess = Session(id=session_id)
                self._sessions[session_id] = sess
            return sess

    def reset(self, session_id: str) -> Session:
        with self._lock:
            sess = Session(id=session_id)
            self._sessions[session_id] = sess
            return sess


store = SessionStore()
