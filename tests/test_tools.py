import pytest
from pydantic import ValidationError

from backend.llm.tools import (
    TOOL_MODELS,
    ModifyConstraintArgs,
    ProposeAtLeastOneOfArgs,
    ProposeBalanceArgs,
    ProposeCapacityArgs,
    ProposeSeparateArgs,
    ProposeTogetherArgs,
    RemoveConstraintArgs,
    ToolArgumentError,
    args_to_constraint,
    build_tool_definitions,
)


def make_detokenize():
    mapping = {"STUDENT_a": 1, "STUDENT_b": 2, "STUDENT_c": 3}
    return mapping.get


def test_build_tool_definitions_covers_all_tools():
    defs = build_tool_definitions()
    names = {d["function"]["name"] for d in defs}
    assert names == set(TOOL_MODELS.keys())
    for d in defs:
        assert d["type"] == "function"
        assert d["function"]["parameters"]["type"] == "object"


def test_propose_separate_args_to_constraint():
    args = ProposeSeparateArgs(student_a="STUDENT_a", student_b="STUDENT_b", hard=True, rationale_hebrew="לא ביחד")
    c = args_to_constraint("propose_separate", args, make_detokenize())
    assert c.type == "separate"
    assert c.hard is True
    assert c.args == {"student_a": 1, "student_b": 2}
    assert c.source == "chat"


def test_propose_together_args_to_constraint():
    args = ProposeTogetherArgs(student_a="STUDENT_a", student_b="STUDENT_b", mode="mutual", hard=False, rationale_hebrew="ביחד בבקשה")
    c = args_to_constraint("propose_together", args, make_detokenize())
    assert c.type == "together"
    assert c.hard is False
    assert c.args == {"student_a": 1, "student_b": 2, "mode": "mutual"}


def test_propose_at_least_one_of_args_to_constraint():
    args = ProposeAtLeastOneOfArgs(student="STUDENT_a", candidates=["STUDENT_b", "STUDENT_c"], hard=True, rationale_hebrew="לפחות אחת")
    c = args_to_constraint("propose_at_least_one_of", args, make_detokenize())
    assert c.type == "at_least_one_of"
    assert c.args == {"student": 1, "candidates": [2, 3]}


def test_propose_capacity_with_existing_field():
    args = ProposeCapacityArgs(group_field="inclusion", min=1, max=2, hard=True, rationale_hebrew="מכסת שילוב")
    c = args_to_constraint("propose_capacity", args, make_detokenize())
    assert c.type == "capacity"
    assert c.args["group"] == {"kind": "field", "field": "inclusion"}
    assert c.args["min"] == 1 and c.args["max"] == 2


def test_propose_capacity_with_ad_hoc_group():
    args = ProposeCapacityArgs(
        group_members=["STUDENT_a", "STUDENT_b"], group_label_hebrew="קבוצת חברות", max=1, hard=True, rationale_hebrew="לפזר"
    )
    c = args_to_constraint("propose_capacity", args, make_detokenize())
    assert c.args["group"] == {"kind": "members", "members": [1, 2], "label": "קבוצת חברות"}


def test_propose_capacity_without_group_raises():
    args = ProposeCapacityArgs(hard=True, rationale_hebrew="חסר קבוצה")
    with pytest.raises(ToolArgumentError):
        args_to_constraint("propose_capacity", args, make_detokenize())


def test_propose_balance_args_to_constraint():
    args = ProposeBalanceArgs(group_field="ethiopian_origin", weight=2.0, rationale_hebrew="לפזר שווה")
    c = args_to_constraint("propose_balance", args, make_detokenize())
    assert c.type == "balance"
    assert c.hard is False
    assert c.args == {"group": {"kind": "field", "field": "ethiopian_origin"}, "weight": 2.0}


def test_unknown_student_token_raises():
    args = ProposeSeparateArgs(student_a="STUDENT_a", student_b="STUDENT_ghost", hard=True, rationale_hebrew="test")
    with pytest.raises(ToolArgumentError):
        args_to_constraint("propose_separate", args, make_detokenize())


def test_modify_and_remove_args_validate():
    m = ModifyConstraintArgs(constraint_id="abc123", hard=False, rationale_hebrew="הפוך לרך")
    assert m.constraint_id == "abc123"
    r = RemoveConstraintArgs(constraint_id="abc123", rationale_hebrew="להסיר")
    assert r.constraint_id == "abc123"


def test_missing_required_field_raises_validation_error():
    with pytest.raises(ValidationError):
        ProposeSeparateArgs(student_a="STUDENT_a", student_b="STUDENT_b", hard=True)
