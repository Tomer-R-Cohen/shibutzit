"""Excel export of the full assignment result, never touching the source file."""

from __future__ import annotations

import io
from dataclasses import asdict
from typing import Optional

import pandas as pd

from src.column_mapping import DEFAULT_GUESS_MAP, FIELD_STUDENT_ID
from src.constraints import Constraint
from src.data_requirements import DataRequirement, match_requirements
from src.dataset_schema import DatasetSchema
from src.metrics import class_overview_table, compute_global_metrics, student_assignment_table, violations_report
from src.optimizer import SolverConfig

_SOURCE_LABELS_HE = {"builtin_default": "ברירת מחדל", "chat": "צ'אט", "manual": "ידני"}


def _autofit_and_style(worksheet, df: pd.DataFrame, workbook, freeze_header=True):
    worksheet.right_to_left()
    header_fmt = workbook.add_format({"bold": True, "bg_color": "#DDEBF7", "border": 1})
    for col_idx, col_name in enumerate(df.columns):
        worksheet.write(0, col_idx, col_name, header_fmt)
        max_len = max([len(str(col_name))] + [len(str(v)) for v in df[col_name].astype(str).head(200)])
        worksheet.set_column(col_idx, col_idx, min(max_len + 2, 45))
    if freeze_header:
        worksheet.freeze_panes(1, 0)
    if len(df) > 0:
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)


def export_to_excel(
    df: pd.DataFrame,
    assignment: dict[int, int],
    friendship_matched: dict[int, list[int]],
    config: SolverConfig,
    constraints: list[Constraint],
    unmatched_df: pd.DataFrame,
    solver_status: str = "",
    solver_wall_time: float = 0.0,
    objective_value=None,
    locked: dict[int, int] | None = None,
    raw_source_df: pd.DataFrame | None = None,
) -> bytes:
    """Build the full multi-sheet Excel export and return its bytes.

    Sheets: שיבוץ לפי כיתות, רשימת תלמידות, מדדים, חריגות, בקשות חברות,
    הגדרות, נתוני מקור.
    """
    locked = locked or {}
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        workbook = writer.book

        class_df = class_overview_table(df, assignment, friendship_matched, constraints, config.num_classes)
        class_df.to_excel(writer, sheet_name="שיבוץ לפי כיתות", index=False)
        _autofit_and_style(writer.sheets["שיבוץ לפי כיתות"], class_df, workbook)

        student_df = student_assignment_table(df, assignment, friendship_matched, locked)
        student_df.to_excel(writer, sheet_name="רשימת תלמידות", index=False)
        ws_students = writer.sheets["רשימת תלמידות"]
        _autofit_and_style(ws_students, student_df, workbook)
        if "אזהרות" in student_df.columns:
            warn_col = student_df.columns.get_loc("אזהרות")
            red_fmt = workbook.add_format({"bg_color": "#FFC7CE"})
            ws_students.conditional_format(
                1, warn_col, len(student_df), warn_col,
                {"type": "no_blanks", "format": red_fmt},
            )

        gm = compute_global_metrics(
            df, assignment, friendship_matched, constraints, config.num_classes,
            config.denominator_all_students, solver_status, solver_wall_time, objective_value,
        )
        metrics_rows = [
            {"מדד": k, "ערך": v}
            for k, v in {
                "סה\"כ תלמידות": gm.total_students,
                "מספר כיתות": gm.num_classes,
                "גדלי כיתות": str(gm.class_sizes),
                "גודל מינימלי": gm.class_size_min,
                "גודל מקסימלי": gm.class_size_max,
                "פער גדלים": gm.class_size_spread,
                "פער בהרכב הלימודי": gm.academic_level_spread,
                "תלמידות עם בקשות חברות": gm.students_with_requests,
                "% חברות הדדית": gm.mutual_satisfied_pct,
                "% 2+ חברות מבוקשות": gm.two_friends_satisfied_pct,
                "בקשות מסופקות במלואן": gm.satisfied_requests,
                "בקשות מסופקות חלקית": gm.partial_requests,
                "בקשות לא מסופקות": gm.unsatisfied_requests,
                "סה\"כ חריגות": gm.violations_count,
                "סטטוס פותר": gm.solver_status,
                "זמן ריצה (שניות)": gm.solver_wall_time,
                "ערך פונקציית מטרה": gm.objective_value,
            }.items()
        ]
        metrics_df = pd.DataFrame(metrics_rows)
        metrics_df.to_excel(writer, sheet_name="מדדים", index=False)
        _autofit_and_style(writer.sheets["מדדים"], metrics_df, workbook)

        viol_df = violations_report(df, assignment, constraints, config.num_classes)
        if viol_df.empty:
            viol_df = pd.DataFrame([{"כלל": "אין חריגות", "כיתה": "", "צפוי": "", "בפועל": "", "חומרה": "", "קשה/רכה": "", "תיקון מוצע": ""}])
        viol_df.to_excel(writer, sheet_name="חריגות", index=False)
        ws_viol = writer.sheets["חריגות"]
        _autofit_and_style(ws_viol, viol_df, workbook)
        if "חומרה" in viol_df.columns:
            sev_col = viol_df.columns.get_loc("חומרה")
            red_fmt = workbook.add_format({"bg_color": "#FFC7CE"})
            ws_viol.conditional_format(
                1, sev_col, len(viol_df), sev_col,
                {"type": "cell", "criteria": "==", "value": '"גבוהה"', "format": red_fmt},
            )

        friend_rows = []
        for sid, targets in friendship_matched.items():
            for t in targets:
                friend_rows.append({
                    "מבקשת": sid,
                    "מבוקשת": t,
                    "הדדית": t in friendship_matched and sid in friendship_matched.get(t, []),
                })
        friend_df = pd.DataFrame(friend_rows) if friend_rows else pd.DataFrame(columns=["מבקשת", "מבוקשת", "הדדית"])
        friend_df.to_excel(writer, sheet_name="בקשות חברות", index=False)
        _autofit_and_style(writer.sheets["בקשות חברות"], friend_df, workbook)

        if not unmatched_df.empty:
            unmatched_df.to_excel(writer, sheet_name="בקשות חברות", index=False, startrow=len(friend_df) + 2)

        cfg_dict = asdict(config)
        cfg_df = pd.DataFrame([{"פרמטר": k, "ערך": v} for k, v in cfg_dict.items()])
        cfg_df.to_excel(writer, sheet_name="הגדרות", index=False)
        _autofit_and_style(writer.sheets["הגדרות"], cfg_df, workbook)

        constraints_rows = [
            {
                "מזהה": c.id,
                "תיאור": c.label_hebrew,
                "סוג": c.type,
                "קשה/רכה": "קשה" if c.hard else "רכה",
                "מקור": _SOURCE_LABELS_HE.get(c.source, c.source),
                "פעיל": "כן" if c.active else "לא",
            }
            for c in constraints
        ]
        constraints_df = pd.DataFrame(
            constraints_rows or [],
            columns=["מזהה", "תיאור", "סוג", "קשה/רכה", "מקור", "פעיל"],
        )
        constraints_df.to_excel(writer, sheet_name="הגדרות", index=False, startrow=len(cfg_df) + 2)

        if raw_source_df is not None:
            raw_export = raw_source_df.copy()
            raw_export.to_excel(writer, sheet_name="נתוני מקור", index=False)
            _autofit_and_style(writer.sheets["נתוני מקור"], raw_export, workbook)

    return buffer.getvalue()


