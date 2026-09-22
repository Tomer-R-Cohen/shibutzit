from __future__ import annotations

import logging
import math
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException

from src.column_mapping import (
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_LABELS_HE,
    FIELD_STUDENT_ID,
)
from src.constraints import Constraint, capacity_range_label_hebrew, locked_constraints, resolve_group_members
from src.decision_support import assignment_distance, generate_portfolio, negotiation_question, profile_constraints, verify_assignment
from src.feasibility import analyze_feasibility
from src.manual_adjustments import AdjustmentState, ManualAdjustmentError, apply_editor_dataframe
from src.metrics import class_overview_table, compute_global_metrics, student_assignment_table, violations_report
from src.optimizer import OptimizationError, OptimizationResult, SolverConfig, optimize
from src.friendship_graph import resolve_requests, unmatched_report
from src.validation import validate_students

from ..llm.narration import narrate_infeasibility, narrate_result, relaxation_candidate
from ..schemas import LockingRequest, MoveStudentRequest, SelectDecisionOptionRequest
from ..session_store import AssignmentVersion, PendingProposal, Session, store
from ..solver_inputs import build_locked_constraints, build_solver_inputs
from ..utils import df_records, require

router = APIRouter()
logger = logging.getLogger(__name__)


_REVIEW_GROUP_LABELS = {
    FIELD_DIFFERENTIAL: "דיפרנציאליות",
    FIELD_ETHIOPIAN_ORIGIN: "מוצא אתיופי",
    FIELD_INCLUSION: "שילוב",
    FIELD_HAMAR: 'ח"מ',
}


def _prefer_proven_arithmetic_conflicts(
    result: OptimizationResult,
    df,
    constraints: list[Constraint],
    num_classes: int,
) -> None:
    """Replace a broad solver core with independently proven capacity failures.

    CP-SAT returns a *sufficient* infeasibility core, which can legitimately
    include several assumptions even when one capacity rule is impossible on
    its own. For the counselor-facing explanation, closed-form population
    arithmetic is stronger and more specific evidence. Keep the solver core
    untouched when no rule can be proven impossible independently.
    """
    if result.is_feasible:
        return
    findings = analyze_feasibility(df, constraints, num_classes).infeasible
    proven = [finding for finding in findings if finding.constraint_id]
    if not proven:
        return
    result.conflicting_constraint_ids = list(dict.fromkeys(finding.constraint_id for finding in proven))
    result.infeasibility_notes = [finding.message for finding in proven]


def _review_groups(sess: Session, constraints: list[Constraint]) -> list[dict]:
    """Active capacity groups the counselor must be able to inspect on the board.

    The solver accepts arbitrary workbook fields, so a fixed four-category
    response would hide school-specific rules precisely where their outcome
    needs to be reviewed. Member ids are already part of the counselor's
    trusted session response and let the frontend count/filter without
    duplicating group-resolution semantics.
    """
    df = sess.mapped_df
    if df is None:
        return []
    extras = {column.key: column.label for column in sess.dataset_schema.extras}
    groups = []
    for constraint in constraints:
        if not constraint.active or constraint.type != "capacity":
            continue
        group = constraint.args.get("group") or {}
        if group.get("kind") == "all":
            continue
        field = group.get("field")
        base_label = _REVIEW_GROUP_LABELS.get(field) or extras.get(field) or group.get("label") or FIELD_LABELS_HE.get(field) or field
        if group.get("kind") == "field_value":
            label = f"{base_label}: {group.get('value')}"
        else:
            label = base_label or constraint.label_hebrew
        groups.append(
            {
                "id": constraint.id,
                "label": str(label),
                "hard": constraint.hard,
                "min": constraint.args.get("min"),
                "max": constraint.args.get("max"),
                "member_ids": [int(student_id) for student_id in resolve_group_members(df, group)],
            }
        )
    return groups


def _create_version(sess: Session, cfg, constraints: list[Constraint], reason: str, mode: str = "solver") -> AssignmentVersion:
    state = sess.adjustment_state
    result = sess.opt_result
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    gm = compute_global_metrics(
        sess.mapped_df,
        state.assignment,
        matched,
        constraints,
        cfg.num_classes,
        cfg.denominator_all_students,
        result.status_name,
        result.wall_time_seconds,
        result.objective_value,
    )
    result_snapshot = asdict(result)
    result_snapshot["assignment"] = dict(state.assignment)
    version = AssignmentVersion(
        number=(sess.assignment_versions[-1].number + 1) if sess.assignment_versions else 1,
        reason=reason,
        assignment=dict(state.assignment),
        locked_assignment=state.locked_assignment(),
        run_config=asdict(cfg),
        constraints=[asdict(c) for c in sess.constraints],
        metrics=asdict(gm),
        result=result_snapshot,
        input_revision=sess.input_revision,
        mode="manual" if mode == "manual" else "solver",
    )
    sess.assignment_versions.append(version)
    sess.assignment_versions = sess.assignment_versions[-50:]
    sess.current_version_id = version.id
    store.save(sess)
    return version


