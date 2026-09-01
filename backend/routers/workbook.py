from __future__ import annotations

import io
import os

import pandas as pd
from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_SCHOOL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_LABELS_HE,
    FIELD_STUDENT_ID,
    OPTIONAL_MANUAL_FIELDS,
    REQUIRED_FIELDS,
    ColumnMapping,
    apply_mapping,
    build_empty_manual_frame,
    guess_mapping,
)
from src.constraints import Constraint, capacity_range_label_hebrew
from src.dataset_schema import attach_extra_columns, detect_extra_columns
from src.excel_loader import (
    DEFAULT_FIRST_DATA_ROW_1INDEXED,
    DEFAULT_HEADER_ROW_1INDEXED,
    DEFAULT_LAST_DATA_ROW_1INDEXED,
    DEFAULT_WORKBOOK_PATH,
    ExcelLoadError,
    load_workbook,
)

from ..data_edits import DataEditError, apply_confirmed_student_edit, apply_student_data_edits, normalize_student_value
from ..schemas import LoadWorkbookRequest, MappingSetRequest
from ..session_store import _safe_name, store
from ..solver_inputs import ensure_defaults_seeded, sync_class_size_bounds
from ..utils import df_records, require

router = APIRouter()

# Generous for a ~200-row roster spreadsheet; guards against an accidental
# huge upload being read fully into memory.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


# When the data contains zero students of a category, requiring a per-class
# minimum for it is mathematically impossible and makes every solve infeasible
# (e.g. the source workbook has no שילוב/ח"מ columns, so those read as 0). Lower
# such a minimum to 0 so the default flow produces an assignment. We only ever
# lower a minimum, never raise it, so a user's own settings for categories that
# do exist are left untouched.
_MIN_FIELDS = [
    (FIELD_INCLUSION, "שילוב"),
    (FIELD_HAMAR, 'ח"מ'),
    (FIELD_ETHIOPIAN_ORIGIN, "מוצא אתיופי"),
]


def clamp_zero_minimums(constraints: list[Constraint], df) -> list[str]:
    adjusted: list[str] = []
    for field_name, label in _MIN_FIELDS:
        if field_name not in df.columns or int(df[field_name].sum()) != 0:
            continue
        for c in constraints:
            group = c.args.get("group", {})
            if c.type == "capacity" and group.get("kind") == "field" and group.get("field") == field_name:
                if (c.args.get("min") or 0) > 0:
                    c.args["min"] = 0
                    c.label_hebrew = capacity_range_label_hebrew(field_name, 0, c.args.get("max"))
                    adjusted.append(label)
    return adjusted


def _header_candidate(preview: pd.DataFrame) -> tuple[int, float]:
    """Return a zero-based header row and confidence score for one sheet."""
    best_known_row = 0
    best_known_score = 0
    for row_index, row in preview.iterrows():
        columns = [str(value).strip() for value in row.tolist() if pd.notna(value) and str(value).strip()]
        if not columns:
            continue
        mapping = guess_mapping(columns)
        score = sum(source is not None for source in mapping.mapping.values())
        if score > best_known_score:
            best_known_row = int(row_index)
            best_known_score = score

    if best_known_score >= 2:
        return best_known_row, 1000.0 + best_known_score * 100 - best_known_row

    # Generic workbooks may use unfamiliar labels. A header is usually a
    # string-heavy row with at least two cells followed by similarly dense
    # data rows. Prefer a wider, earlier table over a cover/title block.
    best_generic_row = 0
    best_generic_score = float("-inf")
    for row_index, row in preview.iterrows():
        values = [value for value in row.tolist() if pd.notna(value) and str(value).strip()]
        if len(values) < 2:
            continue
        text_ratio = sum(isinstance(value, str) for value in values) / len(values)
        if text_ratio < 0.6:
            continue
        minimum_data_cells = max(2, int(len(values) * 0.5))
        following = preview.iloc[int(row_index) + 1 : int(row_index) + 4]
        dense_following = sum(
            1
            for _, candidate in following.iterrows()
            if sum(pd.notna(value) and bool(str(value).strip()) for value in candidate.tolist()) >= minimum_data_cells
        )
        if dense_following == 0:
            continue
        score = len(values) * 10 + dense_following * 4 + text_ratio - int(row_index) * 0.01
        if score > best_generic_score:
            best_generic_row = int(row_index)
            best_generic_score = score

    return best_generic_row, best_generic_score if best_generic_score != float("-inf") else 0.0