def export_template_excel(
    raw_df: Optional[pd.DataFrame],
    requirements: list[DataRequirement],
    schema: Optional[DatasetSchema],
) -> bytes:
    """The counselor's workbook to fill in, updated for whatever the
    planning conversation has decided since it was last exported.

    With no workbook loaded yet, this is a blank header row: the base
    fields the app always needs plus one column per rule discussed so far
    that needs data behind it. With one already loaded, existing rows and
    columns are carried over untouched and only the still-missing
    requirement columns are appended empty -- so filling this in is just
    adding what's new, not redoing the whole file.
    """
    missing_labels = [m["label"] for m in match_requirements(requirements, schema) if not m["satisfied"]]

    if raw_df is not None:
        template_df = raw_df.copy()
        for label in missing_labels:
            if label not in template_df.columns:
                template_df[label] = None
    else:
        columns = list(DEFAULT_GUESS_MAP.values()) + missing_labels
        template_df = pd.DataFrame(columns=columns)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        workbook = writer.book
        template_df.to_excel(writer, sheet_name="תבנית למילוי", index=False)
        worksheet = writer.sheets["תבנית למילוי"]
        _autofit_and_style(worksheet, template_df, workbook)
        if missing_labels:
            new_col_fmt = workbook.add_format({"bold": True, "bg_color": "#FFF2CC", "border": 1})
            for label in missing_labels:
                col_idx = list(template_df.columns).index(label)
                worksheet.write(0, col_idx, label, new_col_fmt)

    return buffer.getvalue()