def _narrate_if_infeasible(
    sess: Session,
    result: OptimizationResult,
    constraints: list[Constraint],
    relaxation: dict | None = None,
) -> str | None:
    """Backend-triggered (not user-triggered): the conflict is already
    known deterministically via `result.conflicting_constraint_ids` -- this
    only phrases it and records it in the chat panel so it shows up
    alongside any manual constraint editing the counselor does next."""
    if result.is_feasible:
        return None
    conflicting = [c for c in constraints if c.id in result.conflicting_constraint_ids]
    if relaxation and (relaxation.get("evidence") or {}).get("basis") == "measured_trial":
        explanation = "לא ניתן לקיים את כל כללי החובה כפי שהם מוגדרים עכשיו. " + relaxation["summary_hebrew"]
    else:
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
    package = _arithmetic_relaxation_package(sess, constraints)
    if package is not None:
        sess.pending_proposal = package
        store.save(sess)
        return asdict(package)
    conflicting = [c for c in constraints if c.id in result.conflicting_constraint_ids]
    # Prefer the smallest numeric correction when a capacity rule is
    # impossible from the totals alone. Unlike converting a mandatory rule
    # to a preference, this keeps it mandatory and changes only the bound
    # that arithmetic proves cannot hold.
    ordered = sorted(conflicting, key=lambda constraint: constraint.source == "builtin_default")
    for candidate in ordered:
        numeric = _tested_numeric_relaxation(sess, candidate, constraints)
        if numeric is not None:
            sess.pending_proposal = numeric
            store.save(sess)
            return asdict(numeric)

    target = relaxation_candidate(conflicting)
    if target is None:
        return None

    proposal = PendingProposal(
        kind="modify",
        summary_hebrew=(
            f'הפיכת "{target.label_hebrew}" מכלל חובה להעדפה תסיר את הכלל מההתנגשות שהמנוע הוכיח. '
            "הכלל ימשיך להשפיע על השיבוץ, אך ייתכן שאחרי השינוי תתגלה התנגשות נוספת."
        ),
        target_constraint_id=target.id,
        changes={"hard": False},
        evidence={"basis": "solver_conflict", "trial_feasible": None, "changes_hard_rule": True},
    )
    sess.pending_proposal = proposal
    store.save(sess)
    return asdict(proposal)