def _detect_uploaded_table(path: str) -> tuple[str | None, int, int]:
    """Find a likely sheet and header without imposing the legacy layout.

    Known school-workbook labels are strong evidence. If none are found, a
    string-heavy table followed by data is selected. This avoids treating an
    instruction/cover sheet or title row as the student table.
    """
    try:
        with pd.ExcelFile(path, engine="openpyxl") as workbook:
            sheets = list(workbook.sheet_names)
    except Exception:
        return None, 1, 2

    best_sheet = sheets[0] if sheets else None
    best_row = 0
    best_score = float("-inf")
    for sheet in sheets:
        try:
            preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=40, engine="openpyxl")
        except Exception:
            continue
        row, score = _header_candidate(preview)
        if score > best_score:
            best_sheet, best_row, best_score = sheet, row, score

    header_row = best_row + 1
    return best_sheet, header_row, header_row + 1


@router.post("/api/workbook/load")
def load_workbook_endpoint(
    header_row: int = DEFAULT_HEADER_ROW_1INDEXED,
    first_data_row: int = DEFAULT_FIRST_DATA_ROW_1INDEXED,
    last_data_row: int = DEFAULT_LAST_DATA_ROW_1INDEXED,
    use_default: bool = True,
    file: UploadFile | None = File(default=None),
    x_session_id: str = Header(...),
):
    sess = store.get_or_create(x_session_id)
    path = DEFAULT_WORKBOOK_PATH
    detected_sheet: str | None = None
    if not use_default and file is not None:
        os.makedirs("sample_data", exist_ok=True)
        # Per-session filename: two sessions uploading around the same time
        # must not read back each other's file.
        tmp_path = os.path.join("sample_data", f"_uploaded_tmp_{_safe_name(x_session_id)}.xlsx")
        content = file.file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="הקובץ גדול מדי.")
        with open(tmp_path, "wb") as f:
            f.write(content)
        path = tmp_path
        if header_row <= 0 or first_data_row <= 0:
            detected_sheet, header_row, first_data_row = _detect_uploaded_table(path)
    try:
        wb = load_workbook(
            path,
            sheet_name=detected_sheet,
            header_row_1indexed=int(header_row),
            first_data_row_1indexed=int(first_data_row),
            last_data_row_1indexed=int(last_data_row) if last_data_row else None,
        )
    except ExcelLoadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sess.loaded_wb = wb
    sess.source_path = os.path.abspath(path)
    sess.source_filename = file.filename if file is not None and not use_default else os.path.basename(path)
    sess.source_load_options = {
        "header_row": int(header_row),
        "first_data_row": int(first_data_row),
        "last_data_row": int(last_data_row) if last_data_row else None,
    }
    sess.mapped_df = None
    sess.student_data_edits = {}
    sess.assignment_versions = []
    sess.current_version_id = None
    sess.mark_inputs_changed(data_changed=True, clear_result=True)
    # Keep a persisted mapping only when every referenced source column is
    # present in the newly loaded workbook. Otherwise force a fresh guess.
    if sess.col_mapping is not None:
        available = set(wb.raw_df.columns)
        referenced = {c for c in sess.col_mapping.mapping.values() if c is not None}
        if not referenced.issubset(available):
            sess.col_mapping = None
    return {
        "row_count": len(wb.raw_df),
        "active_sheet": wb.active_sheet,
        "sheet_names": wb.sheet_names,
        "notes": wb.notes,
        "columns": [str(c) for c in wb.raw_df.columns],
    }


