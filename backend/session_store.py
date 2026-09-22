"""Per-session state for the FastAPI backend.

Single-process, single-user-per-session, no auth, no DB. Sessions are keyed
by an opaque id the frontend generates and sends via the X-Session-Id
header. A session is created lazily on first use of an unknown id.

The user-provided *inputs* (tuned rules, pre-locks, manually typed category
data, and any custom column mapping) are persisted to disk per session so
they survive a browser refresh, a backend restart, or a machine reboot —
retyping category data for ~200 students was the single biggest rework risk.
The source location and immutable assignment snapshots are also persisted.
On restart, the workbook and derived roster analysis are rebuilt from the
source file, while a stored assignment version is restored without silently
running the solver again.
"""

from __future__ import annotations

import os
import pickle
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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

    kind: Literal["propose", "modify", "remove", "assignment_action", "data_action"]
    summary_hebrew: str
    constraint: Optional[dict] = None  # kind == "propose": the built Constraint, as a plain dict
    target_constraint_id: Optional[str] = None  # kind in ("modify", "remove")
    # kind == "modify": ordinary attribute changes, or
    # {"batch": [{"constraint_id": str, "changes": {...}}, ...]} for one
    # atomic counselor-approved package spanning several existing rules.
    changes: Optional[dict] = None
    action: Optional[Literal["move_student", "set_student_lock", "restore_version", "edit_student_data"]] = None
    action_args: Optional[dict] = None
    evidence: Optional[dict] = None


