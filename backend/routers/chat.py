"""Conversational constraint agent: chat -> proposed Constraint -> explicit
counselor confirmation -> src.constraints.Constraint list.

The LLM never applies anything directly. Every turn either:
  - short-circuits locally (no LLM call) when the message contains an
    ambiguous or unmatched student-name mention, asking the counselor to
    disambiguate;
  - or redacts resolved names to opaque tokens, calls the LLM, and turns
    its (at most one, per turn) tool call into a `PendingProposal` that
    sits on the session until /api/chat/confirm or /api/chat/reject is
    called -- nothing touches `sess.constraints` before that.

A direct, chat-free CRUD surface (/api/constraints, PATCH/DELETE by id) is
also exposed here since it operates on the same list; the frontend rules
UI (Phase 4) will use it directly, not just through chat.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ValidationError

from src.chat.mentions import Mention, redact_text, resolve_mentions_in_text
from src.column_mapping import FIELD_STUDENT_ID
from src.constraints import Constraint

from ..llm.agent import run_agent_turn
from ..llm.provider import LLMNotConfiguredError
from ..llm.prompts import (
    build_constraints_context,
    build_dataset_columns_context,
    build_planning_context,
    build_result_context,
    build_roster_context,
    build_system_prompt,
)
from ..llm.read_tools import groupable_field_kinds, groupable_fields
from ..llm.tools import TOOL_MODELS, ToolArgumentError, args_to_constraint
from ..session_store import PendingProposal, Session, store
from ..solver_inputs import build_solver_inputs
from ..utils import require

router = APIRouter()


class ChatMessageRequest(BaseModel):
    message: str


def _suggested_actions(sess: Session, steps: list[dict]) -> list[dict]:
    """Small, structured next moves for the UI.

    Suggestions are application data, not Markdown scraped from model prose.
    They are deliberately deterministic and reflect the state after the
    turn; the model remains responsible only for the answer itself.
    """
    if sess.pending_proposal is not None:
        return []
    if sess.mapped_df is None:
        return [
            {"label": "מה כדאי להכין בקובץ?", "message": "אילו נתונים כדאי להכין בקובץ לפני שמתחילים?"},
            {"label": "הצג את רשימת הדרישות", "message": "הצג את רשימת העמודות שסיכמנו להכין."},
        ]
    result_state = sess.result_state()
    if result_state["has_result"]:
        if result_state["is_stale"]:
            return [
                {"label": "מה השתנה מאז ההרצה?", "message": "אילו כללים השתנו מאז השיבוץ האחרון?"},
                {"label": "בדיקת הכללים הפעילים", "message": "הצג את הכללים הפעילים והערכים שלהם."},
            ]
        tools = {s.get("tool") for s in steps if s.get("ok")}
        if "get_class_sizes" in tools:
            return [
                {"label": "בדיקת הרכב הכיתות", "message": "בדוק את הרכב הכיתות והצבע על פערים משמעותיים."},
                {"label": "בדיקת בקשות חברות", "message": "בדוק את המענה לבקשות החברות בשיבוץ."},
            ]
        return [
            {"label": "בדיקת בקשות חברות", "message": "בדוק את המענה לבקשות החברות בשיבוץ."},
            {"label": "איתור פערים", "message": "אילו פערים משמעותיים כדאי לבדוק בשיבוץ?"},
        ]
    return [
        {"label": "הצג כללים פעילים", "message": "הצג את הכללים הפעילים והערכים שלהם."},
        {"label": "בדוק מוכנות להרצה", "message": "בדוק אם הנתונים והכללים מוכנים להרצת שיבוץ."},
    ]


def _clarification_message(ambiguous: list[Mention], unmatched: list[Mention]) -> str:
    lines = []
    for m in ambiguous:
        options = ", ".join(f"#{sid}" for sid in m.candidate_ids)
        lines.append(f"השם '{m.raw_text}' מתאים ליותר מתלמידה אחת ({options}) - אפשר לציין מספר מזהה (למשל #12)?")
    for m in unmatched:
        lines.append(f"לא מצאתי תלמידה עם המזהה '{m.raw_text}'.")
    return " ".join(lines)


def _build_proposal(tool_name: str, raw_args: dict, sess: Session) -> tuple[PendingProposal, str]:
    model_cls = TOOL_MODELS.get(tool_name)
    if model_cls is None:
        raise ToolArgumentError(f"unknown tool: {tool_name}")
    args = model_cls(**raw_args)

    if tool_name == "modify_constraint":
        target = next((c for c in sess.constraints if c.id == args.constraint_id), None)
        if target is None:
            raise ToolArgumentError(f"constraint {args.constraint_id} not found")
        changes = {}
        if args.hard is not None:
            changes["hard"] = args.hard
        if args.active is not None:
            changes["active"] = args.active
        proposal = PendingProposal(
            kind="modify", summary_hebrew=args.rationale_hebrew, target_constraint_id=args.constraint_id, changes=changes
        )
        summary = f"הבנתי: {args.rationale_hebrew} (כלל: {target.label_hebrew}) - לאשר?"
        return proposal, summary

    if tool_name == "remove_constraint":
        target = next((c for c in sess.constraints if c.id == args.constraint_id), None)
        if target is None:
            raise ToolArgumentError(f"constraint {args.constraint_id} not found")
        proposal = PendingProposal(kind="remove", summary_hebrew=args.rationale_hebrew, target_constraint_id=args.constraint_id)
        summary = f"הבנתי: להסיר את הכלל '{target.label_hebrew}' - לאשר?"
        return proposal, summary

    # A group may now name any column this particular workbook contains, so
    # the set of legal fields comes from the dataset rather than from a
    # hardcoded enum -- and an invented one is rejected here rather than
    # becoming a rule that silently matches nobody.
    constraint = args_to_constraint(
        tool_name,
        args,
        sess.token_map.id_for,
        allowed_fields=groupable_fields(sess),
        field_kinds=groupable_field_kinds(sess),
    )
    proposal = PendingProposal(kind="propose", summary_hebrew=args.rationale_hebrew, constraint=asdict(constraint))
    summary = f"הבנתי: {args.rationale_hebrew} - זו דרישה {'קשה' if constraint.hard else 'רכה'}. לאשר?"
    return proposal, summary


@router.post("/api/chat/message")
def send_chat_message(req: ChatMessageRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = sess.mapped_df

    if df is not None:
        sess.token_map.ensure_all(df[FIELD_STUDENT_ID].tolist())
        mentions = resolve_mentions_in_text(req.message, df)
        ambiguous = [m for m in mentions if m.status == "ambiguous"]
        unmatched = [m for m in mentions if m.status == "unmatched"]
        if ambiguous or unmatched:
            clarification = _clarification_message(ambiguous, unmatched)
            sess.chat_history.append({"role": "user", "content": req.message})
            sess.chat_history.append({"role": "assistant", "content": clarification})
            store.save(sess)
            return {"reply": clarification, "pending_proposal": None, "suggestions": []}
        redacted = redact_text(req.message, mentions, sess.token_map.token_for)
    else:
        # Planning mode: no roster, so there is no name-to-token map to
        # redact against and nothing to resolve a mention to. The message
        # goes out as typed. The prompt tells the model not to solicit
        # names at this stage precisely because they could not be protected
        # here the way they are once a roster exists.
        redacted = req.message

    sess.chat_history.append({"role": "user", "content": redacted})

    cfg, constraints = build_solver_inputs(sess)
    has_result = sess.opt_result is not None and sess.opt_result.is_feasible and sess.adjustment_state is not None
    class_sizes = None
    if has_result:
        sizes = [0] * cfg.num_classes
        for cls in sess.adjustment_state.assignment.values():
            if 0 <= cls < cfg.num_classes:
                sizes[cls] += 1
        class_sizes = sizes

    system_prompt = build_system_prompt(
        build_roster_context(df),
        build_constraints_context(constraints),
        build_result_context(has_result, cfg.num_classes, class_sizes, stale=sess.result_state()["is_stale"]),
        build_dataset_columns_context(sess.dataset_schema),
        build_planning_context(df is None, cfg.num_classes, sess.data_requirements),
    )

    try:
        turn = run_agent_turn(
            sess,
            system_prompt,
            sess.chat_history,
            validate_write=lambda call: _build_proposal(call.name, call.arguments, sess),
        )
    except LLMNotConfiguredError as e:
        # Don't persist the user turn without a matching reply -- leave the
        # history as it was before this call and surface a clear error.
        sess.chat_history.pop()
        raise HTTPException(status_code=503, detail=str(e))

    # What the agent looked at, so the counselor can see it worked rather
    # than just waited. Read tools only -- writes are shown as the proposal.
    steps = [{"tool": s["tool"], "ok": s["ok"]} for s in turn.steps]
    # A planning tool changed persisted state (checklist entry, class
    # count). The UI uses this to re-read the panels rather than poll --
    # "the rules list updates live" is this flag plus a refresh key.
    state_changed = turn.state_changed

    if turn.write_call is not None:
        try:
            proposal, summary = _build_proposal(turn.write_call.name, turn.write_call.arguments, sess)
        except (ValidationError, ToolArgumentError) as e:
            reply = f"לא הצלחתי לפרש את הבקשה כראוי ({e}). אפשר לנסח אחרת?"
            sess.chat_history.append({"role": "assistant", "content": reply})
            store.save(sess)
            return {"reply": reply, "pending_proposal": None, "steps": steps, "state_changed": state_changed, "suggestions": []}

        sess.pending_proposal = proposal
        sess.chat_history.append({"role": "assistant", "content": summary})
        store.save(sess)
        return {"reply": summary, "pending_proposal": asdict(proposal), "steps": steps, "state_changed": state_changed, "suggestions": []}

    reply = turn.text or ""
    sess.chat_history.append({"role": "assistant", "content": reply})
    store.save(sess)
    return {
        "reply": reply,
        "pending_proposal": None,
        "steps": steps,
        "state_changed": state_changed,
        "suggestions": _suggested_actions(sess, steps),
        "result_state": sess.result_state(),
    }


@router.post("/api/chat/confirm")
def confirm_pending_proposal(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    proposal = sess.pending_proposal
    if proposal is None:
        raise HTTPException(status_code=409, detail="אין הצעה ממתינה לאישור.")

    if proposal.kind == "propose":
        constraint = Constraint(**proposal.constraint)
        sess.constraints.append(constraint)
        result = asdict(constraint)
    elif proposal.kind == "modify":
        target = next((c for c in sess.constraints if c.id == proposal.target_constraint_id), None)
        if target is None:
            sess.pending_proposal = None
            store.save(sess)
            raise HTTPException(status_code=409, detail="הכלל כבר לא קיים.")
        for k, v in (proposal.changes or {}).items():
            setattr(target, k, v)
        result = asdict(target)
    elif proposal.kind == "remove":
        sess.constraints = [c for c in sess.constraints if c.id != proposal.target_constraint_id]
        result = {"removed": proposal.target_constraint_id}
    else:
        raise HTTPException(status_code=500, detail="סוג הצעה לא מוכר.")

    sess.mark_inputs_changed()
    sess.pending_proposal = None
    sess.chat_history.append({"role": "assistant", "content": "אושר ועודכן ברשימת הכללים."})
    store.save(sess)
    return {"applied": True, "result": result, "result_state": sess.result_state()}


@router.post("/api/chat/reject")
def reject_pending_proposal(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    if sess.pending_proposal is None:
        raise HTTPException(status_code=409, detail="אין הצעה ממתינה.")
    sess.pending_proposal = None
    sess.chat_history.append({"role": "assistant", "content": "בסדר, ההצעה בוטלה."})
    store.save(sess)
    return {"rejected": True}


@router.get("/api/chat/history")
def get_chat_history(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return {
        "messages": sess.chat_history,
        "pending_proposal": asdict(sess.pending_proposal) if sess.pending_proposal else None,
    }


@router.get("/api/constraints")
def list_constraints(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return {"constraints": [asdict(c) for c in sess.constraints], "result_state": sess.result_state()}


class ConstraintPatchRequest(BaseModel):
    hard: Optional[bool] = None
    active: Optional[bool] = None


@router.patch("/api/constraints/{constraint_id}")
def patch_constraint(constraint_id: str, req: ConstraintPatchRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    target = next((c for c in sess.constraints if c.id == constraint_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="כלל לא נמצא.")
    if req.hard is not None:
        target.hard = req.hard
    if req.active is not None:
        target.active = req.active
    sess.mark_inputs_changed()
    store.save(sess)
    return {**asdict(target), "result_state": sess.result_state()}


@router.delete("/api/constraints/{constraint_id}")
def delete_constraint(constraint_id: str, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    before = len(sess.constraints)
    sess.constraints = [c for c in sess.constraints if c.id != constraint_id]
    if len(sess.constraints) != before:
        sess.mark_inputs_changed()
    store.save(sess)
    return {"removed": before - len(sess.constraints) > 0, "result_state": sess.result_state()}