def _arithmetic_relaxation_package(sess: Session, constraints: list[Constraint]) -> PendingProposal | None:
    """Collect every independently impossible mandatory capacity rule.

    A single-rule proposal followed by an automatic rerun creates a needless
    failure loop when several rules are already known to be impossible from
    the roster totals. Present those minimal arithmetic corrections as one
    atomic, explicitly approved package and run only after all are applied.
    """
    if sess.mapped_df is None:
        return None
    findings = analyze_feasibility(sess.mapped_df, constraints, sess.run_config.num_classes).infeasible
    proven_ids = list(dict.fromkeys(finding.constraint_id for finding in findings if finding.constraint_id))
    if len(proven_ids) < 2:
        return None

    class_count = sess.run_config.num_classes
    batch = []
    descriptions = []
    for constraint_id in proven_ids:
        target = next(
            (constraint for constraint in sess.constraints if constraint.id == constraint_id and constraint.active and constraint.hard),
            None,
        )
        if target is None or target.type != "capacity":
            continue
        try:
            group_count = len(resolve_group_members(sess.mapped_df, target.args["group"]))
        except Exception:
            continue
        old_min, old_max = target.args.get("min"), target.args.get("max")
        new_min, new_max = old_min, old_max
        if old_min is not None and old_min * class_count > group_count:
            new_min = group_count // class_count
        if old_max is not None and old_max * class_count < group_count:
            new_max = math.ceil(group_count / class_count)
        if (new_min, new_max) == (old_min, old_max):
            continue

        next_args = {**target.args, "min": new_min, "max": new_max}
        group = target.args.get("group") or {}
        field = group.get("field")
        if group.get("kind") == "all":
            new_label = f"גודל כיתה {new_min}–{new_max} תלמידות"
        elif group.get("kind") == "field" and field in {FIELD_ETHIOPIAN_ORIGIN, FIELD_INCLUSION, FIELD_HAMAR}:
            new_label = capacity_range_label_hebrew(field, new_min, new_max)
        elif group.get("kind") == "field" and field == FIELD_DIFFERENTIAL:
            new_label = f"עד {new_max} תלמידות דיפרנציאליות לכיתה"
        else:
            shown_min = new_min if new_min is not None else 0
            shown_max = new_max if new_max is not None else "ללא הגבלה"
            new_label = f"{target.label_hebrew} (טווח {shown_min}–{shown_max})"

        batch.append(
            {
                "constraint_id": target.id,
                "changes": {"args": next_args, "label_hebrew": new_label},
                "from": {"min": old_min, "max": old_max},
                "to": {"min": new_min, "max": new_max},
                "students_in_group": group_count,
            }
        )
        shown_old_min = old_min if old_min is not None else 0
        shown_old_max = old_max if old_max is not None else "ללא הגבלה"
        shown_new_min = new_min if new_min is not None else 0
        shown_new_max = new_max if new_max is not None else "ללא הגבלה"
        descriptions.append(
            f"{target.label_hebrew}: {shown_old_min}–{shown_old_max} → {shown_new_min}–{shown_new_max}"
        )

    if len(batch) < 2:
        return None
    summary = (
        f"מצאתי {len(batch)} כללי חובה שאינם אפשריים כל אחד בפני עצמו לפי מספר התלמידות. "
        "כדי לא להריץ שוב אחרי כל תיקון, אני מציעה להחיל יחד את קבוצת השינויים המזערית: "
        + "; ".join(descriptions)
        + ". שום שינוי לא יוחל לפני אישורך."
    )
    return PendingProposal(
        kind="modify",
        summary_hebrew=summary,
        changes={"batch": batch},
        evidence={
            "basis": "arithmetic_feasibility_package",
            "changes_hard_rule": True,
            "item_count": len(batch),
            "trial_feasible": None,
            "findings": [asdict(finding) for finding in findings if finding.constraint_id in proven_ids],
        },
    )


def _tested_numeric_relaxation(sess: Session, target: Constraint, constraints: list[Constraint]) -> PendingProposal | None:
    if target.type != "capacity" or not target.hard or sess.mapped_df is None:
        return None
    stored_target = next((constraint for constraint in sess.constraints if constraint.id == target.id), None)
    if stored_target is None:
        return None
    try:
        group_count = len(resolve_group_members(sess.mapped_df, target.args["group"]))
    except Exception:
        return None

    class_count = sess.run_config.num_classes
    old_min, old_max = target.args.get("min"), target.args.get("max")
    new_min, new_max = old_min, old_max
    arithmetic = None
    if old_min is not None and old_min * class_count > group_count:
        new_min = group_count // class_count
        arithmetic = (
            f"יש {group_count} תלמידות בקבוצה, אך מינימום {old_min} בכל אחת מ-{class_count} הכיתות "
            f"דורש {old_min * class_count}."
        )
    elif old_max is not None and old_max * class_count < group_count:
        new_max = math.ceil(group_count / class_count)
        arithmetic = (
            f"יש {group_count} תלמידות בקבוצה, אך מקסימום {old_max} בכל אחת מ-{class_count} הכיתות "
            f"מאפשר לשבץ רק {old_max * class_count}."
        )
    if arithmetic is None or (new_min == old_min and new_max == old_max):
        return None

    trial_constraints = deepcopy(constraints)
    trial_target = next((constraint for constraint in trial_constraints if constraint.id == target.id), None)
    if trial_target is None:
        return None
    trial_target.args = {**trial_target.args, "min": new_min, "max": new_max}
    trial_cfg = SolverConfig(**asdict(sess.run_config))
    trial_cfg.time_limit_seconds = min(8.0, trial_cfg.time_limit_seconds)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    try:
        trial = optimize(sess.mapped_df, trial_cfg, trial_constraints, friendship_matched=matched)
    except OptimizationError:
        return None
    if not trial.is_feasible:
        return None

    trial_metrics = compute_global_metrics(
        sess.mapped_df,
        trial.assignment,
        matched,
        trial_constraints,
        trial_cfg.num_classes,
        trial_cfg.denominator_all_students,
    )
    new_args = {**stored_target.args, "min": new_min, "max": new_max}
    old_range = f"{old_min if old_min is not None else 0}–{old_max if old_max is not None else 'ללא הגבלה'}"
    new_range = f"{new_min if new_min is not None else 0}–{new_max if new_max is not None else 'ללא הגבלה'}"
    summary = (
        f"{arithmetic} אני מציע לשנות את הטווח מ-{old_range} ל-{new_range} ולהשאיר את הכלל כחובה. "
        f"בדיקת ניסיון מצאה שיבוץ תקין לכל {trial_metrics.total_students} התלמידות, בלי לשנות כלל חובה אחר."
    )
    if trial_metrics.students_with_requests:
        summary += (
            f" בבדיקה, {round(trial_metrics.mutual_satisfied_pct)}% קיבלו לפחות חברה הדדית "
            f"ו-{round(trial_metrics.two_friends_satisfied_pct)}% לפחות שתי חברות."
        )
    return PendingProposal(
        kind="modify",
        summary_hebrew=summary,
        target_constraint_id=target.id,
        changes={"args": new_args, "label_hebrew": f"{target.label_hebrew} (טווח {new_range})"},
        evidence={
            "basis": "measured_trial",
            "group_count": group_count,
            "class_count": class_count,
            "old_min": old_min,
            "old_max": old_max,
            "new_min": new_min,
            "new_max": new_max,
            "trial_feasible": True,
            "changes_hard_rule": True,
            "other_hard_rules_changed": 0,
        },
    )