@router.get("/api/workbook/preview")
def preview_workbook(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    wb = require(sess.loaded_wb, "יש לטעון קובץ תחילה (שלב 1).")
    return {
        "sheet_names": wb.sheet_names,
        "columns": [str(c) for c in wb.raw_df.columns],
        "total_rows": len(wb.raw_df),
        "rows": df_records(wb.raw_df.head(30)),
    }


@router.get("/api/mapping/guess")
def get_mapping_guess(x_session_id: str = Header(...)):
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
def apply_mapping_endpoint(req: MappingSetRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    wb = require(sess.loaded_wb, "יש לטעון קובץ תחילה (שלב 1).")

    cm = ColumnMapping()
    for field_name, col in req.mapping.items():
        if field_name in req.manual_fields and field_name in OPTIONAL_MANUAL_FIELDS:
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

    # Seed an empty manual-entry table on first mapping. When one already exists
    # (typed earlier, or restored from disk), fold it back into the mapped table
    # so re-applying the mapping — which the frontend does on every load — never
    # drops previously entered category data.
    if sess.manual_entry_df is None:
        sess.manual_entry_df = build_empty_manual_frame(mapped[FIELD_STUDENT_ID].tolist())
    else:
        try:
            mapped = apply_mapping(wb.raw_df, cm, manual_df=sess.manual_entry_df)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Everything else in the workbook. Detected from the values, attached to
    # the mapped frame under `x_`-prefixed keys, and described on the session
    # so the chat can write rules about columns this app has never heard of.
    # No defaults are seeded for them: what "מיוחד" means is the counselor's
    # call, not something to guess at import time.
    mapped_sources = {c for c in cm.mapping.values() if c}
    sess.dataset_schema = detect_extra_columns(wb.raw_df, mapped_sources)
    if sess.dataset_schema.extras:
        try:
            mapped = attach_extra_columns(mapped, wb.raw_df, sess.dataset_schema)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    mapped = apply_student_data_edits(mapped, sess.student_data_edits)
    sess.mapped_df = mapped
    manual_needed = [f for f in OPTIONAL_MANUAL_FIELDS if f in cm.manual_fields]
    ensure_defaults_seeded(sess, mapped)
    sync_class_size_bounds(sess, mapped)
    adjusted = clamp_zero_minimums(sess.constraints, mapped)
    sess.mark_inputs_changed(data_changed=True, clear_result=True)
    store.save(sess)

    return {
        "student_count": len(mapped),
        "manual_fields_needed": manual_needed,
        "manual_entry": df_records(sess.manual_entry_df),
        "adjusted_minimums": adjusted,
    }


@router.get("/api/students")
def get_students(x_session_id: str = Header(...)):
    """The full mapped student list (file-derived fields + manually entered
    category fields), for the data-screen list/editor."""
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים תחילה טעינה ומיפוי.")
    rows = df_records(df)
    for row in rows:
        student_id = int(row[FIELD_STUDENT_ID])
        row["_project_edited_fields"] = sorted(sess.student_data_edits.get(student_id, {}).keys())
    return {"rows": rows, "count": len(df)}


@router.patch("/api/students/{student_id}")
def update_student_data(student_id: int, payload: dict, x_session_id: str = Header(...)):
    """Correct a visible roster value in the project's working copy.

    The uploaded workbook remains immutable; the same audited overlay used
    by conversational edits becomes authoritative for validation and solves.
    Only the two ordinary fields exposed by the roster correction UI are
    accepted here. Sensitive support-category edits keep their existing path.
    """
    field = str(payload.get("field") or "")
    if field not in {FIELD_CURRENT_SCHOOL, FIELD_ACADEMIC_LEVEL}:
        raise HTTPException(status_code=400, detail="ניתן לתקן במסך זה רק בית ספר נוכחי או הישגים לימודיים.")
    sess = store.get_or_create(x_session_id)
    try:
        old_value, new_value = apply_confirmed_student_edit(sess, student_id, field, payload.get("value"))
    except DataEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.save(sess)
    return {
        "student_id": student_id,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "remaining_issues": len(sess.validation_report.issues),
        "result_state": sess.result_state(),
    }


@router.get("/api/mapping/manual-entry")
def get_manual_entry(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.manual_entry_df, "יש להשלים תחילה את שלב המיפוי.")
    # Provide id -> display name so the editor can show who each row is,
    # without making the name an editable/round-tripped manual field.
    names: dict[str, str] = {}
    mapped = sess.mapped_df
    if mapped is not None and FIELD_STUDENT_ID in mapped.columns:
        from src.column_mapping import FIELD_FIRST_NAME, FIELD_LAST_NAME

        for _, row in mapped.iterrows():
            first = str(row.get(FIELD_FIRST_NAME, "") or "").strip()
            last = str(row.get(FIELD_LAST_NAME, "") or "").strip()
            names[str(row[FIELD_STUDENT_ID])] = f"{first} {last}".strip()
    return {"rows": df_records(df), "names": names}


@router.post("/api/mapping/manual-entry")
def update_manual_entry(payload: dict, x_session_id: str = Header(...)):
    """Accepts {"rows": [...]} and replaces the manual-entry table, then
    reapplies mapping onto mapped_df."""
    sess = store.get_or_create(x_session_id)
    wb = require(sess.loaded_wb, "יש לטעון קובץ תחילה.")
    cm = require(sess.col_mapping, "יש להשלים מיפוי עמודות תחילה.")

    rows = payload.get("rows", [])
    new_df = pd.DataFrame(rows) if rows else sess.manual_entry_df
    # Visual roster edits and conversational edits share the same project
    # overlay. If a source-mapped optional field is changed in the UI, keep
    # that correction instead of letting the immutable source overwrite it.
    if rows and sess.mapped_df is not None:
        for incoming in rows:
            try:
                student_id = int(incoming[FIELD_STUDENT_ID])
            except (KeyError, TypeError, ValueError):
                continue
            current = sess.mapped_df.loc[sess.mapped_df[FIELD_STUDENT_ID] == student_id]
            if current.empty:
                continue
            for field in OPTIONAL_MANUAL_FIELDS:
                if field not in incoming or field not in sess.mapped_df.columns:
                    continue
                try:
                    normalized = normalize_student_value(sess.mapped_df, field, incoming[field])
                except DataEditError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                old_value = current.iloc[0][field]
                if pd.isna(old_value) or old_value != normalized:
                    sess.student_data_edits.setdefault(student_id, {})[field] = normalized
    sess.manual_entry_df = new_df

    try:
        mapped = apply_mapping(wb.raw_df, cm, manual_df=new_df)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    if sess.dataset_schema.extras:
        try:
            mapped = attach_extra_columns(mapped, wb.raw_df, sess.dataset_schema)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    mapped = apply_student_data_edits(mapped, sess.student_data_edits)
    sess.mapped_df = mapped
    ensure_defaults_seeded(sess, mapped)
    clamp_zero_minimums(sess.constraints, mapped)
    sess.mark_inputs_changed(data_changed=True, clear_result=True)
    store.save(sess)
    return {"student_count": len(mapped), "manual_entry": df_records(new_df)}


@router.post("/api/mapping/manual-entry/import")
def import_manual_entry(file: UploadFile = File(...), x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    require(sess.loaded_wb, "יש לטעון קובץ תחילה.")
    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="הקובץ גדול מדי.")
    try:
        if file.filename and file.filename.endswith(".csv"):
            imported = pd.read_csv(io.BytesIO(content))
        else:
            imported = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"שגיאה בייבוא: {e}")
    sess.manual_entry_df = imported
    cm = require(sess.col_mapping, "×™×© ×œ×”×©×œ×™× ×ž×™×¤×•×™ ×¢×ž×•×“×•×ª ×ª×—×™×œ×”.")
    try:
        mapped = apply_mapping(sess.loaded_wb.raw_df, cm, manual_df=imported)
        if sess.dataset_schema.extras:
            mapped = attach_extra_columns(mapped, sess.loaded_wb.raw_df, sess.dataset_schema)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"×©×’×™××” ×‘×”×—×œ×ª ×”×™×™×‘×•×: {e}")
    mapped = apply_student_data_edits(mapped, sess.student_data_edits)
    sess.mapped_df = mapped
    ensure_defaults_seeded(sess, mapped)
    clamp_zero_minimums(sess.constraints, mapped)
    sess.mark_inputs_changed(data_changed=True, clear_result=True)
    store.save(sess)
    return {"rows": df_records(imported)}
