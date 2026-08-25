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
    FIELD_STUDENT_ID,
)
from src.metrics import class_overview_table, compute_global_metrics, violations_report

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
    "explain_student_placement": ExplainStudentPlacementArgs,
    "query_roster": QueryRosterArgs,
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
    "explain_student_placement": "קרא היכן שובצה תלמידה מסוימת ומה קרה לבקשות החברות שלה.",
    "query_roster": "ספור או דגום תלמידות לפי כל עמודה שקיימת בנתונים (ראה get_dataset_columns) או לפי כיתה משובצת.",
}


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
        entry = {
            "id": c.id,
            "type": c.type,
            "hard": c.hard,
            "label_hebrew": c.label_hebrew,
            "source": c.source,
        }
        if group:
            entry["group"] = group.get("field") or group.get("kind")
        for k in ("min", "max", "weight"):
            if args.get(k) is not None:
                entry[k] = args[k]
        out.append(_clean_value(entry))
    return {"count": len(out), "rules": out}


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
    return info


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

    return {
        "total_students": len(df),
        "columns": cols,
        "how_to_use": (
            "Use a `key` from this list as `group_field` on propose_capacity / propose_balance, or as "
            "`column` on query_roster. For a category-kind column also pass the specific value. Columns "
            "not listed here do not exist in this school's data -- ask the counselor rather than inventing one."
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


_DISPATCH = {
    "get_dataset_columns": _get_dataset_columns,
    "get_solve_summary": _get_solve_summary,
    "get_class_sizes": _get_class_sizes,
    "get_class_composition": _get_class_composition,
    "get_violations": _get_violations,
    "get_active_rules": _get_active_rules,
    "explain_student_placement": _explain_student_placement,
    "query_roster": _query_roster,
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