def _comment_on_result(sess: Session, cfg, constraints: list[Constraint]) -> str | None:
    """A concise, factual read of the same metrics shown in the UI."""
    df = sess.mapped_df
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    state = sess.adjustment_state
    gm = compute_global_metrics(
        df, state.assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students
    )
    size_text = (
        f"{gm.class_size_min} תלמידות בכל כיתה"
        if gm.class_size_min == gm.class_size_max
        else f"{gm.class_size_min}–{gm.class_size_max} תלמידות בכיתה"
    )
    opening = (
        f"סיימתי. שובצו {gm.total_students} תלמידות ל-{gm.num_classes} כיתות, עם {size_text}. "
        + ("כל כללי החובה מתקיימים." if gm.violations_count == 0 else f"יש {gm.violations_count} חריגות שכדאי לבדוק.")
    )
    if gm.students_with_requests == 0:
        social = " בקובץ לא נמצאו בקשות חברות, ולכן אי אפשר למדוד כרגע את המענה החברתי."
    else:
        social = (
            f" {round(gm.mutual_satisfied_pct)}% מהתלמידות עם בקשות קיבלו לפחות חברה הדדית, "
            f"ו-{round(gm.two_friends_satisfied_pct)}% קיבלו לפחות שתי חברות."
        )
        if gm.unsatisfied_requests:
            social += f" יש {gm.unsatisfied_requests} בקשות שלא קיבלו מענה וכדאי לבדוק אותן."
    return opening + social


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
    if locked != sess.locked_assignment:
        sess.locked_assignment = locked
        sess.mark_inputs_changed()
    store.save(sess)
    return {"locked_count": len(locked), "result_state": sess.result_state()}


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
def run_optimize(x_session_id: str = Header(...), alternative: bool = False, include_comment: bool = True):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים שלבים קודמים תחילה.")
    # Recompute input-derived reports on every explicit solve. Roster edits
    # invalidate their caches, and silently solving with an old friendship
    # graph is worse than the small cost of rebuilding it here.
    sess.validation_report = validate_students(df)
    sess.friendship_result = resolve_requests(df)
    sess.unmatched_df = unmatched_report(sess.friendship_result)
    if sess.validation_report.has_errors():
        raise HTTPException(status_code=400, detail="קיימות שגיאות אימות חוסמות (שלב 4). יש לתקן לפני ההרצה.")

    previous_assignment = dict(sess.adjustment_state.assignment) if alternative and sess.adjustment_state else None
    if alternative:
        # Advance to another deterministic tie-breaker and persist it so the
        # exported configuration exactly reproduces the selected option.
        sess.run_config.random_seed += 1
        sess.mark_inputs_changed()
        store.save(sess)
    cfg, constraints = build_solver_inputs(sess)
    constraints = constraints + build_locked_constraints(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    locked = sess.locked_assignment or {}
    strategy = "balanced" if not alternative else ("preferences" if cfg.random_seed % 2 else "balance")
    solver_constraints = profile_constraints(constraints, strategy)

    try:
        result = optimize(
            df,
            cfg,
            solver_constraints,
            friendship_matched=matched,
            excluded_assignments=[previous_assignment] if previous_assignment else None,
            min_assignment_distance=max(1, len(df) // 20),
        )
    except OptimizationError as e:
        logger.warning("optimize() raised for session %s: %s", x_session_id, e)
        raise HTTPException(status_code=400, detail=str(e))

    # The only reason an otherwise feasible alternative run can become
    # infeasible here is the diversity cut.  That means "no additional
    # distinct option", not "the business rules have no solution".  Keep the
    # already verified assignment current and do not stage a bogus relaxation.
    if alternative and previous_assignment and (
        not result.is_feasible
        or assignment_distance(previous_assignment, result.assignment, cfg.num_classes) == 0
    ):
        sess.run_config.random_seed -= 1
        sess.input_revision = max(0, sess.input_revision - 1)
        store.save(sess)
        return {
            "status_name": "NO_DISTINCT_ALTERNATIVE",
            "is_feasible": True,
            "no_distinct_alternative": True,
            "wall_time_seconds": result.wall_time_seconds,
            "objective_value": None,
            "infeasibility_notes": [],
            "conflicting_constraint_ids": [],
            "result_state": sess.result_state(),
            "version": None,
            "verification": verify_assignment(df, previous_assignment, constraints, cfg.num_classes, matched).to_dict(),
        }

    _prefer_proven_arithmetic_conflicts(result, df, constraints, cfg.num_classes)

    logger.info(
        "optimize done session=%s status=%s feasible=%s wall_time=%.2fs",
        x_session_id, result.status_name, result.is_feasible, result.wall_time_seconds,
    )
    sess.opt_result = result
    sess.adjustment_state = AdjustmentState(assignment=dict(result.assignment), locked=set(locked.keys()))
    if result.is_feasible:
        sess.mark_solved()
    relaxation = _propose_relaxation(sess, result, constraints)
    explanation = _narrate_if_infeasible(sess, result, constraints, relaxation)
    comment = _comment_on_result(sess, cfg, constraints) if result.is_feasible and include_comment else None
    version = (
        _create_version(
            sess,
            cfg,
            constraints,
            "חלופת שיבוץ נוספת" if alternative else "שיבוץ לפי הכללים המאושרים",
        )
        if result.is_feasible
        else None
    )

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
        "result_state": sess.result_state(),
        "version": {"id": version.id, "number": version.number} if version else None,
        "verification": (
            verify_assignment(df, result.assignment, constraints, cfg.num_classes, matched).to_dict()
            if result.is_feasible else None
        ),
    }


def _require_result(sess):
    if sess.opt_result is None or not sess.opt_result.is_feasible:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה מוצלחת תחילה (שלב 8).")


@router.get("/api/versions")
def list_versions(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    chronological = list(sess.assignment_versions)
    moved_from_previous: dict[str, int | None] = {}
    previous = None
    for version in chronological:
        moved = None
        if previous is not None:
            student_ids = set(previous.assignment) | set(version.assignment)
            moved = sum(previous.assignment.get(student_id) != version.assignment.get(student_id) for student_id in student_ids)
        moved_from_previous[version.id] = moved
        previous = version
    return {
        "current_version_id": sess.current_version_id,
        "versions": [
            {
                "id": v.id,
                "number": v.number,
                "created_at": v.created_at,
                "reason": v.reason,
                "mode": v.mode,
                "approved": v.approved,
                "is_current": v.id == sess.current_version_id,
                "metrics": v.metrics,
                "locked_count": len(v.locked_assignment),
                "moved_students_from_previous": moved_from_previous[v.id],
            }
            for v in reversed(chronological)
        ],
    }


@router.post("/api/versions/{version_id}/restore")
def restore_version(version_id: str, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    require(sess.mapped_df, "יש לטעון מחדש את קובץ המקור לפני שחזור גרסה.")
    version = next((v for v in sess.assignment_versions if v.id == version_id), None)
    if version is None:
        raise HTTPException(status_code=404, detail="גרסת השיבוץ לא נמצאה.")

    sess.run_config = SolverConfig(**version.run_config)
    sess.constraints = [Constraint(**c) for c in version.constraints]
    sess.locked_assignment = dict(version.locked_assignment)
    sess.adjustment_state = AdjustmentState(
        assignment=dict(version.assignment),
        locked=set(version.locked_assignment.keys()),
    )
    sess.opt_result = OptimizationResult(**version.result)
    sess.input_revision += 1
    sess.solve_revision = sess.input_revision
    sess.result_mode = version.mode
    sess.current_version_id = version.id
    sess.decision_history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "decision": "applied",
        "kind": "restore_version",
        "summary": f"שוחזרה גרסה {version.number}: {version.reason}",
    })
    sess.decision_history = sess.decision_history[-100:]
    store.save(sess)
    return {"restored": True, "version_id": version.id, "number": version.number, "result_state": sess.result_state()}


@router.post("/api/versions/{version_id}/approve")
def approve_version(version_id: str, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    version = next((v for v in sess.assignment_versions if v.id == version_id), None)
    if version is None:
        raise HTTPException(status_code=404, detail="גרסת השיבוץ לא נמצאה.")
    if sess.current_version_id != version.id:
        raise HTTPException(status_code=409, detail="יש לשחזר את הגרסה לפני אישורה.")
    if sess.result_state()["is_stale"]:
        raise HTTPException(
            status_code=409,
            detail="לא ניתן לאשר את השיבוץ משום שהכללים או הנתונים השתנו מאז יצירתו. יש להריץ או לעדכן את השיבוץ תחילה.",
        )
    version_constraints = [Constraint(**raw) for raw in version.constraints]
    version_constraints += locked_constraints(version.locked_assignment, hard=True)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    independent = verify_assignment(
        sess.mapped_df,
        version.assignment,
        version_constraints,
        int(version.run_config["num_classes"]),
        matched,
    )
    violations_count = independent.hard_rules_violated
    version.metrics["violations_count"] = violations_count
    if violations_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"לא ניתן לאשר שיבוץ עם {violations_count} חריגות מכללי חובה. יש לתקן את החריגות או לחזור לגרסה תקינה.",
        )
    for item in sess.assignment_versions:
        item.approved = item.id == version.id
    sess.decision_history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "decision": "approved",
        "kind": "approve_assignment",
        "summary": f"גרסה {version.number} אושרה כשיבוץ הסופי",
    })
    sess.decision_history = sess.decision_history[-100:]
    store.save(sess)
    return {"approved": True, "version_id": version.id, "number": version.number}


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
    _cfg, constraints = build_solver_inputs(sess)
    return {"rows": df_records(table), "review_groups": _review_groups(sess, constraints)}


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
    return {**gm.__dict__, "result_state": sess.result_state()}


