"""The LLM-facing tool surface: typed proposal/modification tools, one per
constraint shape, rather than a single polymorphic tool. Narrow, strictly
typed schemas are what keep a cheap model's misparse rate low -- the model
never has to fill in a nested discriminated union correctly, it just picks
the one tool that matches what the counselor said.

Each tool's Pydantic model is the single source of truth for both (a) the
JSON schema handed to the LLM (`build_tool_definitions`) and (b) validating
whatever the LLM actually returns before it's ever shown to the counselor
or touches `src.constraints`.

Tools never apply anything directly -- `args_to_constraint` only builds a
`Constraint` object; the caller (backend/routers/chat.py) holds it as a
pending proposal until the counselor confirms it.
"""

from __future__ import annotations

from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from src.constraints import Constraint

# Was a closed Literal of this school's four categories, which meant the
# model physically could not name a fifth one -- a school with a "twins"
# column had no way to express a rule about it. It is now a free string
# validated at build time against the columns this particular dataset
# actually has (see `_resolve_field`), so the allowed set comes from the
# uploaded workbook rather than from this file.
_GROUP_FIELD_DESCRIPTION = (
    "A column key to constrain, exactly as returned by get_dataset_columns "
    "(e.g. differential, ethiopian_origin, or an x_-prefixed key from this "
    "school's own spreadsheet). Omit and use group_members for an ad hoc group."
)

# The semantic flag columns every dataset has, whatever else it carries.
BUILTIN_FLAG_FIELDS = {"differential", "ethiopian_origin", "inclusion", "hamar"}


class ToolArgumentError(Exception):
    """Raised when validated tool args can't be turned into a Constraint
    (e.g. an unresolvable student token, or a reference to a nonexistent
    constraint id)."""


class ProposeSeparateArgs(BaseModel):
    student_a: str = Field(description="Anonymized token for the first student, e.g. STUDENT_a1b2c3")
    student_b: str = Field(description="Anonymized token for the second student")
    hard: bool = Field(description="true = mandatory requirement, false = soft preference")
    rationale_hebrew: str = Field(description="One short plain-Hebrew sentence explaining the rule, shown to the counselor to confirm")


class ProposeTogetherArgs(BaseModel):
    student_a: str = Field(description="Anonymized token for the first student")
    student_b: str = Field(description="Anonymized token for the second student")
    mode: Literal["mutual", "one_sided"] = Field(default="mutual", description="Whether the request was mutual or one-sided")
    hard: bool = Field(description="true = mandatory requirement, false = soft preference")
    rationale_hebrew: str = Field(description="One short plain-Hebrew sentence explaining the rule")


class ProposeAtLeastOneOfArgs(BaseModel):
    student: str = Field(description="Anonymized token for the student who needs at least one requested classmate")
    candidates: list[str] = Field(min_length=1, description="Anonymized tokens of acceptable co-placement candidates")
    hard: bool = Field(description="true = mandatory requirement, false = soft preference")
    rationale_hebrew: str = Field(description="One short plain-Hebrew sentence explaining the rule")


class ProposeCapacityArgs(BaseModel):
    group_field: Optional[str] = Field(default=None, description=_GROUP_FIELD_DESCRIPTION)
    group_value: Optional[str] = Field(
        default=None,
        description=(
            "For a category-kind column, the single value to constrain (e.g. group_field='x_שכונה', "
            "group_value='רמת אביב'). Omit for flag-kind columns, which are simply true/false."
        ),
    )
    group_members: Optional[list[str]] = Field(
        default=None, description="Anonymized tokens forming an ad hoc group the counselor just described (not an existing data column)"
    )
    group_label_hebrew: Optional[str] = Field(default=None, description="Short Hebrew label for the ad hoc group; required when group_members is used")
    min: Optional[int] = Field(default=None, description="Minimum count of this group allowed per class; omit for no minimum")
    max: Optional[int] = Field(default=None, description="Maximum count of this group allowed per class; omit for no maximum")
    hard: bool = Field(description="true = mandatory requirement, false = soft preference")
    rationale_hebrew: str = Field(description="One short plain-Hebrew sentence explaining the rule")


