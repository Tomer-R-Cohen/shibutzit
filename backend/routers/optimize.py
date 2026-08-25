from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException

from src.column_mapping import FIELD_STUDENT_ID
from src.constraints import Constraint, locked_constraints
from src.manual_adjustments import AdjustmentState, ManualAdjustmentError, apply_editor_dataframe
from src.metrics import class_overview_table, compute_global_metrics, student_assignment_table, violations_report
from src.optimizer import OptimizationError, OptimizationResult, optimize

from ..llm.narration import narrate_infeasibility, narrate_result, relaxation_candidate
from ..schemas import LockingRequest, MoveStudentRequest
from ..session_store import PendingProposal, Session, store
from ..solver_inputs import build_locked_constraints, build_solver_inputs
from ..utils import df_records, require

router = APIRouter()
logger = logging.getLogger(__name__)


def _narrate_if_infeasible(sess: Session, result: OptimizationResult, constraints: list[Constraint]) -> str | None:
    """Backend-triggered (not user-triggered): the conflict is already
    known deterministically via `result.conflicting_constraint_ids` -- this
    only phrases it and records it in the chat panel so it shows up
    alongside any manual constraint editing the counselor does next."""
    if result.is_feasible:
        return None
    conflicting = [c for c in constraints if c.id in result.conflicting_constraint_ids]
    explanation = narrate_infeasibility(conflicting)
    sess.chat_history.append({"role": "assistant", "content": explanation})
    store.save(sess)
    return explanation


def _propose_relaxation(sess: Session, result: OptimizationResult, constraints: list[Constraint]) -> dict | None:
    """When a solve is proven infeasible, stage a concrete, confirmable way
    out instead of leaving the counselor at a dead end: soften one of the
    conflicting hard rules to a preference.

    Deterministic on purpose -- the target and the change come from the
    solver's own conflict set, not from a model, so this works with no LLM
    configured. It reuses the existing PendingProposal/confirm machinery
    (kind="modify" + changes={"hard": False}), so confirming it goes
    through exactly the same path as a chat-proposed change.
    """
    if result.is_feasible:
        return None
    conflicting = [c for c in constraints if c.id in result.conflicting_constraint_ids]
    target = relaxation_candidate(conflicting)
    if target is None:
        return None

    proposal = PendingProposal(
        kind="modify",
        summary_hebrew=(
            f'הפיכת "{target.label_hebrew}" מכלל חובה להעדפה תשחרר את ההתנגשות הנוכחית. '
            "הכלל ימשיך להשפיע על השיבוץ, אבל לא יחסום אותו."
        ),
        target_constraint_id=target.id,
        changes={"hard": False},
    )
    sess.pending_proposal = proposal
    store.save(sess)
    return asdict(proposal)


def _comment_on_result(sess: Session, cfg, constraints: list[Constraint]) -> str | None:
    """A short read of a successful result, from the same metrics the UI
    shows -- so the numbers in the prose can't drift from the numbers in
    the artifact. Returns None when the LLM isn't configured."""
    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    gm = compute_global_metrics(
        df, state.assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students
    )
    overview = class_overview_table(df, state.assignment, matched, constraints, cfg.num_classes)
    scores = overview["ציון איכות"].tolist() if not overview.empty else []
    summary = (
        f"סה\"כ {gm.total_students} תלמידות ב-{gm.num_classes} כיתות. "
        f"גדלים: {gm.class_sizes}. הפרות קשיחות: {gm.violations_count}. "
        f"בקשות חברות שמומשו במלואן: {gm.satisfied_requests}, חלקית: {gm.partial_requests}, "
        f"ללא מענה: {gm.unsatisfied_requests}. ציוני איכות לפי כיתה: {[round(s) for s in scores]}."
    )
    return narrate_result(summary)


