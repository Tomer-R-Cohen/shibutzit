from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Response

from src.export_excel import export_template_excel, export_to_excel

from ..session_store import store
from ..solver_inputs import build_solver_inputs

router = APIRouter()


@router.get("/api/export-template.xlsx")
def export_template_xlsx(x_session_id: str = Header(...)):
    """The fill-in workbook: base fields plus one column per rule discussed
    in chat that still needs data behind it. Works with or without a
    workbook already loaded -- see export_template_excel."""
    sess = store.get_or_create(x_session_id)
    raw_df = sess.loaded_wb.raw_df if sess.loaded_wb else None
    data = export_template_excel(raw_df, sess.data_requirements, sess.dataset_schema)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=shibutz_tavnit.xlsx"},
    )


@router.get("/api/export.xlsx")
def export_xlsx(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    if sess.adjustment_state is None:
        raise HTTPException(status_code=409, detail="אין שיבוץ להצגה - יש להריץ אופטימיזציה תחילה.")
    current_version = next((v for v in sess.assignment_versions if v.id == sess.current_version_id), None)
    if current_version is None or not current_version.approved:
        raise HTTPException(
            status_code=409,
            detail="יש לאשר את גרסת השיבוץ הנוכחית לפני הורדת קובץ סופי.",
        )
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    state = sess.adjustment_state
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    unmatched_df = sess.unmatched_df
    opt_result = sess.opt_result
    wb = sess.loaded_wb
    manually_adjusted = sess.result_mode == "manual"

    import pandas as pd

    data = export_to_excel(
        df,
        state.assignment,
        matched,
        cfg,
        constraints,
        unmatched_df if unmatched_df is not None else pd.DataFrame(),
        solver_status="MANUAL" if manually_adjusted else (opt_result.status_name if opt_result else ""),
        solver_wall_time=0.0 if manually_adjusted else (opt_result.wall_time_seconds if opt_result else 0.0),
        objective_value=None if manually_adjusted else (opt_result.objective_value if opt_result else None),
        locked=state.locked_assignment(),
        raw_source_df=wb.raw_df if wb else None,
    )
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=shibutz_talmidot.xlsx"},
    )
