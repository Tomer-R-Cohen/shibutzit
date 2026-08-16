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

_CATEGORY_FIELDS = Literal["differential", "ethiopian_origin", "inclusion", "hamar"]


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
    group_field: Optional[_CATEGORY_FIELDS] = Field(
        default=None, description="An existing data category to constrain. Omit and use group_members for an ad hoc group not in the data."
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
    group_field: Optional[_CATEGORY_FIELDS] = Field(default=None, description="An existing data category to spread evenly across classes")
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


def _resolve_group(
    group_field: Optional[str],
    group_members: Optional[list[str]],
    group_label_hebrew: Optional[str],
    detokenize: Callable[[str], Optional[int]],
) -> dict:
    if group_field:
        return {"kind": "field", "field": group_field}
    if group_members:
        ids = [detokenize(t) for t in group_members]
        resolved = [i for i in ids if i is not None]
        if not resolved:
            raise ToolArgumentError("none of the group_members tokens resolved to a known student")
        return {"kind": "members", "members": resolved, "label": group_label_hebrew or ""}
    raise ToolArgumentError("either group_field or group_members must be provided")


def args_to_constraint(tool_name: str, args: BaseModel, detokenize: Callable[[str], Optional[int]]) -> Constraint:
    """Build a (not-yet-applied) Constraint from validated propose_* args.
    Raises ToolArgumentError if a student token doesn't resolve -- should
    only happen if the model hallucinated a token it wasn't given."""
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
        group = _resolve_group(args.group_field, args.group_members, args.group_label_hebrew, detokenize)
        return Constraint(
            type="capacity",
            hard=args.hard,
            args={"group": group, "min": args.min, "max": args.max},
            label_hebrew=args.rationale_hebrew,
            source="chat",
        )

    if tool_name == "propose_balance":
        group = _resolve_group(args.group_field, args.group_members, args.group_label_hebrew, detokenize)
        return Constraint(
            type="balance", hard=args.hard, args={"group": group, "weight": args.weight}, label_hebrew=args.rationale_hebrew, source="chat"
        )

    raise ToolArgumentError(f"{tool_name} does not produce a new constraint")