@router.get("/api/results/violations")
def results_violations(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    state = sess.adjustment_state
    table = violations_report(
        df,
        state.assignment,
        constraints + locked_constraints(state.locked_assignment(), hard=True),
        cfg.num_classes,
    )
    return {"rows": df_records(table)}


@router.get("/api/results/verification")
def results_verification(x_session_id: str = Header(...)):
    """Independent, exhaustive verification of the current assignment.

    This endpoint intentionally does not expose CP-SAT's feasibility flag as
    evidence.  It recomputes every active business rule from the roster and
    assignment, including soft rules and assignment completeness.
    """
    sess = store.get_or_create(x_session_id)
    _require_result(sess)
    cfg, constraints = build_solver_inputs(sess)
    constraints += locked_constraints(sess.adjustment_state.locked_assignment(), hard=True)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    report = verify_assignment(
        sess.mapped_df, sess.adjustment_state.assignment, constraints, cfg.num_classes, matched
    )
    return report.to_dict()


@router.post("/api/decision-support/portfolio")
def create_decision_portfolio(x_session_id: str = Header(...), max_options: int = 4):
    """Create alternatives before asking the counselor to choose.

    Feasible cases use different objective profiles.  Infeasible cases trial
    one narrowly relaxed hard rule at a time and verify each result against
    the original rules, so compromises remain explicit.
    """
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים את שלבי הנתונים תחילה.")
    sess.validation_report = validate_students(df)
    if sess.validation_report.has_errors():
        raise HTTPException(status_code=400, detail="קיימות שגיאות אימות חוסמות שיש לתקן לפני יצירת חלופות.")
    sess.friendship_result = resolve_requests(df)
    cfg, constraints = build_solver_inputs(sess)
    constraints += build_locked_constraints(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    options, conflicts = generate_portfolio(
        df, cfg, constraints, matched, max_options=max(2, min(4, max_options))
    )
    stored = [option.to_dict(include_assignment=True) for option in options]
    sess.decision_portfolio = stored
    store.save(sess)
    by_id = {constraint.id: constraint.label_hebrew for constraint in constraints}
    return {
        "has_perfect_solution": any(option.verification.is_valid for option in options),
        "options": [option.to_dict(include_assignment=False) for option in options],
        "conflicts": [{"constraint_id": item, "label": by_id.get(item, item)} for item in conflicts],
        "question": negotiation_question(options),
        "message": (
            f"נמצאו {len(options)} חלופות שונות והשיבוץ המוצג בכל אחת נבדק מחדש."
            if options else "לא נמצאה חלופה ישימה גם לאחר בדיקת הקלות ממוקדות."
        ),
    }


@router.get("/api/decision-support/portfolio")
def get_decision_portfolio(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    public = [{key: value for key, value in item.items() if key != "assignment"} for item in sess.decision_portfolio]
    # Reconstruct just enough for a deterministic question without trusting
    # stored prose; the POST response already contains the richer question.
    return {"options": public, "inferred_preferences": list(sess.inferred_preferences)}


def _learn_option_preference(sess: Session, chosen: dict) -> None:
    strategy = chosen.get("strategy", "balanced")
    existing = next((item for item in sess.inferred_preferences if item.get("key") == strategy), None)
    if existing is None:
        existing = {
            "key": strategy,
            "description": f"The coordinator tends to prefer the '{strategy}' assignment strategy.",
            "kind": "inferred_preference",
            "explicit": False,
            "observations": 0,
            "confidence": 0.0,
        }
        sess.inferred_preferences.append(existing)
    existing["observations"] = int(existing.get("observations", 0)) + 1
    existing["confidence"] = round(min(0.95, 0.5 + 0.1 * (existing["observations"] - 1)), 2)
    existing["last_updated"] = datetime.now(timezone.utc).isoformat()


@router.post("/api/decision-support/select")
def select_decision_option(req: SelectDecisionOptionRequest, x_session_id: str = Header(...)):
    """Record a choice and either apply it or stage its required compromise."""
    sess = store.get_or_create(x_session_id)
    chosen = next((item for item in sess.decision_portfolio if item.get("id") == req.option_id), None)
    if chosen is None:
        raise HTTPException(status_code=404, detail="חלופת השיבוץ לא נמצאה או שאינה עדכנית.")
    _learn_option_preference(sess, chosen)
    sess.decision_history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "decision": "approved",
        "kind": "option_selection",
        "summary": req.reason or f"נבחרה {chosen.get('title', req.option_id)}",
        "option_id": req.option_id,
        "rejected_option_ids": [item.get("id") for item in sess.decision_portfolio if item.get("id") != req.option_id],
    })
    sess.decision_history = sess.decision_history[-100:]

    verification = chosen.get("verification") or {}
    if not verification.get("is_valid", False):
        relaxed = chosen.get("relaxed_constraint_ids") or []
        target = next((constraint for constraint in sess.constraints if constraint.id in relaxed), None)
        if target is None:
            store.save(sess)
            raise HTTPException(status_code=409, detail="החלופה דורשת פשרה שלא ניתן להחיל אוטומטית.")
        proposal = PendingProposal(
            kind="modify",
            summary_hebrew=f'כדי להשתמש בחלופה שנבחרה יש להפוך את "{target.label_hebrew}" מכלל חובה להעדפה. השינוי דורש אישור מפורש.',
            target_constraint_id=target.id,
            changes={"hard": False},
            evidence={"basis": "measured_trial", "trial_feasible": True, "changes_hard_rule": True},
        )
        sess.pending_proposal = proposal
        store.save(sess)
        return {"applied": False, "requires_confirmation": True, "proposal": asdict(proposal),
                "inferred_preferences": list(sess.inferred_preferences)}

    assignment = {int(student_id): int(group) for student_id, group in chosen["assignment"].items()}
    cfg, constraints = build_solver_inputs(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    fresh = verify_assignment(sess.mapped_df, assignment, constraints + build_locked_constraints(sess), cfg.num_classes, matched)
    if not fresh.is_valid:
        store.save(sess)
        raise HTTPException(status_code=409, detail="הכללים השתנו מאז יצירת החלופות; יש ליצור חלופות מחדש.")
    sess.opt_result = OptimizationResult(
        status_name="VERIFIED_PORTFOLIO", is_feasible=True, assignment=assignment,
        objective_value=chosen.get("objective_value"), wall_time_seconds=float(chosen.get("wall_time_seconds", 0.0)),
    )
    sess.adjustment_state = AdjustmentState(assignment=assignment, locked=set(sess.locked_assignment))
    sess.mark_solved()
    version = _create_version(sess, cfg, constraints, chosen.get("title", "חלופה נבחרת"))
    store.save(sess)
    return {"applied": True, "requires_confirmation": False,
            "version": {"id": version.id, "number": version.number},
            "verification": fresh.to_dict(), "result_state": sess.result_state(),
            "inferred_preferences": list(sess.inferred_preferences)}


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
    previous_class = state.assignment.get(req.student_id)
    was_locked = req.student_id in state.locked
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    moving_between_classes = previous_class is not None and previous_class != req.new_class - 1
    if was_locked and moving_between_classes and req.locked is not False:
        raise HTTPException(
            status_code=409,
            detail="התלמידה מקובעת לכיתה הנוכחית. יש לבטל את הקיבוע במפורש לפני ההעברה.",
        )
    # Validate and apply the move before mutating lock state. This keeps an
    # invalid explicit unlock-and-move request transactional: a rejected
    # destination must never leave the student silently unlocked.
    try:
        state.move_student(req.student_id, req.new_class - 1, cfg.num_classes)
    except ManualAdjustmentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if req.locked is False:
        state.unlock(req.student_id)
        if req.student_id in sess.locked_assignment:
            sess.locked_assignment.pop(req.student_id, None)
            sess.mark_inputs_changed()
    if req.locked is True:
        state.lock(req.student_id)
        sess.locked_assignment[req.student_id] = req.new_class - 1
        sess.mark_inputs_changed()

    sess.mark_manually_adjusted()
    gm = compute_global_metrics(df, state.assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students)
    moved_between_classes = moving_between_classes
    if moved_between_classes and req.locked is True:
        reason = f"העברה וקיבוע ידניים מכיתה {previous_class + 1} לכיתה {req.new_class}"
    elif moved_between_classes:
        reason = f"העברה ידנית מכיתה {previous_class + 1} לכיתה {req.new_class}"
    elif req.locked is True and not was_locked:
        reason = f"קיבוע ידני בכיתה {req.new_class}"
    elif req.locked is False and was_locked:
        reason = f"ביטול קיבוע ידני בכיתה {req.new_class}"
    else:
        reason = f"עדכון ידני בכיתה {req.new_class}"
    student_token = sess.token_map.token_for(req.student_id)
    sess.decision_history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "decision": "applied",
        "kind": "manual_move" if moved_between_classes else "manual_lock",
        "student": student_token,
        "summary": reason,
    })
    sess.decision_history = sess.decision_history[-100:]
    version = _create_version(sess, cfg, constraints, reason, mode="manual")
    return {
        "assignment_updated": True,
        "metrics": gm.__dict__,
        "result_state": sess.result_state(),
        "version": {"id": version.id, "number": version.number},
    }