@router.post("/api/locking")
def set_locking(req: LockingRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים שלבים קודמים תחילה.")
    id_type = type(df[FIELD_STUDENT_ID].iloc[0]) if len(df) else int
    locked = {}
    for sid_str, cls in req.locks.items():
        if cls and int(cls) >= 1:
            try:
                sid = id_type(sid_str)
            except Exception:
                sid = sid_str
            locked[sid] = int(cls) - 1
    sess.locked_assignment = locked
    store.save(sess)
    return {"locked_count": len(locked)}


@router.get("/api/locking")
def get_locking(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים שלבים קודמים תחילה.")
    rows = [
        {FIELD_STUDENT_ID: sid, "locked_class": sess.locked_assignment.get(sid, 0) + 1 if sid in sess.locked_assignment else 0}
        for sid in df[FIELD_STUDENT_ID].tolist()
    ]
    return {"rows": rows, "locked_count": len(sess.locked_assignment)}


# INVARIANT: opt_result / adjustment_state are only ever written from this
# explicitly-called endpoint (step 8) or /api/adjustment/reoptimize (step
# 10's "lock & re-optimize" button). No other route may overwrite a
# computed result as a side effect. Each call here triggers exactly one
# optimize() call.
@router.post("/api/optimize")
def run_optimize(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים שלבים קודמים תחילה.")
    if sess.validation_report is not None and sess.validation_report.has_errors():
        raise HTTPException(status_code=400, detail="קיימות שגיאות אימות חוסמות (שלב 4). יש לתקן לפני ההרצה.")

    cfg, constraints = build_solver_inputs(sess)
    constraints = constraints + build_locked_constraints(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    locked = sess.locked_assignment or {}

    try:
        result = optimize(df, cfg, constraints, friendship_matched=matched)
    except OptimizationError as e:
        logger.warning("optimize() raised for session %s: %s", x_session_id, e)
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        "optimize done session=%s status=%s feasible=%s wall_time=%.2fs",
        x_session_id, result.status_name, result.is_feasible, result.wall_time_seconds,
    )
    sess.opt_result = result
    sess.adjustment_state = AdjustmentState(assignment=dict(result.assignment), locked=set(locked.keys()))
    explanation = _narrate_if_infeasible(sess, result, constraints)
    relaxation = _propose_relaxation(sess, result, constraints)
    comment = _comment_on_result(sess, cfg, constraints) if result.is_feasible else None

    return {
        "status_name": result.status_name,
        "is_feasible": result.is_feasible,
        "wall_time_seconds": result.wall_time_seconds,
        "objective_value": result.objective_value,
        "infeasibility_notes": result.infeasibility_notes,
        "conflicting_constraint_ids": result.conflicting_constraint_ids,
        "infeasibility_explanation": explanation,
        "relaxation_proposal": relaxation,
        "result_comment": comment,
    }


def _require_result(sess):
    if sess.opt_result is None or not sess.opt_result.is_feasible:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה מוצלחת תחילה (שלב 8).")


@router.get("/api/results/overview")
def results_overview(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    table = class_overview_table(df, state.assignment, matched, constraints, cfg.num_classes)
    return {"rows": df_records(table)}


@router.get("/api/results/students")
def results_students(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    table = student_assignment_table(df, state.assignment, matched, state.locked_assignment())
    return {"rows": df_records(table)}


@router.get("/api/results/metrics")
def results_metrics(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    gm = compute_global_metrics(
        df, state.assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students,
        sess.opt_result.status_name, sess.opt_result.wall_time_seconds, sess.opt_result.objective_value,
    )
    return gm.__dict__


@router.get("/api/results/violations")
def results_violations(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    state = sess.adjustment_state
    table = violations_report(df, state.assignment, constraints, cfg.num_classes)
    return {"rows": df_records(table)}


@router.get("/api/results/friendship")
def results_friendship(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    unmatched_df = sess.unmatched_df
    no_data = [sid for sid in df[FIELD_STUDENT_ID] if sid not in matched or not matched.get(sid)]
    return {
        "unmatched_rows": df_records(unmatched_df) if unmatched_df is not None else [],
        "no_request_data_count": len(no_data),
    }


@router.post("/api/adjustment/move")
def adjustment_move(req: MoveStudentRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    if sess.adjustment_state is None:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה תחילה (שלב 8).")
    state: AdjustmentState = sess.adjustment_state
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    try:
        state.move_student(req.student_id, req.new_class - 1, cfg.num_classes)
    except ManualAdjustmentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if req.locked is True:
        state.lock(req.student_id)
    elif req.locked is False:
        state.unlock(req.student_id)

    matched = sess.friendship_result.matched if sess.friendship_result else {}
    gm = compute_global_metrics(df, state.assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students)
    return {"assignment_updated": True, "metrics": gm.__dict__}


@router.post("/api/adjustment/reoptimize")
def adjustment_reoptimize(x_session_id: str = Header(...)):
    """Lock all current assignments and re-optimize the remainder. Single
    optimize() call, mirroring the "lock all & re-optimize" button in the
    Streamlit app's step 10."""
    sess = store.get_or_create(x_session_id)
    if sess.adjustment_state is None:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה תחילה (שלב 8).")
    state: AdjustmentState = sess.adjustment_state
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}

    state.lock_all_current()
    all_constraints = constraints + locked_constraints(state.locked_assignment(), hard=True)
    try:
        result = optimize(df, cfg, all_constraints, friendship_matched=matched)
    except OptimizationError as e:
        logger.warning("reoptimize() raised for session %s: %s", x_session_id, e)
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        "reoptimize done session=%s status=%s feasible=%s wall_time=%.2fs",
        x_session_id, result.status_name, result.is_feasible, result.wall_time_seconds,
    )
    sess.opt_result = result
    state.assignment = dict(result.assignment)
    sess.adjustment_state = state
    explanation = _narrate_if_infeasible(sess, result, all_constraints)

    return {
        "status_name": result.status_name,
        "is_feasible": result.is_feasible,
        "wall_time_seconds": result.wall_time_seconds,
        "objective_value": result.objective_value,
        "infeasibility_notes": result.infeasibility_notes,
        "conflicting_constraint_ids": result.conflicting_constraint_ids,
        "infeasibility_explanation": explanation,
    }
