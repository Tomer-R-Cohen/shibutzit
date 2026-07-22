from __future__ import annotations

import io
import os

import pandas as pd
from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from src.column_mapping import (
    FIELD_LABELS_HE,
    FIELD_STUDENT_ID,
    OPTIONAL_MANUAL_FIELDS,
    REQUIRED_FIELDS,
    ColumnMapping,
    apply_mapping,
    build_empty_manual_frame,
    guess_mapping,
)
from src.excel_loader import DEFAULT_WORKBOOK_PATH, ExcelLoadError, load_workbook

from ..schemas import LoadWorkbookRequest, MappingSetRequest
from ..session_store import store
from ..utils import df_records, require

router = APIRouter()


@router.post("/api/workbook/load")
async def load_workbook_endpoint(
    header_row: int = 4,
    first_data_row: int = 5,
    last_data_row: int = 221,
    use_default: bool = True,
    file: UploadFile | None = File(default=None),
    x_session_id: str = Header(...),
):
    sess = store.get_or_create(x_session_id)
    path = DEFAULT_WORKBOOK_PATH
    if not use_default and file is not None:
        os.makedirs("sample_data", exist_ok=True)
        tmp_path = os.path.join("sample_data", "_uploaded_tmp.xlsx")
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        path = tmp_path
    try:
        wb = load_workbook(
            path,
            header_row_1indexed=int(header_row),
            first_data_row_1indexed=int(first_data_row),
            last_data_row_1indexed=int(last_data_row) if last_data_row else None,
        )
    except ExcelLoadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sess.loaded_wb = wb
    return {
        "row_count": len(wb.raw_df),
        "active_sheet": wb.active_sheet,
        "sheet_names": wb.sheet_names,
        "notes": wb.notes,
        "columns": [str(c) for c in wb.raw_df.columns],
    }


@router.get("/api/workbook/preview")
async def preview_workbook(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    wb = require(sess.loaded_wb, "יש לטעון קובץ תחילה (שלב 1).")
    return {
        "sheet_names": wb.sheet_names,
        "columns": [str(c) for c in wb.raw_df.columns],
        "total_rows": len(wb.raw_df),
        "rows": df_records(wb.raw_df.head(30)),
    }


@router.get("/api/mapping/guess")
async def get_mapping_guess(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    wb = require(sess.loaded_wb, "יש לטעון קובץ תחילה (שלב 1).")
    if sess.col_mapping is None:
        sess.col_mapping = guess_mapping(list(wb.raw_df.columns), wb.raw_df)
    cm = sess.col_mapping
    return {
        "columns": [str(c) for c in wb.raw_df.columns],
        "required_fields": REQUIRED_FIELDS,
        "optional_fields": OPTIONAL_MANUAL_FIELDS,
        "labels": FIELD_LABELS_HE,
        "mapping": cm.mapping,
        "manual_fields": sorted(cm.manual_fields),
        "problems": cm.validate(),
    }


@router.post("/api/mapping/apply")
async def apply_mapping_endpoint(req: MappingSetRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    wb = require(sess.loaded_wb, "יש לטעון קובץ תחילה (שלב 1).")

    cm = ColumnMapping()
    for field_name, col in req.mapping.items():
        if field_name in req.manual_fields or col is None:
            cm.mark_manual(field_name)
        else:
            cm.set(field_name, col)
    sess.col_mapping = cm

    problems = cm.validate()
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))

    try:
        mapped = apply_mapping(wb.raw_df, cm)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    sess.mapped_df = mapped
    manual_needed = [f for f in OPTIONAL_MANUAL_FIELDS if f in cm.manual_fields]
    if sess.manual_entry_df is None:
        sess.manual_entry_df = build_empty_manual_frame(mapped[FIELD_STUDENT_ID].tolist())

    return {
        "student_count": len(mapped),
        "manual_fields_needed": manual_needed,
        "manual_entry": df_records(sess.manual_entry_df),
    }


@router.get("/api/mapping/manual-entry")
async def get_manual_entry(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.manual_entry_df, "יש להשלים תחילה את שלב המיפוי.")
    return {"rows": df_records(df)}


@router.post("/api/mapping/manual-entry")
async def update_manual_entry(payload: dict, x_session_id: str = Header(...)):
    """Accepts {"rows": [...]} and replaces the manual-entry table, then
    reapplies mapping onto mapped_df."""
    sess = store.get_or_create(x_session_id)
    wb = require(sess.loaded_wb, "יש לטעון קובץ תחילה.")
    cm = require(sess.col_mapping, "יש להשלים מיפוי עמודות תחילה.")

    rows = payload.get("rows", [])
    new_df = pd.DataFrame(rows) if rows else sess.manual_entry_df
    sess.manual_entry_df = new_df

    try:
        mapped = apply_mapping(wb.raw_df, cm, manual_df=new_df)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    sess.mapped_df = mapped
    return {"student_count": len(mapped), "manual_entry": df_records(new_df)}


@router.post("/api/mapping/manual-entry/import")
async def import_manual_entry(file: UploadFile = File(...), x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    require(sess.loaded_wb, "יש לטעון קובץ תחילה.")
    content = await file.read()
    try:
        if file.filename and file.filename.endswith(".csv"):
            imported = pd.read_csv(io.BytesIO(content))
        else:
            imported = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"שגיאה בייבוא: {e}")
    sess.manual_entry_df = imported
    return {"rows": df_records(imported)}