class ProposeBalanceArgs(BaseModel):
    group_field: Optional[str] = Field(default=None, description=_GROUP_FIELD_DESCRIPTION)
    group_value: Optional[str] = Field(
        default=None, description="For a category-kind column, the single value to spread evenly. Omit to spread a flag column."
    )
    group_members: Optional[list[str]] = Field(default=None, description="Anonymized tokens forming an ad hoc group to spread evenly")
    group_label_hebrew: Optional[str] = Field(default=None, description="Short Hebrew label for the ad hoc group; required when group_members is used")
    weight: float = Field(default=1.0, description="Relative importance of this balance preference")
    hard: bool = Field(default=False, description="Almost always false (a soft preference); true means an exact equal split is mandatory")
    rationale_hebrew: str = Field(description="One short plain-Hebrew sentence explaining the rule")


class ModifyConstraintArgs(BaseModel):
    constraint_id: str = Field(description="id of the existing rule to change, from the active rules list in context")
    hard: Optional[bool] = Field(default=None, description="Set to change whether the rule is mandatory or a soft preference")
    active: Optional[bool] = Field(default=None, description="Set to false to deactivate the rule without deleting it")
    rationale_hebrew: str = Field(description="One short plain-Hebrew sentence explaining the change, shown to the counselor to confirm")


class RemoveConstraintArgs(BaseModel):
    constraint_id: str = Field(description="id of the existing rule to remove, from the active rules list in context")
    rationale_hebrew: str = Field(description="One short plain-Hebrew sentence explaining why, shown to the counselor to confirm")


TOOL_MODELS: dict[str, type[BaseModel]] = {
    "propose_separate": ProposeSeparateArgs,
    "propose_together": ProposeTogetherArgs,
    "propose_at_least_one_of": ProposeAtLeastOneOfArgs,
    "propose_capacity": ProposeCapacityArgs,
    "propose_balance": ProposeBalanceArgs,
    "modify_constraint": ModifyConstraintArgs,
    "remove_constraint": RemoveConstraintArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "propose_separate": "הצע כלל: שתי תלמידות ספציפיות לא ישובצו לאותה כיתה.",
    "propose_together": "הצע כלל: שתי תלמידות ספציפיות ישובצו לאותה כיתה.",
    "propose_at_least_one_of": "הצע כלל: תלמידה מסוימת תשובץ עם לפחות אחת מקבוצת מועמדות נתונה.",
    "propose_capacity": "הצע כלל מכסה: מספר מינימלי/מקסימלי של תלמידות מקבוצה (קטגוריה קיימת או קבוצה אד-הוק) בכל כיתה.",
    "propose_balance": "הצע כלל איזון: לפזר קבוצה (קטגוריה קיימת או קבוצה אד-הוק) באופן שווה ככל האפשר בין הכיתות.",
    "modify_constraint": "שנה כלל קיים (הפוך לקשה/רך, הפעל/בטל), על פי מזהה מהרשימה הפעילה.",
    "remove_constraint": "הסר כלל קיים, על פי מזהה מהרשימה הפעילה.",
}


def build_tool_definitions() -> list[dict]:
    """OpenAI-style `tools=[...]` list, generated from the Pydantic models
    above so the schema and the validation can never drift apart."""
    tools = []
    for name, model in TOOL_MODELS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "parameters": schema,
                },
            }
        )
    return tools


def _resolve_field(group_field: str, allowed_fields: Optional[set[str]]) -> None:
    """Reject a column this dataset doesn't have, before it reaches a rule.

    Since `group_field` stopped being a closed enum, nothing in the schema
    stops the model inventing a plausible-sounding column. Catching it here
    turns a hallucinated field into a clarifying question -- the alternative
    is a constraint whose group silently resolves to zero students, which
    looks like it applied and does nothing.
    """
    if allowed_fields is None:  # caller didn't supply a dataset; skip the check
        return
    if group_field not in allowed_fields:
        known = ", ".join(sorted(allowed_fields)) or "(none)"
        raise ToolArgumentError(f"unknown column '{group_field}'. Columns in this dataset: {known}")


