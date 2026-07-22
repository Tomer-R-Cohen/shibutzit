from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from src.column_mapping import FIELD_STUDENT_ID
from src.manual_adjustments import AdjustmentState, ManualAdjustmentError, apply_editor_dataframe
from src.metrics import class_overview_table, compute_global_metrics, student_assignment_table, violations_report
from src.optimizer import OptimizationError, SolverConfig, optimize

from ..schemas import LockingRequest, MoveStudentRequest
from ..session_store import store
from ..utils import df_records, require

router = APIRouter()


@router.post("/api/locking")
async def set_locking(req: LockingRequest, x_session_id: str = Header(...)):
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
    return {"locked_count": len(locked)}


@router.get("/api/locking")
async def get_locking(x_session_id: str = Header(...)):
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
async def run_optimize(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים שלבים קודמים תחילה.")
    if sess.validation_report is not None and sess.validation_report.has_errors():
        raise HTTPException(status_code=400, detail="קיימות שגיאות אימות חוסמות (שלב 4). יש לתקן לפני ההרצה.")

    cfg = sess.solver_config or SolverConfig()
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    locked = sess.locked_assignment or {}

    try:
        result = optimize(df, cfg, locked=locked, friendship_matched=matched)
    except OptimizationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sess.opt_result = result
    sess.adjustment_state = AdjustmentState(assignment=dict(result.assignment), locked=set(locked.keys()))

    return {
        "status_name": result.status_name,
        "is_feasible": result.is_feasible,
        "wall_time_seconds": result.wall_time_seconds,
        "objective_value": result.objective_value,
        "infeasibility_notes": result.infeasibility_notes,
    }


def _require_result(sess):
    if sess.opt_result is None or not sess.opt_result.is_feasible:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה מוצלחת תחילה (שלב 8).")


@router.get("/api/results/overview")
async def results_overview(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    cfg = sess.solver_config
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    table = class_overview_table(df, state.assignment, matched, cfg)
    return {"rows": df_records(table)}


@router.get("/api/results/students")
async def results_students(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    table = student_assignment_table(df, state.assignment, matched, state.locked_assignment())
    return {"rows": df_records(table)}


@router.get("/api/results/metrics")
async def results_metrics(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    cfg = sess.solver_config
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    gm = compute_global_metrics(
        df, state.assignment, matched, cfg,
        sess.opt_result.status_name, sess.opt_result.wall_time_seconds, sess.opt_result.objective_value,
    )
    return gm.__dict__


@router.get("/api/results/violations")
async def results_violations(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    cfg = sess.solver_config
    state = sess.adjustment_state
    table = violations_report(df, state.assignment, cfg)
    return {"rows": df_records(table)}


@router.get("/api/results/friendship")
async def results_friendship(x_session_id: str = Header(...)):
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
async def adjustment_move(req: MoveStudentRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    if sess.adjustment_state is None:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה תחילה (שלב 8).")
    state: AdjustmentState = sess.adjustment_state
    cfg = sess.solver_config
    try:
        state.move_student(req.student_id, req.new_class - 1, cfg.num_classes)
    except ManualAdjustmentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if req.locked is True:
        state.lock(req.student_id)
    elif req.locked is False:
        state.unlock(req.student_id)

    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    gm = compute_global_metrics(df, state.assignment, matched, cfg)
    return {"assignment_updated": True, "metrics": gm.__dict__}


@router.post("/api/adjustment/reoptimize")
async def adjustment_reoptimize(x_session_id: str = Header(...)):
    """Lock all current assignments and re-optimize the remainder. Single
    optimize() call, mirroring the "lock all & re-optimize" button in the
    Streamlit app's step 10."""
    sess = store.get_or_create(x_session_id)
    if sess.adjustment_state is None:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה תחילה (שלב 8).")
    state: AdjustmentState = sess.adjustment_state
    df = sess.mapped_df
    cfg = sess.solver_config
    matched = sess.friendship_result.matched if sess.friendship_result else {}

    state.lock_all_current()
    try:
        result = optimize(df, cfg, locked=state.locked_assignment(), friendship_matched=matched)
    except OptimizationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sess.opt_result = result
    state.assignment = dict(result.assignment)
    sess.adjustment_state = state
    return {
        "status_name": result.status_name,
        "is_feasible": result.is_feasible,
        "wall_time_seconds": result.wall_time_seconds,
        "objective_value": result.objective_value,
    }
