from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Response

from src.export_excel import export_to_excel

from ..session_store import store
from ..solver_inputs import build_solver_inputs

router = APIRouter()


@router.get("/api/export.xlsx")
def export_xlsx(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    if sess.adjustment_state is None:
        raise HTTPException(status_code=409, detail="אין שיבוץ להצגה - יש להריץ אופטימיזציה תחילה.")
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    state = sess.adjustment_state
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    unmatched_df = sess.unmatched_df
    opt_result = sess.opt_result
    wb = sess.loaded_wb

    import pandas as pd

    data = export_to_excel(
        df,
        state.assignment,
        matched,
        cfg,
        constraints,
        unmatched_df if unmatched_df is not None else pd.DataFrame(),
        solver_status=opt_result.status_name if opt_result else "",
        solver_wall_time=opt_result.wall_time_seconds if opt_result else 0.0,
        objective_value=opt_result.objective_value if opt_result else None,
        locked=state.locked_assignment(),
        raw_source_df=wb.raw_df if wb else None,
    )
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=shibutz_talmidot.xlsx"},
    )