def _resolve_group(
    group_field: Optional[str],
    group_members: Optional[list[str]],
    group_label_hebrew: Optional[str],
    detokenize: Callable[[str], Optional[int]],
    allowed_fields: Optional[set[str]] = None,
    group_value: Optional[str] = None,
    field_kinds: Optional[dict[str, str]] = None,
    for_balance: bool = False,
) -> dict:
    if group_field:
        _resolve_field(group_field, allowed_fields)
        # An explicit value always means that one value.
        if group_value is not None and str(group_value) != "":
            return {"kind": "field_value", "field": group_field, "value": group_value}

        kind = (field_kinds or {}).get(group_field, "flag")
        if kind == "category":
            # {"kind": "field"} tests bool(value), which on a text column is
            # true for every student. Building a rule that way produces one
            # that looks applied and does nothing -- the worst failure this
            # code can have. "Balance by academic level" means spread each
            # level evenly, which is `field_all_values`.
            if for_balance:
                return {"kind": "field_all_values", "field": group_field}
            raise ToolArgumentError(
                f"'{group_field}' holds one of several values, not yes/no. For a capacity rule say which "
                f"value to cap (group_value), or use a balance rule to spread all of them evenly."
            )
        return {"kind": "field", "field": group_field}
    if group_members:
        ids = [detokenize(t) for t in group_members]
        resolved = [i for i in ids if i is not None]
        if not resolved:
            raise ToolArgumentError("none of the group_members tokens resolved to a known student")
        return {"kind": "members", "members": resolved, "label": group_label_hebrew or ""}
    raise ToolArgumentError("either group_field or group_members must be provided")


def args_to_constraint(
    tool_name: str,
    args: BaseModel,
    detokenize: Callable[[str], Optional[int]],
    allowed_fields: Optional[set[str]] = None,
    field_kinds: Optional[dict[str, str]] = None,
) -> Constraint:
    """Build a (not-yet-applied) Constraint from validated propose_* args.

    Raises ToolArgumentError if a student token doesn't resolve, or if a
    group names a column this dataset doesn't have -- both mean the model
    invented something it wasn't given. `allowed_fields` is every column
    the current workbook offers; None skips the check."""
    if tool_name == "propose_separate":
        a, b = detokenize(args.student_a), detokenize(args.student_b)
        if a is None or b is None:
            raise ToolArgumentError("unknown student token in propose_separate")
        return Constraint(
            type="separate", hard=args.hard, args={"student_a": a, "student_b": b}, label_hebrew=args.rationale_hebrew, source="chat"
        )

    if tool_name == "propose_together":
        a, b = detokenize(args.student_a), detokenize(args.student_b)
        if a is None or b is None:
            raise ToolArgumentError("unknown student token in propose_together")
        return Constraint(
            type="together",
            hard=args.hard,
            args={"student_a": a, "student_b": b, "mode": args.mode},
            label_hebrew=args.rationale_hebrew,
            source="chat",
        )

    if tool_name == "propose_at_least_one_of":
        sid = detokenize(args.student)
        candidates = [c for c in (detokenize(t) for t in args.candidates) if c is not None]
        if sid is None or not candidates:
            raise ToolArgumentError("unknown student token(s) in propose_at_least_one_of")
        return Constraint(
            type="at_least_one_of",
            hard=args.hard,
            args={"student": sid, "candidates": candidates},
            label_hebrew=args.rationale_hebrew,
            source="chat",
        )

    if tool_name == "propose_capacity":
        group = _resolve_group(
            args.group_field, args.group_members, args.group_label_hebrew, detokenize,
            allowed_fields=allowed_fields, group_value=getattr(args, "group_value", None),
            field_kinds=field_kinds, for_balance=False,
        )
        return Constraint(
            type="capacity",
            hard=args.hard,
            args={"group": group, "min": args.min, "max": args.max},
            label_hebrew=args.rationale_hebrew,
            source="chat",
        )

    if tool_name == "propose_balance":
        group = _resolve_group(
            args.group_field, args.group_members, args.group_label_hebrew, detokenize,
            allowed_fields=allowed_fields, group_value=getattr(args, "group_value", None),
            field_kinds=field_kinds, for_balance=True,
        )
        return Constraint(
            type="balance", hard=args.hard, args={"group": group, "weight": args.weight}, label_hebrew=args.rationale_hebrew, source="chat"
        )

    raise ToolArgumentError(f"{tool_name} does not produce a new constraint")