@router.post("/api/adjustment/reoptimize")
def adjustment_reoptimize(x_session_id: str = Header(...)):
    """Re-optimize around the students the counselor explicitly locked.

    Locking every current placement would leave no decision for the solver
    and merely reproduce the existing board. Only explicit locks are hard;
    every other student may move to improve the objective.
    """
    sess = store.get_or_create(x_session_id)
    if sess.adjustment_state is None:
        raise HTTPException(status_code=409, detail="יש להריץ אופטימיזציה תחילה (שלב 8).")
    state: AdjustmentState = sess.adjustment_state
    df = sess.mapped_df
    cfg, constraints = build_solver_inputs(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}

    all_constraints = constraints + locked_constraints(state.locked_assignment(), hard=True)
    try:
        result = optimize(df, cfg, all_constraints, friendship_matched=matched)
    except OptimizationError as e:
        logger.warning("reoptimize() raised for session %s: %s", x_session_id, e)
        raise HTTPException(status_code=400, detail=str(e))

    _prefer_proven_arithmetic_conflicts(result, df, all_constraints, cfg.num_classes)

    logger.info(
        "reoptimize done session=%s status=%s feasible=%s wall_time=%.2fs",
        x_session_id, result.status_name, result.is_feasible, result.wall_time_seconds,
    )
    sess.opt_result = result
    state.assignment = dict(result.assignment)
    sess.adjustment_state = state
    if result.is_feasible:
        sess.mark_solved()
    explanation = _narrate_if_infeasible(sess, result, all_constraints)
    version = _create_version(sess, cfg, all_constraints, "אופטימיזציה מחדש סביב קיבועים") if result.is_feasible else None

    return {
        "status_name": result.status_name,
        "is_feasible": result.is_feasible,
        "wall_time_seconds": result.wall_time_seconds,
        "objective_value": result.objective_value,
        "infeasibility_notes": result.infeasibility_notes,
        "conflicting_constraint_ids": result.conflicting_constraint_ids,
        "infeasibility_explanation": explanation,
        "result_state": sess.result_state(),
        "version": {"id": version.id, "number": version.number} if version else None,
    }
