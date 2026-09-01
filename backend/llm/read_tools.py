"""Read-only tools: the half of the agent surface that answers questions.

The propose_*/modify_*/remove_* tools in tools.py change the world, so they
never execute -- they become a PendingProposal the counselor confirms. The
tools here only look at the world, so they execute immediately and their
results are fed straight back to the model inside the same turn.

That asymmetry is the design. Gating reads behind a confirmation card would
make the agent unable to think; auto-applying writes would make it
untrustworthy with real students' placements. Reading is free and
reversible, so it needs no ceremony.

Everything returned here stays inside the same privacy boundary as the rest
of backend/llm: students appear only as opaque session tokens (TokenMap),
never as names or real student ids.

Class numbers in and out of these tools are 1-based -- the same numbers the
counselor sees on screen (ז1..ז6). The 0-based indices the solver uses never
leave this module.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel, Field

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_CLASS,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_FRIEND_REQUESTS,
    FIELD_LABELS_HE,
    FIELD_STUDENT_ID,
)
from src.metrics import academic_level_spread, class_overview_table, compute_global_metrics, violations_report
from src.constraints import Constraint, locked_constraints, resolve_group_members
from src.friendship_graph import resolve_requests
from src.feasibility import analyze_feasibility
from src.validation import validate_students

from ..solver_inputs import build_solver_inputs
from ..utils import df_records, _clean_value

CATEGORY_FIELDS = {
    "differential": FIELD_DIFFERENTIAL,
    "ethiopian_origin": FIELD_ETHIOPIAN_ORIGIN,
    "inclusion": FIELD_INCLUSION,
    "hamar": FIELD_HAMAR,
}

# Hebrew display names for the built-in flags. Extra columns bring their own
# label from the spreadsheet header, which is usually better than anything
# this file could invent.
BUILTIN_LABELS = {
    "differential": "דיפרנציאלית",
    "ethiopian_origin": "מוצא אתיופי",
    "inclusion": "שילוב",
    "hamar": 'ח"מ',
}

# Columns that describe a student but aren't flags -- worth offering as
# things to balance or filter on even though they were never "categories".
SEMANTIC_CATEGORY_FIELDS = {
    FIELD_ACADEMIC_LEVEL: "הישגים לימודיים",
    FIELD_CURRENT_SCHOOL: 'ביה"ס קודם',
    FIELD_CURRENT_CLASS: "כיתה קודמת",
}


def groupable_field_kinds(sess) -> dict[str, str]:
    """Column key -> "flag" | "category", for every constrainable column.

    The distinction is load-bearing, not cosmetic. A group selector of
    {"kind": "field"} tests `bool(value)`, which on a text column is true for
    every student -- so a balance rule built that way spreads "everyone",
    silently does nothing, and still looks applied. Category columns need
    `field_all_values` (spread each value) or `field_value` (one value).
    """
    kinds: dict[str, str] = {f: "flag" for f in CATEGORY_FIELDS.values()}
    kinds.update({f: "category" for f in SEMANTIC_CATEGORY_FIELDS})
    schema = getattr(sess, "dataset_schema", None)
    for col in (schema.extras if schema is not None else []):
        kinds[col.key] = col.kind
    return kinds


def groupable_fields(sess) -> set[str]:
    """Every column a rule may be written about for *this* dataset.

    The built-in flags plus the descriptive semantic columns plus whatever
    else the uploaded workbook turned out to contain. This is what stops the
    model inventing a column: `args_to_constraint` checks against it.
    """
    fields = set(CATEGORY_FIELDS.values()) | set(SEMANTIC_CATEGORY_FIELDS)
    schema = getattr(sess, "dataset_schema", None)
    if schema is not None:
        fields |= set(schema.keys())
    return fields

# Cap on how many distinct values of a category column get listed back to
# the model -- enough to reason about, not enough to bloat every turn.
MAX_LISTED_VALUES = 15

NO_RESULT = {
    "error": "no_assignment_yet",
    "detail": "No successful solve has been run in this session yet, so there are no classes to inspect.",
}


# ---------------------------------------------------------------- arg models

class NoArgs(BaseModel):
    pass


class GetClassCompositionArgs(BaseModel):
    class_number: int = Field(description="Which class to describe, 1-based (1 = ז1)")


class ExplainStudentPlacementArgs(BaseModel):
    student: str = Field(description="Anonymized token for the student, e.g. STUDENT_a1b2c3")


class GetStudentRecordArgs(BaseModel):
    student: str = Field(description="Anonymized token for the student whose editable project data should be inspected")


class CompareStudentVersionsArgs(BaseModel):
    student: str = Field(description="Anonymized token for the student, e.g. STUDENT_a1b2c3")
    from_version_id: Optional[str] = Field(
        default=None,
        description="Opaque version id returned by get_assignment_versions. Omit to use the version immediately before the target.",
    )
    to_version_id: Optional[str] = Field(
        default=None,
        description="Opaque version id returned by get_assignment_versions. Omit to use the current assignment version.",
    )


class QueryRosterArgs(BaseModel):
    column: Optional[str] = Field(
        default=None,
        description=(
            "Any column key from get_dataset_columns. For a flag column this selects the students it is "
            "true for; for a category column, pair it with `value`."
        ),
    )
    value: Optional[str] = Field(default=None, description="The value to match, when `column` is a category-kind column")
    assigned_class: Optional[int] = Field(default=None, description="Filter to students placed in this class, 1-based; requires a solve")
    limit: int = Field(default=25, description="Maximum number of student tokens to return; the count is always exact")


READ_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "get_dataset_columns": NoArgs,
    "get_solve_summary": NoArgs,
    "get_class_sizes": NoArgs,
    "get_class_composition": GetClassCompositionArgs,
    "get_violations": NoArgs,
    "get_active_rules": NoArgs,
    "analyze_rule_feasibility": NoArgs,
    "explain_student_placement": ExplainStudentPlacementArgs,
    "compare_student_versions": CompareStudentVersionsArgs,
    "query_roster": QueryRosterArgs,
    "get_assignment_versions": NoArgs,
    "analyze_assignment_quality": NoArgs,
    "get_student_record": GetStudentRecordArgs,
    "analyze_data_quality": NoArgs,
}

READ_TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_dataset_columns": (
        "קרא אילו עמודות קיימות בקובץ של בית הספר הזה ומה הטווח שלהן. **קרא לזה לפני שאת/ה כותב/ת כלל על "
        "קבוצה כלשהי** - לכל בית ספר יש עמודות אחרות, ורק מה שחוזר מכאן קיים באמת."
    ),
    "get_solve_summary": "קרא את סיכום השיבוץ הנוכחי: מספר תלמידות וכיתות, גדלים, פערים, אחוזי מימוש בקשות חברות, ומספר הפרות.",
    "get_class_sizes": "קרא את גודל כל כיתה בשיבוץ הנוכחי, יחד עם חוק גודל-הכיתה הפעיל והגבולות שלו. השתמש בזה לכל שאלה על הבדלי גודל בין כיתות.",
    "get_class_composition": "קרא את ההרכב המלא של כיתה אחת: גודל, התפלגות הישגים, ספירת קטגוריות, התפלגות בתי ספר ואחוזי חברות.",
    "get_violations": "קרא את רשימת ההפרות בשיבוץ הנוכחי - אילו חוקים קשיחים נשברים, באיזו כיתה, ובכמה.",
    "get_active_rules": "קרא את רשימת החוקים הפעילים כולל הערכים המספריים שלהם (מינימום/מקסימום/משקל), לא רק את התיאור.",
    "analyze_rule_feasibility": (
        "בדוק כל כלל חובה מספרי בפני עצמו מול מספר התלמידות האמיתי בקובץ ומספר הכיתות. מחזיר את "
        "החשבון המדויק ואת הריכוך המזערי לכל כלל בלתי אפשרי; אינו משנה שום כלל ואינו מחליף בדיקת מנוע "
        "לאינטראקציות בין כמה כללים. השתמש בזה לפני כל תשובה על כללים בלתי אפשריים או היתכנות."
    ),
    "explain_student_placement": (
        "קרא היכן שובצה תלמידה מסוימת, האם היא מקובעת, מה קרה לבקשות החברות שלה, "
        "ואילו כללי חובה באמת יחסמו העברה ישירה לכל כיתה אחרת."
    ),
    "compare_student_versions": (
        "השווה תלמידה מסוימת בין שתי גרסאות שיבוץ: הכיתה לפני ואחרי, מענה החברות, "
        "הרכב לימודי, והאם החזרתה לבדה לכיתה הקודמת הייתה יוצרת הפרת חובה חדשה. "
        "השתמש/י בזה לשאלות כמו 'למה היא עברה?' או 'מה השתנה עבורה?'."
    ),
    "query_roster": "ספור או דגום תלמידות לפי כל עמודה שקיימת בנתונים (ראה get_dataset_columns) או לפי כיתה משובצת.",
    "get_student_record": (
        "Inspect the current editable project-data values for one student before proposing a correction. Returns only "
        "privacy-safe fields; names and raw friendship text are never sent to the model."
    ),
    "analyze_data_quality": (
        "Analyze the uploaded roster itself for missing, duplicate, invalid, or ambiguous data. Returns exact affected "
        "student tokens and safe correction guidance. Use before suggesting data edits; never infer sensitive values."
    ),
}


READ_TOOL_DESCRIPTIONS["get_assignment_versions"] = (
    "Read the stored assignment versions, their measured metrics, and how many students moved between "
    "successive versions. Use this after a solve when comparing alternatives."
)

READ_TOOL_DESCRIPTIONS["analyze_assignment_quality"] = (
    "Inspect the entire current assignment as one system, not one class at a time. Returns measured class "
    "profiles, global quality metrics, active optimization priorities, hard-rule compliance, locks, and the "
    "solver status. Use this first when the counselor asks whether the placement is balanced, what is imperfect, "
    "or why the result looks uneven. It supplies evidence for reasoning; it does not claim an exact cause unless "
    "a constraint or a measured counterfactual proves one."
)


def build_read_tool_definitions() -> list[dict]:
    """OpenAI-style tool definitions, generated from the models above so the
    schema handed to the model and the validation applied to its output can
    never drift apart -- same contract as tools.build_tool_definitions."""
    tools = []
    for name, model in READ_TOOL_MODELS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("properties", {})
        tools.append(
            {
                "type": "function",
                "function": {"name": name, "description": READ_TOOL_DESCRIPTIONS[name], "parameters": schema},
            }
        )
    return tools


# ------------------------------------------------------------------ context

def _result_ctx(sess) -> Optional[tuple]:
    """(df, cfg, constraints, assignment, matched) for the assignment
    currently on screen -- `adjustment_state`, not `opt_result`, so manual
    moves the counselor made after the solve are included. Returns None when
    there is nothing to look at yet."""
    if sess.adjustment_state is None or sess.opt_result is None or not sess.opt_result.is_feasible:
        return None
    cfg, constraints = build_solver_inputs(sess)
    matched = sess.friendship_result.matched if sess.friendship_result else {}
    return sess.mapped_df, cfg, constraints, sess.adjustment_state.assignment, matched


def _class_size_rule(constraints) -> Optional[dict]:
    """The built-in overall class-size rule, if it's still active. This is
    the rule that actually decides how uneven classes may be, and its
    numeric bounds are the answer to most "why is that class bigger"
    questions -- the constraints context block only ever showed its label."""
    for c in constraints:
        if c.type == "capacity" and c.active and c.args.get("group", {}).get("kind") == "all":
            return {
                "id": c.id,
                "min": c.args.get("min"),
                "max": c.args.get("max"),
                "tolerance": c.args.get("size_diff"),
                "hard": c.hard,
                "label_hebrew": c.label_hebrew,
            }
    return None


def _counts(series: pd.Series) -> dict:
    return {str(k): int(v) for k, v in series.value_counts().to_dict().items()}


# -------------------------------------------------------------- tool bodies

def _get_solve_summary(sess, _args) -> dict:
    ctx = _result_ctx(sess)
    if ctx is None:
        return NO_RESULT
    df, cfg, constraints, assignment, matched = ctx
    gm = compute_global_metrics(
        df, assignment, matched, constraints, cfg.num_classes, cfg.denominator_all_students,
        sess.opt_result.status_name, sess.opt_result.wall_time_seconds, sess.opt_result.objective_value,
    )
    out = dict(gm.__dict__)
    # Guard the single most misreadable number in the product: 0% mutual
    # satisfaction means something completely different when nobody filed a
    # request than when every request failed.
    if gm.students_with_requests == 0:
        out["friendship_note"] = (
            "No student submitted any friend request, so the satisfaction percentages are 0 by "
            "construction and say nothing about placement quality."
        )
    return _clean_value(out)


def _get_class_sizes(sess, _args) -> dict:
    ctx = _result_ctx(sess)
    if ctx is None:
        return NO_RESULT
    df, cfg, constraints, assignment, _matched = ctx
    sizes = [0] * cfg.num_classes
    for cls in assignment.values():
        if 0 <= cls < cfg.num_classes:
            sizes[cls] += 1
    rule = _class_size_rule(constraints)
    within = None
    if rule is not None:
        lo, hi = rule.get("min"), rule.get("max")
        within = all((lo is None or s >= lo) and (hi is None or s <= hi) for s in sizes)
    return {
        "classes": [{"class": i + 1, "size": s} for i, s in enumerate(sizes)],
        "smallest": min(sizes) if sizes else 0,
        "largest": max(sizes) if sizes else 0,
        "spread": (max(sizes) - min(sizes)) if sizes else 0,
        "size_rule": rule,
        "all_sizes_within_rule": within,
        # Domain fact the model cannot infer and repeatedly guesses wrong
        # about: class size is bounded, never optimized. Inside the allowed
        # band the solver is indifferent, so an uneven-but-legal split is
        # the expected outcome, not a bug or a sign of a broken rule.
        "how_size_is_decided": (
            "Class size is controlled only by the min/max of the size rule above. There is no objective term "
            "that rewards making classes equal, so any split inside the allowed band is equally good to the "
            "solver and it will not even them out further on its own. To force a tighter spread, narrow the "
            "rule's min/max."
        ),
    }


def _get_class_composition(sess, args: GetClassCompositionArgs) -> dict:
    ctx = _result_ctx(sess)
    if ctx is None:
        return NO_RESULT
    df, cfg, constraints, assignment, matched = ctx
    if not 1 <= args.class_number <= cfg.num_classes:
        return {"error": "no_such_class", "detail": f"Valid classes are 1..{cfg.num_classes}."}
    overview = class_overview_table(df, assignment, matched, constraints, cfg.num_classes)
    rows = df_records(overview)
    row = next((r for r in rows if r.get("כיתה") == args.class_number), None)
    return row or {"error": "no_such_class"}


def _get_violations(sess, _args) -> dict:
    ctx = _result_ctx(sess)
    if ctx is None:
        return NO_RESULT
    df, cfg, constraints, assignment, _matched = ctx
    rows = df_records(violations_report(df, assignment, constraints, cfg.num_classes))
    return {"count": len(rows), "violations": rows}


def _get_active_rules(sess, _args) -> dict:
    _cfg, constraints = build_solver_inputs(sess)
    out = []
    for c in constraints:
        if not c.active:
            continue
        args = dict(c.args)
        group = args.get("group")
        safe_rule = _safe_blocking_rule(c)
        entry = {
            "id": c.id,
            "type": c.type,
            "hard": c.hard,
            "label_hebrew": safe_rule["label_hebrew"],
            "source": c.source,
        }
        if group:
            entry["group"] = _clean_value(group)
        for k in ("min", "max", "weight", "weight_mutual", "weight_two_friends"):
            if args.get(k) is not None:
                entry[k] = args[k]
        out.append(_clean_value(entry))
    return {"count": len(out), "rules": out}


def _analyze_rule_feasibility(sess, _args) -> dict:
    """Prove which mandatory capacity rules fail on arithmetic alone."""
    df = sess.mapped_df
    if df is None:
        return {"error": "no_dataset", "detail": "No mapped roster is available yet."}
    cfg, constraints = build_solver_inputs(sess)
    report = analyze_feasibility(df, constraints, cfg.num_classes)
    by_id = {constraint.id: constraint for constraint in constraints}
    checked = []
    for finding in report.findings:
        constraint = by_id.get(finding.constraint_id)
        entry = {
            "constraint_id": finding.constraint_id,
            "label_hebrew": finding.rule,
            "independently_feasible": finding.feasible,
            "arithmetic": finding.message,
        }
        if constraint is not None and constraint.type == "capacity":
            group = constraint.args.get("group", {})
            total = len(resolve_group_members(df, group))
            old_min = constraint.args.get("min")
            old_max = constraint.args.get("max")
            entry.update(
                {
                    "group": _clean_value(group),
                    "students_in_group": total,
                    "num_classes": cfg.num_classes,
                    "active_min": old_min,
                    "active_max": old_max,
                }
            )
            if not finding.feasible:
                # The smallest independent relaxation changes only a bound
                # whose multiplication is already impossible. Preserve the
                # other bound exactly; a later solver run checks interactions.
                new_min = old_min
                new_max = old_max
                changed_bounds = []
                if old_min is not None and old_min * cfg.num_classes > total:
                    new_min = total // cfg.num_classes
                    changed_bounds.append({"bound": "min", "from": old_min, "to": new_min})
                if old_max is not None and old_max * cfg.num_classes < total:
                    new_max = -(-total // cfg.num_classes)
                    changed_bounds.append({"bound": "max", "from": old_max, "to": new_max})
                entry["minimal_independent_relaxation"] = {
                    "min": new_min,
                    "max": new_max,
                    "changed_bounds": changed_bounds,
                    "requires_explicit_approval": True,
                }
        checked.append(_clean_value(entry))

    impossible = [item for item in checked if not item["independently_feasible"]]
    return {
        "student_count": len(df),
        "num_classes": cfg.num_classes,
        "checked_mandatory_capacity_rules": len(checked),
        "all_independently_feasible": not impossible,
        "independently_impossible_count": len(impossible),
        "independently_impossible_rules": impossible,
        "independently_feasible_rules": [item for item in checked if item["independently_feasible"]],
        "reasoning_boundary": (
            "Each result above is an independent arithmetic proof about one active mandatory capacity rule. "
            "Rules that pass independently may still conflict in combination; proving that requires a solver run. "
            "No rule has been changed by this analysis."
        ),
    }


def _explain_student_placement(sess, args: ExplainStudentPlacementArgs) -> dict:
    sid = sess.token_map.id_for(args.student)
    if sid is None:
        return {"error": "unknown_student_token", "detail": "That token does not belong to any student in this session."}
    df = sess.mapped_df
    row = df[df[FIELD_STUDENT_ID] == sid]
    if row.empty:
        return {"error": "unknown_student_token"}
    r = row.iloc[0]

    info: dict[str, Any] = {
        "student": args.student,
        "current_school": _clean_value(r.get(FIELD_CURRENT_SCHOOL)),
        "current_class": _clean_value(r.get(FIELD_CURRENT_CLASS)),
        "academic_level": _clean_value(r.get(FIELD_ACADEMIC_LEVEL)),
        "categories": [name for name, field in CATEGORY_FIELDS.items() if bool(r.get(field, False))],
    }

    ctx = _result_ctx(sess)
    if ctx is None:
        info["assigned_class"] = None
        info["note"] = "No solve has been run yet, so this student has no placement."
        return info

    _df, _cfg, _constraints, assignment, matched = ctx
    cls = assignment.get(sid)
    info["assigned_class"] = (cls + 1) if cls is not None else None
    info["locked"] = sid in (sess.adjustment_state.locked or set())

    requested = [r2 for r2 in matched.get(sid, []) if r2 != sid]
    same = [r2 for r2 in requested if assignment.get(r2) == cls]
    mutual = [r2 for r2 in same if sid in matched.get(r2, [])]
    info["friend_requests"] = {
        "requested": len(requested),
        "placed_together": len(same),
        "mutual_together": len(mutual),
        "requested_tokens": [sess.token_map.token_for(r2) for r2 in requested],
        "placed_together_tokens": [sess.token_map.token_for(r2) for r2 in same],
    }
    info["direct_move_checks"] = _direct_move_checks(
        df,
        sid,
        assignment,
        _constraints,
        _cfg.num_classes,
        matched,
        sess.locked_assignment,
    )
    info["explanation_limit"] = (
        "These checks verify what would happen if only this student moved and everyone else stayed fixed. "
        "A class marked blocked may still become feasible if the solver also moves other students. The data "
        "does not prove which objective term caused the solver to choose among equally feasible classes."
    )
    return info


def _violated_hard_rule_ids(df, assignment: dict, constraints, num_classes: int) -> set[str]:
    """Evaluate every supported hard rule against one complete assignment."""
    violated: set[str] = set()
    class_members = [{sid for sid, cls in assignment.items() if cls == class_index} for class_index in range(num_classes)]
    for constraint in constraints:
        if not constraint.active or not constraint.hard:
            continue
        args = constraint.args
        if constraint.type == "capacity":
            members = set(resolve_group_members(df, args["group"]))
            lo, hi = args.get("min"), args.get("max")
            counts = [len(members & class_members[index]) for index in range(num_classes)]
            if any((lo is not None and count < lo) or (hi is not None and count > hi) for count in counts):
                violated.add(constraint.id)
        elif constraint.type == "separate":
            if assignment.get(args["student_a"]) == assignment.get(args["student_b"]):
                violated.add(constraint.id)
        elif constraint.type == "together":
            if assignment.get(args["student_a"]) != assignment.get(args["student_b"]):
                violated.add(constraint.id)
        elif constraint.type == "at_least_one_of":
            student_class = assignment.get(args["student"])
            if not any(assignment.get(candidate) == student_class for candidate in args.get("candidates", [])):
                violated.add(constraint.id)
        elif constraint.type == "locked":
            if assignment.get(args["student"]) != args["class_index"]:
                violated.add(constraint.id)
        elif constraint.type == "balance":
            group = args["group"]
            if group.get("kind") == "field_all_values":
                groups = [
                    {"kind": "field_value", "field": group["field"], "value": value}
                    for value in df[group["field"]].dropna().unique()
                ]
            elif group.get("kind") == "fields":
                groups = [{"kind": "field", "field": field} for field in group["fields"]]
            else:
                groups = [group]
            for subgroup in groups:
                members = set(resolve_group_members(df, subgroup))
                counts = [len(members & class_members[index]) for index in range(num_classes)]
                if counts and max(counts) != min(counts):
                    violated.add(constraint.id)
                    break
    return violated


def _direct_move_checks(df, student_id, assignment, constraints, num_classes, matched, locked_assignment) -> list[dict]:
    current_class = assignment.get(student_id)
    current_violations = _violated_hard_rule_ids(df, assignment, constraints, num_classes)
    by_id = {constraint.id: constraint for constraint in constraints}
    checks = []
    for target in range(num_classes):
        if target == current_class:
            continue
        candidate = dict(assignment)
        candidate[student_id] = target
        new_ids = _violated_hard_rule_ids(df, candidate, constraints, num_classes) - current_violations
        if student_id in locked_assignment:
            new_ids.add("manual_lock")
        requested = [other for other in matched.get(student_id, []) if other != student_id]
        together = [other for other in requested if candidate.get(other) == target]
        mutual = [other for other in together if student_id in matched.get(other, [])]
        blocking = []
        for constraint_id in sorted(new_ids):
            if constraint_id == "manual_lock":
                blocking.append({"id": constraint_id, "type": "locked", "label_hebrew": "קיבוע ידני פעיל"})
            elif constraint_id in by_id:
                blocking.append(_safe_blocking_rule(by_id[constraint_id]))
        checks.append(
            {
                "class": target + 1,
                "direct_move_preserves_hard_rules": not blocking,
                "new_blocking_rules": blocking,
                "requested_friends_there": len(together),
                "mutual_friends_there": len(mutual),
            }
        )
    return checks


def _safe_blocking_rule(constraint: Constraint) -> dict:
    """Return a useful blocker label without leaking names embedded in rules."""
    generic = {
        "locked": "קיבוע ידני פעיל",
        "together": "כלל צירוף בין תלמידות",
        "separate": "כלל הפרדה בין תלמידות",
        "at_least_one_of": "כלל חברה נדרשת",
        "balance": "כלל איזון חובה",
    }
    return {
        "id": constraint.id,
        "type": constraint.type,
        "label_hebrew": generic.get(constraint.type, constraint.label_hebrew),
    }


def _student_version_snapshot(df, student_id, version, matched) -> dict:
    assigned = version.assignment.get(student_id)
    requested = [other for other in matched.get(student_id, []) if other != student_id]
    together = [other for other in requested if version.assignment.get(other) == assigned]
    mutual = [other for other in together if student_id in matched.get(other, [])]
    num_classes = int(version.run_config.get("num_classes", 0) or 0)
    level_row = df.loc[df[FIELD_STUDENT_ID] == student_id, FIELD_ACADEMIC_LEVEL]
    level = None if level_row.empty else _clean_value(level_row.iloc[0])
    class_members = [sid for sid, cls in version.assignment.items() if cls == assigned]
    same_level = 0
    if assigned is not None and level is not None:
        same_level_ids = set(df.loc[df[FIELD_ACADEMIC_LEVEL] == level, FIELD_STUDENT_ID].tolist())
        same_level = sum(sid in same_level_ids for sid in class_members)
    academic_spread = version.metrics.get("academic_level_spread")
    if academic_spread is None and num_classes > 0:
        academic_spread = academic_level_spread(df, version.assignment, num_classes)
    return {
        "version_id": version.id,
        "version_number": version.number,
        "class": assigned + 1 if assigned is not None else None,
        "class_size": len(class_members),
        "friend_requests": {
            "requested": len(requested),
            "placed_together": len(together),
            "mutual_together": len(mutual),
        },
        "academic_level": level,
        "same_academic_level_in_class": same_level,
        "academic_level_spread": academic_spread,
    }


def _compare_student_versions(sess, args: CompareStudentVersionsArgs) -> dict:
    student_id = sess.token_map.id_for(args.student)
    if student_id is None:
        return {"error": "unknown_student_token", "detail": "That token does not belong to any student in this session."}
    versions = list(getattr(sess, "assignment_versions", []))
    if len(versions) < 2:
        return {"error": "not_enough_versions", "detail": "At least two stored assignment versions are required."}

    to_version = next((version for version in versions if version.id == args.to_version_id), None) if args.to_version_id else None
    if to_version is None and args.to_version_id:
        return {"error": "unknown_to_version", "detail": "Call get_assignment_versions and use an exact returned id."}
    if to_version is None:
        to_version = next((version for version in versions if version.id == sess.current_version_id), versions[-1])
    to_index = versions.index(to_version)

    from_version = next((version for version in versions if version.id == args.from_version_id), None) if args.from_version_id else None
    if from_version is None and args.from_version_id:
        return {"error": "unknown_from_version", "detail": "Call get_assignment_versions and use an exact returned id."}
    if from_version is None:
        if to_index == 0:
            return {"error": "no_previous_version", "detail": "The target is the first stored assignment version."}
        from_version = versions[to_index - 1]
    if from_version.id == to_version.id:
        return {"error": "same_version", "detail": "Choose two different assignment versions."}

    df = sess.mapped_df
    if df is None or df.loc[df[FIELD_STUDENT_ID] == student_id].empty:
        return {"error": "unknown_student_token"}
    matched = sess.friendship_result.matched if sess.friendship_result else resolve_requests(df).matched
    before = _student_version_snapshot(df, student_id, from_version, matched)
    after = _student_version_snapshot(df, student_id, to_version, matched)
    moved = before["class"] != after["class"]

    return_check = None
    if moved and before["class"] is not None and after["class"] is not None:
        target_zero = int(before["class"]) - 1
        num_classes = int(to_version.run_config.get("num_classes", sess.run_config.num_classes))
        if 0 <= target_zero < num_classes:
            constraints = [Constraint(**raw) for raw in to_version.constraints]
            constraints += locked_constraints(to_version.locked_assignment)
            current_violations = _violated_hard_rule_ids(df, to_version.assignment, constraints, num_classes)
            candidate = dict(to_version.assignment)
            candidate[student_id] = target_zero
            new_ids = _violated_hard_rule_ids(df, candidate, constraints, num_classes) - current_violations
            by_id = {constraint.id: constraint for constraint in constraints}
            blockers = [_safe_blocking_rule(by_id[constraint_id]) for constraint_id in sorted(new_ids) if constraint_id in by_id]
            requested = [other for other in matched.get(student_id, []) if other != student_id]
            together = [other for other in requested if candidate.get(other) == target_zero]
            return_check = {
                "available": True,
                "direct_return_preserves_hard_rules": not blockers,
                "new_blocking_rules": blockers,
                "requested_friends_if_returned": len(together),
                "scope": "Only this student is returned; no compensating moves are made.",
            }
        else:
            return_check = {
                "available": False,
                "reason": "The previous class number does not exist in the target version's class configuration.",
            }

    return {
        "student": args.student,
        "moved": moved,
        "before": before,
        "after": after,
        "return_to_previous_class_check": return_check,
        "causality_limit": (
            "Stored assignments prove what changed and what a one-student return would violate. They do not record "
            "which objective term caused the solver to select this move among multiple feasible assignments."
        ),
    }


def _get_dataset_columns(sess, _args) -> dict:
    """What this school's spreadsheet actually contains.

    The four built-in flags are not special here -- they are listed
    alongside whatever else the workbook turned out to have, because from
    the solver's point of view they never were special. A school with a
    "twins" column sees it in exactly the same shape.
    """
    df = sess.mapped_df
    if df is None:
        return {"error": "no_roster", "detail": "No roster has been loaded yet."}

    cols: list[dict] = []
    for key, field_name in CATEGORY_FIELDS.items():
        if field_name not in df.columns:
            continue
        cols.append(
            {
                "key": field_name,
                "label": BUILTIN_LABELS.get(key, key),
                "kind": "flag",
                "true_count": int(df[field_name].fillna(False).astype(bool).sum()),
                "builtin": True,
            }
        )
    for field_name, label in SEMANTIC_CATEGORY_FIELDS.items():
        if field_name not in df.columns:
            continue
        vals = [str(v) for v in df[field_name].dropna().unique().tolist()]
        cols.append(
            {
                "key": field_name,
                "label": label,
                "kind": "category",
                "values": vals[:MAX_LISTED_VALUES],
                "value_count": len(vals),
                "builtin": True,
            }
        )

    schema = getattr(sess, "dataset_schema", None)
    for extra in (schema.extras if schema else []):
        entry = {
            "key": extra.key,
            "label": extra.label,
            "kind": extra.kind,
            "source_column": extra.source_column,
            "filled_count": extra.filled_count,
            "builtin": False,
        }
        if extra.kind == "flag":
            entry["true_count"] = extra.true_count
        elif extra.kind == "category":
            entry["values"] = extra.values[:MAX_LISTED_VALUES]
            entry["value_count"] = len(extra.values)
        cols.append(entry)

    mapping = getattr(sess, "col_mapping", None)
    manual_fields = sorted(mapping.manual_fields) if mapping is not None else []
    source_fields = sorted(
        field for field, source_column in (mapping.mapping.items() if mapping is not None else []) if source_column is not None
    )
    friendship_rows = 0
    if FIELD_FRIEND_REQUESTS in df.columns:
        friendship_rows = int(
            df[FIELD_FRIEND_REQUESTS]
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        )
    validation = validate_students(df)
    friendship_resolution = resolve_requests(df)
    matched_edges = sum(len(targets) for targets in friendship_resolution.matched.values())
    parsed_requests = matched_edges + len(friendship_resolution.unmatched) + len(friendship_resolution.ambiguous)
    mutual_pairs = {
        tuple(sorted((requester, target)))
        for requester, targets in friendship_resolution.matched.items()
        for target in targets
        if requester in friendship_resolution.matched.get(target, [])
    }
    return {
        "total_students": len(df),
        "columns": cols,
        "source_fields": [{"key": field, "label": FIELD_LABELS_HE.get(field, field)} for field in source_fields],
        "manual_or_missing_from_source": [
            {
                "key": field,
                "label": FIELD_LABELS_HE.get(field, field),
                "meaning": (
                    "This field was not mapped from any column in the uploaded workbook. Its empty placeholder "
                    "does not prove that zero students belong to this category. It can be supplied manually."
                ),
            }
            for field in manual_fields
        ],
        "friendship_request_rows": friendship_rows,
        "friendship_data": {
            "students_with_entries": friendship_rows,
            "parsed_request_names": parsed_requests,
            "matched_request_edges": matched_edges,
            "mutual_pairs": len(mutual_pairs),
            "unmatched_names": len(friendship_resolution.unmatched),
            "ambiguous_names": len(friendship_resolution.ambiguous),
            "ready_for_optimization": bool(
                matched_edges > 0
                and not friendship_resolution.unmatched
                and not friendship_resolution.ambiguous
            ),
            "interpretation": (
                "students_with_entries counts students whose cell is non-empty; it is not the number of requests. "
                "parsed_request_names is the actual number of requested names. Data is ready only when requested "
                "names resolve without unmatched or ambiguous entries."
            ),
        },
        "validation": {
            "blocking_errors": sum(issue.severity == "error" for issue in validation.issues),
            "warnings": sum(issue.severity == "warning" for issue in validation.issues),
            "categories": sorted({issue.category for issue in validation.issues}),
        },
        "how_to_use": (
            "Use a `key` from this list as `group_field` on propose_capacity / propose_balance, or as "
            "`column` on query_roster. For a category-kind column also pass the specific value. Columns "
            "not listed here do not exist in this school's data -- ask the counselor rather than inventing one."
        ),
        "file_summary_rule": (
            "When summarizing the upload, describe source_fields as fields found in the workbook. Describe "
            "manual_or_missing_from_source only as fields not found in the workbook and available for manual "
            "entry. Never convert an empty generated placeholder into a claim that the school has zero such "
            "students. Use friendship_data, not friendship_request_rows, to describe friendship readiness or the "
            "number of requests. Friendship_request_rows=0 means friendship quality cannot be optimized or "
            "measured yet, not that requests failed."
        ),
    }


def _get_student_record(sess, args: GetStudentRecordArgs) -> dict:
    student_id = sess.token_map.id_for(args.student)
    if student_id is None or sess.mapped_df is None:
        return {"error": "unknown_student_token"}
    row = sess.mapped_df.loc[sess.mapped_df[FIELD_STUDENT_ID] == student_id]
    if row.empty:
        return {"error": "unknown_student_token"}
    record = row.iloc[0]
    safe_fields = {
        FIELD_CURRENT_SCHOOL,
        FIELD_CURRENT_CLASS,
        FIELD_ACADEMIC_LEVEL,
        *CATEGORY_FIELDS.values(),
    }
    safe_fields.update(item.key for item in getattr(sess.dataset_schema, "extras", []))
    values = {
        field: {
            "label": FIELD_LABELS_HE.get(field, next((item.label for item in sess.dataset_schema.extras if item.key == field), field)),
            "value": _clean_value(record.get(field)),
            "edited_in_project": field in (sess.student_data_edits.get(student_id, {}) or {}),
        }
        for field in sorted(safe_fields)
        if field in sess.mapped_df.columns
    }
    matched = sess.friendship_result.matched if sess.friendship_result else resolve_requests(sess.mapped_df).matched
    return {
        "student": args.student,
        "editable_values": values,
        "friendship_requests": {
            "resolved_request_count": len([other for other in matched.get(student_id, []) if other != student_id]),
            "raw_text_withheld_for_privacy": True,
        },
        "edit_boundary": (
            "The project copy may be corrected after explicit approval. Student id is immutable. Names and raw friendship "
            "text are withheld from the model; friendship changes should use resolved student tokens, not invented text."
        ),
    }


def _analyze_data_quality(sess, _args) -> dict:
    df = sess.mapped_df
    if df is None:
        return {"error": "no_roster", "detail": "No mapped workbook is available."}
    report = validate_students(df)
    issues = []
    for issue in report.issues:
        issues.append(
            {
                "category": issue.category,
                "severity": issue.severity,
                "message": issue.message,
                "affected_students": [sess.token_map.token_for(student_id) for student_id in issue.student_ids],
                "correction_rule": (
                    "Ask the counselor for the correct value. Do not infer a replacement from other students or from the assignment."
                ),
            }
        )

    friendship = sess.friendship_result or resolve_requests(df)
    unmatched_requesters = sorted({requester for requester, _raw in friendship.unmatched})
    ambiguous_requesters = sorted({requester for requester, _raw, _candidates in friendship.ambiguous})
    return {
        "total_students": len(df),
        "blocking_errors": len(report.errors),
        "warnings": len(report.warnings),
        "issues": issues,
        "friendship_resolution": {
            "unmatched_request_count": len(friendship.unmatched),
            "ambiguous_request_count": len(friendship.ambiguous),
            "requesters_with_unmatched_names": [sess.token_map.token_for(student_id) for student_id in unmatched_requesters],
            "requesters_with_ambiguous_names": [sess.token_map.token_for(student_id) for student_id in ambiguous_requesters],
            "raw_names_withheld_for_privacy": True,
        },
        "confirmed_project_edits": {
            "students_edited": len(sess.student_data_edits),
            "fields_edited": sum(len(values) for values in sess.student_data_edits.values()),
        },
        "safety": (
            "Suggest corrections from verified anomalies, but never invent a missing academic, support, origin, or friendship value. "
            "A concrete value must come from the counselor and requires explicit approval before it changes the project copy."
        ),
    }


def _query_roster(sess, args: QueryRosterArgs) -> dict:
    df = sess.mapped_df
    if df is None:
        return {"error": "no_roster", "detail": "No roster has been loaded yet."}

    mask = pd.Series(True, index=df.index)
    applied: dict[str, Any] = {}

    if args.column:
        # Accept either the column key or the friendly alias the built-in
        # flags have always used ("inclusion" as well as the field name).
        col = CATEGORY_FIELDS.get(args.column, args.column)
        if col not in df.columns:
            return {
                "error": "unknown_column",
                "detail": f"No column '{args.column}' in this dataset. Call get_dataset_columns to see what exists.",
            }
        if args.value is not None and str(args.value) != "":
            mask &= df[col].astype(str).str.strip() == str(args.value).strip()
            applied["column"], applied["value"] = args.column, args.value
        else:
            mask &= df[col].fillna(False).astype(bool)
            applied["column"] = args.column
    if args.assigned_class is not None:
        ctx = _result_ctx(sess)
        if ctx is None:
            return NO_RESULT
        _df, _cfg, _cons, assignment, _m = ctx
        target = args.assigned_class - 1
        mask &= df[FIELD_STUDENT_ID].map(lambda s: assignment.get(s) == target)
        applied["assigned_class"] = args.assigned_class

    sub = df[mask]
    limit = max(1, min(int(args.limit or 25), 100))
    ids = sub[FIELD_STUDENT_ID].tolist()
    return {
        "filters": applied,
        "count": len(sub),
        "total_roster": len(df),
        "tokens": [sess.token_map.token_for(s) for s in ids[:limit]],
        "truncated": len(ids) > limit,
        "academic_levels": _counts(sub[FIELD_ACADEMIC_LEVEL]) if len(sub) else {},
    }


def _get_assignment_versions(sess, _args) -> dict:
    """Measured version history only; qualitative judgment belongs to the agent."""
    versions = list(getattr(sess, "assignment_versions", []))
    if not versions:
        return {"count": 0, "current_version_id": None, "versions": []}

    rows = []
    previous = None
    for version in versions[-10:]:
        moved = None
        if previous is not None:
            student_ids = set(previous.assignment) | set(version.assignment)
            moved = sum(previous.assignment.get(sid) != version.assignment.get(sid) for sid in student_ids)
        rows.append(
            {
                "id": version.id,
                "number": version.number,
                "reason": version.reason,
                "mode": version.mode,
                "approved": version.approved,
                "is_current": version.id == sess.current_version_id,
                "moved_students_from_previous": moved,
                "metrics": _clean_value(version.metrics),
                "friendship_measurement": (
                    {
                        "available": True,
                        "students_with_requests": version.metrics.get("students_with_requests", 0),
                        "mutual_satisfied_pct": version.metrics.get("mutual_satisfied_pct", 0),
                        "two_friends_satisfied_pct": version.metrics.get("two_friends_satisfied_pct", 0),
                    }
                    if version.metrics.get("students_with_requests", 0) > 0
                    else {
                        "available": False,
                        "students_with_requests": 0,
                        "note": "No friendship requests exist in the source data. Zero percentages are not failures and must not be compared.",
                    }
                ),
            }
        )
        previous = version
    comparable = rows[-3:]
    metric_keys = ("objective_value", "violations_count", "class_size_spread", "academic_level_spread")
    equivalent = len(comparable) > 1 and all(
        all(item["metrics"].get(key) == comparable[0]["metrics"].get(key) for key in metric_keys)
        and (
            not item["friendship_measurement"]["available"]
            or (
                item["metrics"].get("mutual_satisfied_pct") == comparable[0]["metrics"].get("mutual_satisfied_pct")
                and item["metrics"].get("two_friends_satisfied_pct") == comparable[0]["metrics"].get("two_friends_satisfied_pct")
            )
        )
        for item in comparable[1:]
    )
    return {
        "count": len(versions),
        "current_version_id": sess.current_version_id,
        "versions": rows,
        "latest_options_equivalent_on_reported_metrics": equivalent,
        "recommendation_rule": (
            "If options are equivalent on reported metrics, say there is no measured quality reason to prefer one. "
            "Keeping the current option can avoid another change, but does not make it a better assignment."
        ),
        "measurement_note": "All metrics and moved-student counts were computed from stored assignments.",
    }


def _assignment_diagnostic_findings(sess, df, cfg, constraints, assignment, matched, gm) -> list[dict]:
    """Turn raw assignment metrics into ranked, privacy-safe facts.

    GPT-4o mini is much more useful when it receives the important patterns
    already calculated. These are observations and test suggestions, not
    invented causes. Student identities remain opaque tokens.
    """
    num_classes = cfg.num_classes
    student_ids = df[FIELD_STUDENT_ID].tolist()
    total_students = len(student_ids)
    denominator = total_students if cfg.denominator_all_students else gm.students_with_requests
    findings: list[tuple[int, dict]] = []

    def add(score: int, finding: dict) -> None:
        findings.append((score, finding))

    def distribution(field: str, value=None, truthy: bool = False) -> list[int]:
        if field not in df.columns:
            return []
        if truthy:
            members = set(df.loc[df[field].fillna(False).astype(bool), FIELD_STUDENT_ID].tolist())
        else:
            members = set(df.loc[df[field] == value, FIELD_STUDENT_ID].tolist())
        return [sum(1 for sid in members if assignment.get(sid) == class_index) for class_index in range(num_classes)]

    def balance_objective(field: str) -> Optional[dict]:
        for constraint in constraints:
            if not constraint.active or constraint.type != "balance":
                continue
            group = constraint.args.get("group", {})
            if (group.get("kind") == "field_all_values" and group.get("field") == field) or (
                group.get("kind") == "fields" and field in group.get("fields", [])
            ):
                return {
                    "constraint_id": constraint.id,
                    "label_hebrew": constraint.label_hebrew,
                    "weight": constraint.args.get("weight", 1),
                    "hard": constraint.hard,
                }
        return None

    def capacity_rule(field: str) -> Optional[dict]:
        for constraint in constraints:
            if not constraint.active or constraint.type != "capacity":
                continue
            group = constraint.args.get("group", {})
            if group.get("kind") == "field" and group.get("field") == field:
                return {
                    "constraint_id": constraint.id,
                    "min": constraint.args.get("min"),
                    "max": constraint.args.get("max"),
                    "hard": constraint.hard,
                }
        return None

    if gm.violations_count:
        add(
            120,
            {
                "kind": "mandatory_rule_violations",
                "priority": "critical",
                "evidence": {
                    "violation_count": gm.violations_count,
                    "violations": df_records(violations_report(df, assignment, constraints, num_classes)),
                },
                "interpretation_limit": "These are current verified violations and must be resolved before approval.",
                "suggested_test": None,
            },
        )

    if gm.class_size_spread > 1:
        ideal_min = total_students // num_classes
        ideal_max = -(-total_students // num_classes)
        size_rule = _class_size_rule(constraints)
        add(
            95,
            {
                "kind": "class_size_imbalance",
                "priority": "high",
                "evidence": {
                    "sizes_by_class": gm.class_sizes,
                    "spread": gm.class_size_spread,
                    "mathematically_tight_range": [ideal_min, ideal_max],
                },
                "interpretation_limit": "This proves the gap exists, not why the solver selected it.",
                "suggested_test": (
                    {
                        "tool": "simulate_capacity_change",
                        "constraint_id": size_rule.get("id"),
                        "min": ideal_min,
                        "max": ideal_max,
                    }
                    if size_rule and size_rule.get("id")
                    else None
                ),
            },
        )

    for field, kind, label in (
        (FIELD_ACADEMIC_LEVEL, "academic_distribution", "הישגים לימודיים"),
        (FIELD_CURRENT_SCHOOL, "source_school_concentration", 'בתי ספר קודמים'),
        (FIELD_CURRENT_CLASS, "previous_class_concentration", "כיתות קודמות"),
    ):
        if field not in df.columns:
            continue
        rows = []
        for value in df[field].dropna().unique().tolist():
            if not str(value).strip():
                continue
            counts = distribution(field, value=value)
            rows.append(
                {
                    "value": _clean_value(value),
                    "total": sum(counts),
                    "counts_by_class": counts,
                    "spread": max(counts) - min(counts) if counts else 0,
                }
            )
        rows.sort(key=lambda row: (row["spread"], row["total"]), reverse=True)
        uneven = [row for row in rows if row["spread"] >= 2]
        if uneven:
            objective = balance_objective(field)
            suggested = None
            if objective and not objective["hard"]:
                suggested = {
                    "tool": "simulate_balance_priority",
                    "constraint_id": objective["constraint_id"],
                    "weight": max(1.0, float(objective["weight"])) * 2,
                }
            score = 88 if kind == "academic_distribution" else 72
            add(
                score + min(uneven[0]["spread"], 6),
                {
                    "kind": kind,
                    "priority": "high" if uneven[0]["spread"] >= 3 else "medium",
                    "label": label,
                    "evidence": {"worst_distributions": uneven[:5]},
                    "active_objective": objective,
                    "interpretation_limit": "A concentration is measured; its cause is not established without a counterfactual.",
                    "suggested_test": suggested,
                },
            )

    support_rows = []
    for key, field in CATEGORY_FIELDS.items():
        if field not in df.columns:
            continue
        counts = distribution(field, truthy=True)
        total = sum(counts)
        spread = max(counts) - min(counts) if counts else 0
        if total and spread:
            rule = capacity_rule(field)
            tight_min = total // num_classes
            tight_max = -(-total // num_classes)
            support_rows.append(
                {
                    "category": key,
                    "label_hebrew": BUILTIN_LABELS[key],
                    "total": total,
                    "counts_by_class": counts,
                    "spread": spread,
                    "active_capacity_rule": rule,
                    "mathematically_tight_range": [tight_min, tight_max],
                }
            )
    support_rows.sort(key=lambda row: row["spread"], reverse=True)
    if support_rows:
        worst_support = support_rows[0]
        support_rule = worst_support.get("active_capacity_rule")
        support_tight = worst_support["mathematically_tight_range"]
        support_test = None
        if support_rule and support_rule.get("constraint_id") and (
            support_rule.get("min") != support_tight[0] or support_rule.get("max") != support_tight[1]
        ):
            support_test = {
                "tool": "simulate_capacity_change",
                "constraint_id": support_rule["constraint_id"],
                "min": support_tight[0],
                "max": support_tight[1],
            }
        add(
            82 + min(support_rows[0]["spread"], 5),
            {
                "kind": "support_category_distribution",
                "priority": "high" if support_rows[0]["spread"] >= 2 else "medium",
                "evidence": {"uneven_categories": support_rows},
                "interpretation_limit": (
                    "Counts may be uneven while still satisfying an allowed hard range. Treat this as a measured distribution, "
                    "not a violation unless the active rule says so."
                ),
                "suggested_test": support_test,
            },
        )

    requested_rows = []
    mutual_eligible = 0
    two_eligible = 0
    class_social = [
        {"class": class_index + 1, "students_with_requests": 0, "with_no_requested_friend": 0}
        for class_index in range(num_classes)
    ]
    for sid in student_ids:
        requests = [other for other in matched.get(sid, []) if other != sid]
        if not requests:
            continue
        mutual_requests = [other for other in requests if sid in matched.get(other, [])]
        same = [other for other in requests if assignment.get(other) == assignment.get(sid)]
        if mutual_requests:
            mutual_eligible += 1
        if len(requests) >= 2:
            two_eligible += 1
        class_index = assignment.get(sid)
        if class_index is not None and 0 <= class_index < num_classes:
            class_social[class_index]["students_with_requests"] += 1
            if not same:
                class_social[class_index]["with_no_requested_friend"] += 1
        if not same:
            requested_rows.append(
                {
                    "student": sess.token_map.token_for(sid),
                    "class": class_index + 1 if class_index is not None else None,
                    "requests_made": len(requests),
                    "mutual_requests_available": len(mutual_requests),
                }
            )

    for row in class_social:
        count = row["students_with_requests"]
        row["no_friend_pct_among_requesters"] = round(100 * row["with_no_requested_friend"] / count, 1) if count else None

    if gm.students_with_requests:
        friendship_objective = next(
            (constraint for constraint in constraints if constraint.active and constraint.type == "friendship_objective"),
            None,
        )
        mutual_ceiling = round(100 * mutual_eligible / denominator, 1) if denominator else 0.0
        two_ceiling = round(100 * two_eligible / denominator, 1) if denominator else 0.0
        suggested = None
        if friendship_objective is not None:
            old_mutual = int(friendship_objective.args.get("weight_mutual", 0))
            old_two = int(friendship_objective.args.get("weight_two_friends", 0))
            suggested = {
                "tool": "simulate_friendship_priority",
                "constraint_id": friendship_objective.id,
                "weight_mutual": max(1, old_mutual * 2),
                "weight_two_friends": max(1, old_two * 2),
            }
        if requested_rows or gm.mutual_satisfied_pct < mutual_ceiling or gm.two_friends_satisfied_pct < two_ceiling:
            add(
                90 if requested_rows else 76,
                {
                    "kind": "friendship_outcomes",
                    "priority": "high" if len(requested_rows) >= max(3, gm.students_with_requests // 10) else "medium",
                    "evidence": {
                        "students_with_requests": gm.students_with_requests,
                        "current_mutual_pct": gm.mutual_satisfied_pct,
                        "mutual_data_ceiling_pct": mutual_ceiling,
                        "current_two_friends_pct": gm.two_friends_satisfied_pct,
                        "two_friends_data_ceiling_pct": two_ceiling,
                        "students_with_no_requested_friend": len(requested_rows),
                        "attention_students": requested_rows[:12],
                        "class_social_outcomes": class_social,
                        "percentage_denominator": "all_students" if cfg.denominator_all_students else "students_with_requests",
                    },
                    "interpretation_limit": (
                        "The data ceiling only reflects whether qualifying requests exist. It does not prove that the ceiling is "
                        "jointly feasible with the mandatory rules. A solver trial is required."
                    ),
                    "suggested_test": suggested,
                },
            )
    else:
        add(
            45,
            {
                "kind": "friendship_data_unavailable",
                "priority": "information",
                "evidence": {"students_with_requests": 0},
                "interpretation_limit": "Zero friendship percentages are not poor outcomes when no requests exist.",
                "suggested_test": None,
            },
        )

    locked = getattr(sess, "locked_assignment", {}) or {}
    if locked:
        lock_counts = [0] * num_classes
        for class_index in locked.values():
            if 0 <= class_index < num_classes:
                lock_counts[class_index] += 1
        add(
            55,
            {
                "kind": "manual_locks",
                "priority": "information",
                "evidence": {"locked_students": len(locked), "locks_by_class": lock_counts},
                "interpretation_limit": "Locks reduce the solver's freedom but are not proven blockers until a relevant trial fails.",
                "suggested_test": None,
            },
        )

    if str(gm.solver_status).upper() != "OPTIMAL":
        add(
            68,
            {
                "kind": "optimality_not_proven",
                "priority": "medium",
                "evidence": {"solver_status": gm.solver_status, "time_limit_seconds": cfg.time_limit_seconds},
                "interpretation_limit": "The assignment is valid, but the run did not prove that no better objective value exists.",
                "suggested_test": None,
            },
        )

    findings.sort(key=lambda item: item[0], reverse=True)
    return [_clean_value(finding) for _score, finding in findings[:10]]


def _analyze_assignment_quality(sess, _args) -> dict:
    """A compact, whole-assignment evidence packet for the reasoning model.

    This intentionally reports observations and configuration separately.
    A snapshot can prove that a gap exists and a rule can prove that the gap
    was allowed; neither alone proves which competing objective caused the
    solver to choose this exact arrangement. That requires a what-if run.
    """
    ctx = _result_ctx(sess)
    if ctx is None:
        return NO_RESULT
    df, cfg, constraints, assignment, matched = ctx
    gm = compute_global_metrics(
        df,
        assignment,
        matched,
        constraints,
        cfg.num_classes,
        cfg.denominator_all_students,
        sess.opt_result.status_name,
        sess.opt_result.wall_time_seconds,
        sess.opt_result.objective_value,
    )
    violations = df_records(violations_report(df, assignment, constraints, cfg.num_classes))
    objectives = []
    for constraint in constraints:
        if not constraint.active or constraint.type not in {"balance", "friendship_objective"}:
            continue
        item = {
            "id": constraint.id,
            "type": constraint.type,
            "label_hebrew": constraint.label_hebrew,
            "hard": constraint.hard,
            "group": constraint.args.get("group"),
        }
        for key in ("weight", "weight_mutual", "weight_two_friends"):
            if constraint.args.get(key) is not None:
                item[key] = constraint.args[key]
        objectives.append(_clean_value(item))

    diagnostic_findings = _assignment_diagnostic_findings(
        sess,
        df,
        cfg,
        constraints,
        assignment,
        matched,
        gm,
    )

    status = str(sess.opt_result.status_name or "")
    if status.upper() == "OPTIMAL":
        status_note = (
            "The solver proved this run optimal for the active mathematical objective. That does not mean every "
            "human notion of balance was part of the objective."
        )
    else:
        status_note = (
            "The solver found a valid assignment but did not prove it was the best possible one within the run. "
            "A longer or differently prioritized run may improve it."
        )

    return _clean_value(
        {
            "measured_current_state": dict(gm.__dict__),
            "class_profiles": df_records(
                class_overview_table(df, assignment, matched, constraints, cfg.num_classes)
            ),
            "hard_rule_compliance": {
                "all_satisfied": len(violations) == 0,
                "violation_count": len(violations),
                "violations": violations,
            },
            "class_size_rule": _class_size_rule(constraints),
            "active_optimization_priorities": objectives,
            "diagnostic_findings": diagnostic_findings,
            "manual_context": {
                "locked_students": len(getattr(sess, "locked_assignment", {}) or {}),
                "result_is_stale": sess.result_state()["is_stale"],
            },
            "solver_interpretation": {
                "status": status,
                "time_limit_seconds": cfg.time_limit_seconds,
                "wall_time_seconds": sess.opt_result.wall_time_seconds,
                "note": status_note,
            },
            "metric_definitions": {
                "class_size_spread": "Largest class size minus smallest class size. Zero means equal sizes.",
                "academic_level_spread": (
                    "For each academic category, take the largest per-class count minus the smallest, then sum "
                    "those gaps. Lower is more even. This is not a range of grades and not a count of levels."
                ),
                "friendship_percentages": (
                    "Measured placement outcomes. Interpret only when students_with_requests is greater than zero; "
                    "the configured denominator may include all students."
                ),
                "satisfied_partial_unsatisfied_requests": (
                    "Counts of students with friend requests: satisfied means all of that student's requests were "
                    "placed with her, partial means at least one but not all, and unsatisfied means none. These are "
                    "counts, not percentages, and they do not measure fairness."
                ),
            },
            "reasoning_boundary": (
                "Use the snapshot to identify and quantify imbalances. Use the active rules to explain what was "
                "allowed and what the solver was asked to value. Do not claim that a specific objective caused an "
                "exact placement unless a hard rule or a measured counterfactual supports that claim."
            ),
        }
    )


_DISPATCH = {
    "get_dataset_columns": _get_dataset_columns,
    "get_solve_summary": _get_solve_summary,
    "get_class_sizes": _get_class_sizes,
    "get_class_composition": _get_class_composition,
    "get_violations": _get_violations,
    "get_active_rules": _get_active_rules,
    "analyze_rule_feasibility": _analyze_rule_feasibility,
    "explain_student_placement": _explain_student_placement,
    "compare_student_versions": _compare_student_versions,
    "query_roster": _query_roster,
    "get_assignment_versions": _get_assignment_versions,
    "analyze_assignment_quality": _analyze_assignment_quality,
    "get_student_record": _get_student_record,
    "analyze_data_quality": _analyze_data_quality,
}


def is_read_tool(name: str) -> bool:
    return name in _DISPATCH


def execute_read_tool(name: str, raw_args: dict, sess) -> dict:
    """Validate + run one read tool. Never raises for model error: a bad
    tool call comes back as an `error` field the model can read and recover
    from, because an exception here would abort the whole turn over
    something the model could have fixed by trying again."""
    model_cls = READ_TOOL_MODELS.get(name)
    if model_cls is None:
        return {"error": "unknown_tool", "detail": name}
    try:
        args = model_cls(**(raw_args or {}))
    except Exception as e:
        return {"error": "bad_arguments", "detail": str(e)}
    try:
        return _DISPATCH[name](sess, args)
    except Exception as e:  # pragma: no cover - defensive
        return {"error": "tool_failed", "detail": str(e)}