@dataclass
class AssignmentVersion:
    """Immutable, reproducible snapshot of one accepted solver/manual state."""

    number: int
    reason: str
    assignment: dict
    locked_assignment: dict
    run_config: dict
    constraints: list[dict]
    metrics: dict
    result: dict
    input_revision: int
    mode: Literal["solver", "manual"] = "solver"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approved: bool = False


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
    source_path: Optional[str] = None
    source_filename: Optional[str] = None
    source_load_options: dict = field(default_factory=dict)
    manual_entry_df: Optional[pd.DataFrame] = None
    # Confirmed corrections to the project's working copy. The uploaded
    # workbook remains immutable; this overlay is reapplied after mapping.
    student_data_edits: dict[int, dict[str, Any]] = field(default_factory=dict)
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
    # Durable instructions and an audit trail are structured project memory,
    # not merely prose buried in chat history. They are included in every
    # agent turn and persisted with the rest of the authoritative inputs.
    user_notes: list[str] = field(default_factory=list)
    decision_history: list[dict] = field(default_factory=list)
    # Inferences never replace explicit constraints.  They are evidence for
    # future ranking, with a confidence that can rise or fall as decisions
    # accumulate.
    inferred_preferences: list[dict] = field(default_factory=list)
    decision_portfolio: list[dict] = field(default_factory=list)
    assignment_versions: list[AssignmentVersion] = field(default_factory=list)
    current_version_id: Optional[str] = None
    chat_history: list[dict] = field(default_factory=list)
    pending_proposal: Optional[PendingProposal] = None
    # Most recent measured recommendation offered in conversation. This is
    # structured because a follow-up like "yes, use that" must resolve to the
    # exact tested rule, not ask the model to reconstruct numbers from prose.
    active_recommendation: Optional[dict] = None
    token_map: TokenMap = field(default_factory=TokenMap)
    # Monotonic version of every input that can affect the solver. A
    # successful solve records the exact version it consumed. This makes
    # result freshness authoritative on the server instead of inferred from
    # an ephemeral browser timeline.
    input_revision: int = 0
    solve_revision: Optional[int] = None
    result_mode: Literal["solver", "manual"] = "solver"

    def mark_inputs_changed(self, *, data_changed: bool = False, clear_result: bool = False) -> None:
        self.input_revision += 1
        self.feasibility_report = None
        self.active_recommendation = None
        if data_changed:
            self.validation_report = None
            self.friendship_result = None
            self.unmatched_df = None
        if clear_result:
            self.opt_result = None
            self.adjustment_state = None
            self.solve_revision = None
            self.result_mode = "solver"

    def mark_solved(self) -> None:
        self.solve_revision = self.input_revision
        self.result_mode = "solver"

    def mark_manually_adjusted(self) -> None:
        # A manual version is evaluated and snapshotted against the current
        # inputs. It is current (though it may still contain violations,
        # reported separately), not an old solver result.
        self.solve_revision = self.input_revision
        self.result_mode = "manual"

    def result_state(self) -> dict:
        has_result = bool(self.opt_result is not None and self.opt_result.is_feasible and self.adjustment_state is not None)
        return {
            "has_result": has_result,
            "is_stale": has_result and self.solve_revision != self.input_revision,
            "input_revision": self.input_revision,
            "solve_revision": self.solve_revision,
            "result_mode": self.result_mode if has_result else None,
        }


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
            "student_data_edits": sess.student_data_edits,
            "source_path": sess.source_path,
            "source_filename": sess.source_filename,
            "source_load_options": dict(sess.source_load_options),
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
            "user_notes": list(sess.user_notes),
            "decision_history": list(sess.decision_history),
            "inferred_preferences": list(sess.inferred_preferences),
            "decision_portfolio": list(sess.decision_portfolio),
            "assignment_versions": [asdict(v) for v in sess.assignment_versions],
            "current_version_id": sess.current_version_id,
            "chat_history": sess.chat_history,
            "pending_proposal": asdict(sess.pending_proposal) if sess.pending_proposal else None,
            "active_recommendation": sess.active_recommendation,
            "token_map": {
                "id_to_token": sess.token_map.id_to_token,
                "token_to_id": sess.token_map.token_to_id,
            },
            "input_revision": sess.input_revision,
            "solve_revision": sess.solve_revision,
            "result_mode": sess.result_mode,
        }
        try:
            with self._lock:
                target = self._path(sess.id)
                # Write beside the target and atomically replace it. A crash
                # or power loss can no longer leave a half-written pickle
                # that silently discards the counselor's saved inputs.
                fd, tmp_path = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=PERSIST_DIR)
                with os.fdopen(fd, "wb") as f:
                    pickle.dump(payload, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target)
        except Exception:
            # Persistence is a convenience, not a correctness requirement.
            try:
                if "tmp_path" in locals() and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
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

        raw_data_edits = payload.get("student_data_edits")
        if isinstance(raw_data_edits, dict):
            sess.student_data_edits = {
                int(student_id): dict(values)
                for student_id, values in raw_data_edits.items()
                if isinstance(values, dict)
            }

        sess.source_path = payload.get("source_path")
        sess.source_filename = payload.get("source_filename")
        raw_load_options = payload.get("source_load_options")
        if isinstance(raw_load_options, dict):
            sess.source_load_options = raw_load_options

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

        raw_notes = payload.get("user_notes")
        if isinstance(raw_notes, list):
            sess.user_notes = [str(note) for note in raw_notes if str(note).strip()]

        raw_decisions = payload.get("decision_history")
        if isinstance(raw_decisions, list):
            sess.decision_history = [d for d in raw_decisions if isinstance(d, dict)][-100:]

        raw_preferences = payload.get("inferred_preferences")
        if isinstance(raw_preferences, list):
            sess.inferred_preferences = [item for item in raw_preferences if isinstance(item, dict)][-50:]
        raw_portfolio = payload.get("decision_portfolio")
        if isinstance(raw_portfolio, list):
            sess.decision_portfolio = [item for item in raw_portfolio if isinstance(item, dict)][-10:]

        raw_versions = payload.get("assignment_versions")
        if isinstance(raw_versions, list):
            try:
                sess.assignment_versions = [AssignmentVersion(**v) for v in raw_versions if isinstance(v, dict)][-50:]
            except Exception:
                sess.assignment_versions = []
        sess.current_version_id = payload.get("current_version_id")

        chat_history = payload.get("chat_history")
        if chat_history:
            sess.chat_history = chat_history

        pp = payload.get("pending_proposal")
        if pp:
            try:
                sess.pending_proposal = PendingProposal(**pp)
            except Exception:
                pass

        recommendation = payload.get("active_recommendation")
        if isinstance(recommendation, dict):
            sess.active_recommendation = recommendation

        tm = payload.get("token_map")
        if tm:
            sess.token_map = TokenMap(
                id_to_token=tm.get("id_to_token", {}),
                token_to_id=tm.get("token_to_id", {}),
            )

        try:
            sess.input_revision = max(0, int(payload.get("input_revision", 0)))
            raw_solve_revision = payload.get("solve_revision")
            sess.solve_revision = int(raw_solve_revision) if raw_solve_revision is not None else None
            mode = payload.get("result_mode", "solver")
            sess.result_mode = mode if mode in ("solver", "manual") else "solver"
        except (TypeError, ValueError):
            pass

        # Rebuild the derived workbook/mapped table when the persisted source
        # still exists. This makes uploaded projects and version restoration
        # survive a backend restart without persisting live domain objects.
        if sess.source_path and os.path.exists(sess.source_path) and sess.col_mapping is not None:
            try:
                from src.column_mapping import apply_mapping
                from src.dataset_schema import attach_extra_columns
                from src.excel_loader import load_workbook

                opts = sess.source_load_options
                wb = load_workbook(
                    sess.source_path,
                    header_row_1indexed=int(opts.get("header_row", 4)),
                    first_data_row_1indexed=int(opts.get("first_data_row", 5)),
                    last_data_row_1indexed=int(opts["last_data_row"]) if opts.get("last_data_row") else None,
                )
                mapped = apply_mapping(wb.raw_df, sess.col_mapping, manual_df=sess.manual_entry_df)
                if sess.dataset_schema.extras:
                    mapped = attach_extra_columns(mapped, wb.raw_df, sess.dataset_schema)
                from backend.data_edits import apply_student_data_edits

                mapped = apply_student_data_edits(mapped, sess.student_data_edits)
                sess.loaded_wb = wb
                sess.mapped_df = mapped
                # These are derived from the roster but affect every social
                # metric and explanation. Rebuild them alongside the table
                # so a restored version does not appear to have zero friend
                # requests merely because the process restarted.
                from src.friendship_graph import resolve_requests, unmatched_report
                from src.validation import validate_students

                sess.validation_report = validate_students(mapped)
                sess.friendship_result = resolve_requests(mapped)
                sess.unmatched_df = unmatched_report(sess.friendship_result)
                current = next((v for v in sess.assignment_versions if v.id == sess.current_version_id), None)
                if current is not None:
                    sess.adjustment_state = AdjustmentState(
                        assignment=dict(current.assignment),
                        locked=set(current.locked_assignment.keys()),
                    )
                    sess.opt_result = OptimizationResult(**current.result)
            except Exception:
                # A missing/corrupt source should return the project to the
                # upload flow, never discard the persisted decisions/rules.
                sess.loaded_wb = None
                sess.mapped_df = None


store = SessionStore()
