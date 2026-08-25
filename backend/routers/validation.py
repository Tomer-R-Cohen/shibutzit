from __future__ import annotations

from fastapi import APIRouter, Header

from src.feasibility import analyze_feasibility
from src.friendship_graph import resolve_requests, unmatched_report
from src.validation import validate_students

from ..session_store import store
from ..solver_inputs import build_solver_inputs
from ..utils import df_records, require

router = APIRouter()


@router.get("/api/validation")
def get_validation(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים את מיפוי העמודות תחילה (שלב 3).")
    report = validate_students(df)
    sess.validation_report = report
    return {
        "has_errors": report.has_errors(),
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
        "issues": df_records(report.to_dataframe()),
    }


@router.get("/api/friendship/diagnostics")
def get_friendship_diagnostics(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים את מיפוי העמודות תחילה (שלב 3).")
    result = resolve_requests(df)
    sess.friendship_result = result
    unmatched_df = unmatched_report(result)
    sess.unmatched_df = unmatched_df
    return {
        "matched_count": sum(len(v) for v in result.matched.values()),
        "unmatched_count": len(result.unmatched),
        "ambiguous_count": len(result.ambiguous),
        "unmatched_rows": df_records(unmatched_df),
    }


@router.get("/api/feasibility")
def get_feasibility(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים שלבים קודמים תחילה.")
    cfg, constraints = build_solver_inputs(sess)
    report = analyze_feasibility(df, constraints, cfg.num_classes)
    sess.feasibility_report = report
    from src.column_mapping import (
        FIELD_CURRENT_CLASS,
        FIELD_DIFFERENTIAL,
        FIELD_ETHIOPIAN_ORIGIN,
        FIELD_HAMAR,
        FIELD_INCLUSION,
    )

    current_class_dist = df[FIELD_CURRENT_CLASS].value_counts().to_dict()
    return {
        "total_students": len(df),
        "ethiopian_count": int(df[FIELD_ETHIOPIAN_ORIGIN].sum()),
        "differential_count": int(df[FIELD_DIFFERENTIAL].sum()),
        "inclusion_count": int(df[FIELD_INCLUSION].sum()),
        "hamar_count": int(df[FIELD_HAMAR].sum()),
        "current_class_distribution": {str(k): int(v) for k, v in current_class_dist.items()},
        "all_feasible": report.all_feasible(),
        "findings": df_records(report.to_dataframe()),
    }
