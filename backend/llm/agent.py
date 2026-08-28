"""The agent loop: look things up, then answer or propose.

What this replaces was a single `chat_completion()` call whose result was
either plain text or one write tool call. With no way to feed a tool result
back, the model could only ever answer from whatever happened to be in the
system prompt -- so "why does class 3 have two more students" got a
confident-sounding guess, because the class sizes were never in context.

The loop here is the fix, and it is deliberately asymmetric about the three
kinds of tool:

  read     -- executes immediately, result appended, loop continues. The
              model can chain: sizes -> active rules -> composition of the
              odd class, and only then answer.
  simulate -- also executes immediately, but runs the real solver on a
              deep copy and throws it away, so the model can find out what a
              change would do instead of predicting it. Metered per turn
              (MAX_SIMULATIONS_PER_TURN) because each one costs the
              counselor real seconds, not just tokens.
  write    -- never executes. The first one ends the turn and becomes a
              PendingProposal for the counselor to confirm or reject,
              exactly as before. Nothing reaches `sess.constraints` without
              a human yes.

The natural shape that falls out is investigate -> try -> propose: read the
sizes, simulate the tighter rule, then offer the change as a card the
counselor confirms. The agent does the work; the counselor still decides.

Intermediate tool traffic is kept in a per-turn working list and thrown away
at the end. `sess.chat_history` stays what it has always been -- the
user-visible transcript of user/assistant text -- because it is persisted
and replayed to the frontend by /api/chat/history, which knows nothing about
tool messages. The cost of that choice is that the model re-reads what it
needs on each turn instead of remembering it; the read tools are local and
cheap, so that is the right trade for now.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .provider import ToolCall, chat_completion
from .planning_tools import (
    MUTATING_PLANNING_TOOLS,
    build_planning_tool_definitions,
    execute_planning_tool,
    is_planning_tool,
)
from .read_tools import build_read_tool_definitions, execute_read_tool, is_read_tool
from .simulation_tools import build_simulation_tool_definitions, execute_simulation_tool, is_simulation_tool
from .tools import build_tool_definitions

logger = logging.getLogger(__name__)

# How many provider round-trips one counselor message may cost. Each step is
# one billed call, so this caps what a model that decides to look up
# everything twice can spend. Six is enough for the deepest useful chain
# (summary -> sizes -> rules -> composition -> violations -> answer).
MAX_STEPS = 6

# Simulations run the real CP-SAT solver, so they cost wall-clock time the
# counselor spends staring at a spinner -- not just tokens. Two per turn
# keeps the worst case near 20s of solving, which is a believable pause;
# six would be a minute and would feel broken. Past the budget the tool
# returns a refusal the model can read and work around, rather than
# silently doing something cheaper.
MAX_SIMULATIONS_PER_TURN = 2


@dataclass
class AgentTurn:
    """Outcome of one counselor message."""

    text: Optional[str] = None
    write_call: Optional[ToolCall] = None
    # Read tools actually executed, in order, for the activity line the UI
    # shows. An agent that works invisibly just looks slow.
    steps: list[dict] = field(default_factory=list)
    hit_step_limit: bool = False
    # A planning tool changed persisted session state (a checklist entry,
    # the class count), so the caller must save and tell the UI to refresh.
    state_changed: bool = False


def build_agent_tools() -> list[dict]:
    """Read tools first, then what-ifs, then writes: with a small model the
    ordering in the tool array is a weak but free prior, and the failure we
    are fixing is the model reaching for a write when it should have looked
    something up or tried it first."""
    return (
        build_read_tool_definitions()
        + build_planning_tool_definitions()
        + build_simulation_tool_definitions()
        + build_tool_definitions()
    )


def _execute(name: str, args: dict, sess, budget: dict) -> dict:
    """Run one non-write tool. Cheap reads are unmetered; simulations spend
    from the per-turn budget because each one is a real solve."""
    if is_planning_tool(name):
        payload = execute_planning_tool(name, args, sess)
        if name in MUTATING_PLANNING_TOOLS and "error" not in payload:
            budget["dirty"] = True
        return payload
    if is_simulation_tool(name):
        if budget["simulations"] <= 0:
            return {
                "error": "simulation_budget_exhausted",
                "detail": (
                    f"Already ran {MAX_SIMULATIONS_PER_TURN} trial solves for this question, which is the limit. "
                    "Answer from the results you have, and suggest the counselor try further variations in a "
                    "follow-up question."
                ),
            }
        budget["simulations"] -= 1
        return execute_simulation_tool(name, args, sess)
    return execute_read_tool(name, args, sess)


def _tool_result_message(call: ToolCall, payload: dict) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }


def run_agent_turn(sess, system_prompt: str, history: list[dict], validate_write=None) -> AgentTurn:
    """Drive one counselor message to either an answer or a proposal.

    `history` is the persisted user/assistant transcript; it is copied, not
    mutated. The caller owns what ends up in `sess.chat_history`.

    `validate_write(call)` may raise to reject a write tool call. A rejected
    call is fed back to the model as a tool result and the loop continues,
    so it can correct itself -- the same recovery the read tools already
    get. Previously a rejection ended the turn and the raw exception text
    (in English, aimed at the model) was shown to the counselor.
    """
    messages = list(history)
    turn = AgentTurn()
    tools = build_agent_tools()
    budget = {"simulations": MAX_SIMULATIONS_PER_TURN, "dirty": False}

    for step in range(MAX_STEPS):
        completion = chat_completion(system_prompt=system_prompt, messages=messages, tools=tools)

        if not completion.tool_calls:
            turn.text = completion.text or ""
            turn.state_changed = budget["dirty"]
            return turn

        # A write call ends the turn even if the model batched reads
        # alongside it: the counselor is about to be shown a confirm card,
        # and it must describe a decision made from what the model had
        # already read, not from lookups it never got to see the results of.
        write_call = next(
            (
                tc
                for tc in completion.tool_calls
                if not is_read_tool(tc.name) and not is_simulation_tool(tc.name) and not is_planning_tool(tc.name)
            ),
            None,
        )
        if write_call is not None:
            error = None
            if validate_write is not None:
                try:
                    validate_write(write_call)
                except Exception as e:
                    error = str(e)
            if error is None:
                turn.write_call = write_call
                turn.text = completion.text or None
                turn.state_changed = budget["dirty"]
                return turn
            # Hand the reason back and let it try again rather than ending the
            # turn on a message written for the model, not the counselor.
            logger.info("agent write rejected tool=%s -> %s", write_call.name, error)
            turn.steps.append({"tool": write_call.name, "args": write_call.arguments, "ok": False})
            messages.append(completion.raw_message)
            for call in completion.tool_calls:
                payload = (
                    {"error": "invalid_rule", "detail": error, "hint": "Fix the arguments and call the tool again."}
                    if call is write_call
                    else _execute(call.name, call.arguments, sess, budget)
                )
                messages.append(_tool_result_message(call, payload))
            continue

        messages.append(completion.raw_message)
        for call in completion.tool_calls:
            payload = _execute(call.name, call.arguments, sess, budget)
            logger.info(
                "agent step=%d tool=%s args=%s -> %s",
                step, call.name, call.arguments, "error" if "error" in payload else "ok",
            )
            turn.steps.append({"tool": call.name, "args": call.arguments, "ok": "error" not in payload})
            messages.append(_tool_result_message(call, payload))

    # Out of steps with the model still calling tools. Ask it once more with
    # no tools available, so the counselor gets a real answer built from
    # everything already gathered rather than a spinner that gave up.
    turn.hit_step_limit = True
    turn.state_changed = budget["dirty"]
    try:
        final = chat_completion(system_prompt=system_prompt, messages=messages, tools=[])
        turn.text = final.text or ""
    except Exception:
        logger.exception("agent forced-answer call failed")
        turn.text = "לא הצלחתי להשלים את הבדיקה. אפשר לנסות לשאול שוב, אולי ממוקד יותר?"
    return turn
