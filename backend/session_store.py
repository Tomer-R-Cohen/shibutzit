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
from typing import Any, Literal, Optional

import pandas as pd

from src.column_mapping import ColumnMapping
from src.constraints import Constraint
from src.data_requirements import DataRequirement
from src.dataset_schema import DatasetSchema, ExtraColumn
from src.excel_loader import LoadedWorkbook
from src.friendship_graph import NameResolutionResult
from src.manual_adjustments import AdjustmentState
from src.optimizer import OptimizationResult, SolverConfig

from .llm.tokenization import TokenMap

PERSIST_DIR = os.path.join(os.path.dirname(__file__), ".sessions")


@dataclass
class PendingProposal:
    """A chat-derived change awaiting explicit counselor confirmation
    before it touches `Session.constraints`. Exactly one at a time per
    session -- a new chat message replaces whatever was pending."""

    kind: Literal["propose", "modify", "remove"]
    summary_hebrew: str
    constraint: Optional[dict] = None  # kind == "propose": the built Constraint, as a plain dict
    target_constraint_id: Optional[str] = None  # kind in ("modify", "remove")
    changes: Optional[dict] = None  # kind == "modify": {"hard": bool} and/or {"active": bool}


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
    # Run parameters only (num_classes, time limit, seed, ...) -- every
    # actual rule (including the built-in defaults) lives in `constraints`
    # below, seeded once via backend/solver_inputs.ensure_defaults_seeded.
    run_config: SolverConfig = field(default_factory=SolverConfig)
    locked_assignment: dict = field(default_factory=dict)
    opt_result: Optional[OptimizationResult] = None
    adjustment_state: Optional[AdjustmentState] = None
    constraints: list[Constraint] = field(default_factory=list)
    # Columns this workbook has that the app doesn't know by name. Detected
    # at mapping time; what makes rules about arbitrary spreadsheet columns
    # possible. See src/dataset_schema.py.
    dataset_schema: DatasetSchema = field(default_factory=DatasetSchema)
    # Columns the counselor agreed to add to the workbook, recorded during
    # planning -- before any file exists. See src/data_requirements.py.
    data_requirements: list[DataRequirement] = field(default_factory=list)
    chat_history: list[dict] = field(default_factory=list)
    pending_proposal: Optional[PendingProposal] = None
    token_map: TokenMap = field(default_factory=TokenMap)


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
            "run_config": asdict(sess.run_config) if sess.run_config else None,
            "locked_assignment": sess.locked_assignment,
            "manual_entry": sess.manual_entry_df,
            "col_mapping": (
                {"mapping": dict(cm.mapping), "manual_fields": sorted(cm.manual_fields)}
                if cm is not None
                else None
            ),
            "constraints": [asdict(c) for c in sess.constraints],
            "dataset_schema": sess.dataset_schema.to_dicts() if sess.dataset_schema else [],
            "data_requirements": [
                {"id": r.id, "label": r.label, "kind": r.kind, "reason": r.reason, "values": list(r.values)}
                for r in sess.data_requirements
            ],
            "chat_history": sess.chat_history,
            "pending_proposal": asdict(sess.pending_proposal) if sess.pending_proposal else None,
            "token_map": {
                "id_to_token": sess.token_map.id_to_token,
                "token_to_id": sess.token_map.token_to_id,
            },
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

        rc = payload.get("run_config")
        if rc:
            # The search budget used to default to 30s and was only reachable
            # from a sub-view nobody opened, so a stored 30.0 is the old
            # default rather than a choice anyone made. Carry such sessions
            # onto the new 60s default; any other value was deliberate and is
            # left alone.
            if rc.get("time_limit_seconds") == 30.0:
                rc = {**rc, "time_limit_seconds": 60.0}
            try:
                sess.run_config = SolverConfig(**rc)
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

        raw_constraints = payload.get("constraints")
        if raw_constraints:
            try:
                sess.constraints = [Constraint(**c) for c in raw_constraints]
            except Exception:
                pass

        raw_schema = payload.get("dataset_schema")
        if raw_schema:
            try:
                sess.dataset_schema = DatasetSchema(extras=[ExtraColumn(**c) for c in raw_schema])
            except Exception:
                pass

        raw_reqs = payload.get("data_requirements")
        if raw_reqs:
            try:
                sess.data_requirements = [DataRequirement(**r) for r in raw_reqs]
            except Exception:
                pass

        chat_history = payload.get("chat_history")
        if chat_history:
            sess.chat_history = chat_history

        pp = payload.get("pending_proposal")
        if pp:
            try:
                sess.pending_proposal = PendingProposal(**pp)
            except Exception:
                pass

        tm = payload.get("token_map")
        if tm:
            sess.token_map = TokenMap(
                id_to_token=tm.get("id_to_token", {}),
                token_to_id=tm.get("token_to_id", {}),
            )


store = SessionStore()
