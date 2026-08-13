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

from ..llm.provider import LLMNotConfiguredError, chat_completion
from ..llm.prompts import build_constraints_context, build_roster_context, build_system_prompt
from ..llm.tools import TOOL_MODELS, ToolArgumentError, args_to_constraint, build_tool_definitions
from ..session_store import PendingProposal, Session, store
from ..solver_inputs import build_solver_inputs
from ..utils import require

router = APIRouter()


class ChatMessageRequest(BaseModel):
    message: str


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

    constraint = args_to_constraint(tool_name, args, sess.token_map.id_for)
    proposal = PendingProposal(kind="propose", summary_hebrew=args.rationale_hebrew, constraint=asdict(constraint))
    summary = f"הבנתי: {args.rationale_hebrew} - זו דרישה {'קשה' if constraint.hard else 'רכה'}. לאשר?"
    return proposal, summary


@router.post("/api/chat/message")
async def send_chat_message(req: ChatMessageRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    df = require(sess.mapped_df, "יש להשלים שלבים קודמים תחילה.")
    sess.token_map.ensure_all(df[FIELD_STUDENT_ID].tolist())

    mentions = resolve_mentions_in_text(req.message, df)
    ambiguous = [m for m in mentions if m.status == "ambiguous"]
    unmatched = [m for m in mentions if m.status == "unmatched"]
    if ambiguous or unmatched:
        clarification = _clarification_message(ambiguous, unmatched)
        sess.chat_history.append({"role": "user", "content": req.message})
        sess.chat_history.append({"role": "assistant", "content": clarification})
        store.save(sess)
        return {"reply": clarification, "pending_proposal": None}

    redacted = redact_text(req.message, mentions, sess.token_map.token_for)
    sess.chat_history.append({"role": "user", "content": redacted})

    _, constraints = build_solver_inputs(sess)
    system_prompt = build_system_prompt(
        build_roster_context(df, sess.token_map),
        build_constraints_context(constraints),
    )

    try:
        completion = chat_completion(system_prompt=system_prompt, messages=sess.chat_history, tools=build_tool_definitions())
    except LLMNotConfiguredError as e:
        # Don't persist the user turn without a matching reply -- leave the
        # history as it was before this call and surface a clear error.
        sess.chat_history.pop()
        raise HTTPException(status_code=503, detail=str(e))

    if completion.tool_calls:
        # v1 scope: one proposal per turn. If the model returns more than
        # one tool call, only the first becomes a pending proposal; the
        # rest are dropped rather than silently applying multiple changes
        # from a single unreviewed turn.
        tool_call = completion.tool_calls[0]
        try:
            proposal, summary = _build_proposal(tool_call.name, tool_call.arguments, sess)
        except (ValidationError, ToolArgumentError) as e:
            reply = f"לא הצלחתי לפרש את הבקשה כראוי ({e}). אפשר לנסח אחרת?"
            sess.chat_history.append({"role": "assistant", "content": reply})
            store.save(sess)
            return {"reply": reply, "pending_proposal": None}

        sess.pending_proposal = proposal
        sess.chat_history.append({"role": "assistant", "content": summary})
        store.save(sess)
        return {"reply": summary, "pending_proposal": asdict(proposal)}

    reply = completion.text or ""
    sess.chat_history.append({"role": "assistant", "content": reply})
    store.save(sess)
    return {"reply": reply, "pending_proposal": None}


@router.post("/api/chat/confirm")
async def confirm_pending_proposal(x_session_id: str = Header(...)):
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

    sess.pending_proposal = None
    sess.chat_history.append({"role": "assistant", "content": "אושר ועודכן ברשימת הכללים."})
    store.save(sess)
    return {"applied": True, "result": result}


@router.post("/api/chat/reject")
async def reject_pending_proposal(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    if sess.pending_proposal is None:
        raise HTTPException(status_code=409, detail="אין הצעה ממתינה.")
    sess.pending_proposal = None
    sess.chat_history.append({"role": "assistant", "content": "בסדר, ההצעה בוטלה."})
    store.save(sess)
    return {"rejected": True}


@router.get("/api/chat/history")
async def get_chat_history(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return {
        "messages": sess.chat_history,
        "pending_proposal": asdict(sess.pending_proposal) if sess.pending_proposal else None,
    }


@router.get("/api/constraints")
async def list_constraints(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return {"constraints": [asdict(c) for c in sess.constraints]}


class ConstraintPatchRequest(BaseModel):
    hard: Optional[bool] = None
    active: Optional[bool] = None


@router.patch("/api/constraints/{constraint_id}")
async def patch_constraint(constraint_id: str, req: ConstraintPatchRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    target = next((c for c in sess.constraints if c.id == constraint_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="כלל לא נמצא.")
    if req.hard is not None:
        target.hard = req.hard
    if req.active is not None:
        target.active = req.active
    store.save(sess)
    return asdict(target)


@router.delete("/api/constraints/{constraint_id}")
async def delete_constraint(constraint_id: str, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    before = len(sess.constraints)
    sess.constraints = [c for c in sess.constraints if c.id != constraint_id]
    store.save(sess)
    return {"removed": before - len(sess.constraints) > 0}
