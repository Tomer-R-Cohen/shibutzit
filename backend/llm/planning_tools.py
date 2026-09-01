"""Planning tools: what the agent can do before a spreadsheet exists.

The chat used to refuse to run at all without `sess.mapped_df`. That put the
conversation in the wrong order -- the counselor had to finish building the
file before she could discuss what belongs in it, when the discussion is
precisely what determines the answer.

These tools are what "advisor" means concretely. They execute immediately
like the read tools: recording that the file will need a twins column is a
note on a checklist, not a change to anyone's placement, so making the
counselor confirm a card for it would be ceremony without safety. Rules
still go through propose -> confirm, unchanged.

`set_class_count` is here rather than in the write tools for the same reason
it is a stepper in the inspector and not a chat proposal: it is a single
number the counselor states outright, and it is reversible in one click.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from src.data_requirements import DataRequirement, summarize

logger = logging.getLogger(__name__)

MAX_REQUIREMENTS = 25


class NoArgs(BaseModel):
    pass


class NoteRequiredDataArgs(BaseModel):
    label: str = Field(description="The exact Hebrew column header the counselor should create, e.g. תאומות")
    kind: str = Field(description="One of: flag (yes/blank), category (one value from a list), number")
    reason: str = Field(description="One short Hebrew sentence: which rule or goal needs this column")
    values: Optional[list[str]] = Field(
        default=None, description="For a category column, the values it should take, e.g. ['רמת אביב','צפון']"
    )


class DropRequiredDataArgs(BaseModel):
    label: str = Field(description="The column header to remove from the checklist, exactly as it was added")


class SetClassCountArgs(BaseModel):
    num_classes: int = Field(description="How many classes to split the year into")


class RequestSolverRunArgs(BaseModel):
    alternatives: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Number of real assignment alternatives explicitly requested. Use 3 for 'several options'.",
    )
    explain_results: bool = Field(
        default=True,
        description="Whether the user asked for an explanation or details about the resulting assignments.",
    )


class RememberProjectNoteArgs(BaseModel):
    note: str = Field(
        description=(
            "A concise durable project instruction in Hebrew, such as 'Never relax the inclusion rule' or "
            "'Friendship is more important than source-school balance'."
        )
    )


class RemoveProjectNoteArgs(BaseModel):
    note: str = Field(description="The durable project instruction to remove, matching its meaning or wording.")


PLANNING_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "get_data_requirements": NoArgs,
    "note_required_data": NoteRequiredDataArgs,
    "drop_required_data": DropRequiredDataArgs,
    "set_class_count": SetClassCountArgs,
    "request_solver_run": RequestSolverRunArgs,
    "remember_project_note": RememberProjectNoteArgs,
    "remove_project_note": RemoveProjectNoteArgs,
}

PLANNING_TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_data_requirements": "קרא את רשימת העמודות שסוכם שיהיו בקובץ, ואילו מהן כבר קיימות בקובץ שנטען.",
    "note_required_data": (
        "רשום שהקובץ יצטרך עמודה מסוימת. השתמש/י בזה כשהיועצת מתארת שיקול שאין לו עדיין עמודה בנתונים "
        "(למשל תאומות, אחיות, שכונה) - זו הדרך להגיד לה מה למלא באקסל."
    ),
    "drop_required_data": "הסר עמודה מרשימת הדרישות, אם היועצת החליטה שאינה נחוצה.",
    "set_class_count": "קבע לכמה כיתות לחלק את השכבה. אפשר לקרוא לזה גם לפני שנטען קובץ.",
    "request_solver_run": (
        "בקש מהממשק להריץ את השיבוץ האמיתי עם הנתונים והכללים המאושרים כעת. "
        "השתמש/י רק כשהמשתמשת ביקשה במפורש להריץ, לנסות שוב או להפיק שיבוץ; לעולם לא ביוזמתך."
    ),
    "remember_project_note": (
        "שמור הנחיית פרויקט מתמשכת שהמשתמשת מבקשת לזכור להמשך, למשל כלל שאסור לרכך או סדר עדיפויות. "
        "אין להשתמש בזה במקום כלל מספרי שניתן לייצג ככלל שיבוץ מובנה."
    ),
    "remove_project_note": "הסר הנחיית פרויקט מתמשכת כשהמשתמשת חוזרת בה במפורש.",
}


def build_planning_tool_definitions() -> list[dict]:
    tools = []
    for name, model in PLANNING_TOOL_MODELS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("properties", {})
        tools.append(
            {"type": "function", "function": {"name": name, "description": PLANNING_TOOL_DESCRIPTIONS[name], "parameters": schema}}
        )
    return tools


def _get_data_requirements(sess, _args) -> dict:
    out = summarize(sess.data_requirements, getattr(sess, "dataset_schema", None))
    out["has_dataset"] = sess.mapped_df is not None
    if not out["requirements"]:
        out["note"] = (
            "Nothing recorded yet. As the counselor describes considerations that have no column in the "
            "data, record each one with note_required_data."
        )
    return out


def _note_required_data(sess, args: NoteRequiredDataArgs) -> dict:
    kind = args.kind.strip().lower()
    if kind not in ("flag", "category", "number"):
        return {"error": "bad_kind", "detail": "kind must be one of: flag, category, number."}
    if len(sess.data_requirements) >= MAX_REQUIREMENTS:
        return {"error": "too_many", "detail": f"The checklist already has {MAX_REQUIREMENTS} columns."}

    label = args.label.strip()
    if not label:
        return {"error": "bad_arguments", "detail": "label is required."}
    # Re-recording the same column is a no-op rather than a duplicate: the
    # model often restates a requirement while summarising the conversation.
    existing = next((r for r in sess.data_requirements if r.label.strip().lower() == label.lower()), None)
    if existing is not None:
        existing.reason = args.reason or existing.reason
        if args.values:
            existing.values = list(args.values)
        return {"updated": True, **existing.to_dict()}

    req = DataRequirement(label=label, kind=kind, reason=args.reason, values=list(args.values or []))
    sess.data_requirements.append(req)
    return {"added": True, **req.to_dict()}


def _drop_required_data(sess, args: DropRequiredDataArgs) -> dict:
    label = args.label.strip().lower()
    before = len(sess.data_requirements)
    sess.data_requirements = [r for r in sess.data_requirements if r.label.strip().lower() != label]
    if len(sess.data_requirements) == before:
        return {"error": "not_found", "detail": f"No requirement named '{args.label}'."}
    return {"removed": True, "label": args.label}


def _set_class_count(sess, args: SetClassCountArgs) -> dict:
    if not 2 <= args.num_classes <= 20:
        return {"error": "bad_arguments", "detail": "num_classes must be between 2 and 20."}

    previous = sess.run_config.num_classes
    sess.run_config.num_classes = args.num_classes
    # The class-size rule's bounds are derived from roster size and class
    # count, so they have to move with it -- otherwise the next solve fails
    # against numbers computed for a different number of classes.
    if sess.mapped_df is not None:
        from ..solver_inputs import sync_class_size_bounds

        sync_class_size_bounds(sess, sess.mapped_df)
        if previous != args.num_classes:
            sess.mark_inputs_changed()
    return {"num_classes": args.num_classes, "previous": previous, "size_rule_rescaled": sess.mapped_df is not None}


def _request_solver_run(sess, _args: RequestSolverRunArgs) -> dict:
    if sess.mapped_df is None:
        return {"error": "no_dataset", "detail": "A workbook must be uploaded before the solver can run."}
    return {
        "solver_run_requested": True,
        "num_classes": sess.run_config.num_classes,
        "active_rules": sum(1 for c in sess.constraints if c.active),
        "alternatives": _args.alternatives,
        "explain_results": _args.explain_results,
        "note": "The frontend will run the existing solver with the current confirmed session inputs.",
    }


def _remember_project_note(sess, args: RememberProjectNoteArgs) -> dict:
    note = " ".join(args.note.split()).strip()
    if not note:
        return {"error": "bad_arguments", "detail": "note is required"}
    if not any(existing.casefold() == note.casefold() for existing in sess.user_notes):
        sess.user_notes.append(note)
        sess.user_notes = sess.user_notes[-30:]
    return {"remembered": True, "note": note}


def _remove_project_note(sess, args: RemoveProjectNoteArgs) -> dict:
    needle = " ".join(args.note.split()).strip().casefold()
    matches = [n for n in sess.user_notes if needle in n.casefold() or n.casefold() in needle]
    if not matches:
        return {"error": "not_found", "detail": "No matching project note was found."}
    sess.user_notes = [n for n in sess.user_notes if n not in matches]
    return {"removed": True, "notes": matches}


_PLANNING_DISPATCH = {
    "get_data_requirements": _get_data_requirements,
    "note_required_data": _note_required_data,
    "drop_required_data": _drop_required_data,
    "set_class_count": _set_class_count,
    "request_solver_run": _request_solver_run,
    "remember_project_note": _remember_project_note,
    "remove_project_note": _remove_project_note,
}

# Tools that change persisted session state and therefore need a store.save()
# after the turn, plus a refresh signal to the UI.
MUTATING_PLANNING_TOOLS = {
    "note_required_data",
    "drop_required_data",
    "set_class_count",
    "remember_project_note",
    "remove_project_note",
}


def is_planning_tool(name: str) -> bool:
    return name in _PLANNING_DISPATCH


def execute_planning_tool(name: str, raw_args: dict, sess) -> dict:
    model_cls = PLANNING_TOOL_MODELS.get(name)
    if model_cls is None:
        return {"error": "unknown_tool", "detail": name}
    try:
        args = model_cls(**(raw_args or {}))
    except Exception as e:
        return {"error": "bad_arguments", "detail": str(e)}
    try:
        return _PLANNING_DISPATCH[name](sess, args)
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("planning tool %s failed", name)
        return {"error": "tool_failed", "detail": str(e)}
