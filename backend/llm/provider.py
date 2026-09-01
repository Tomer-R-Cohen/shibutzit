"""Thin OpenAI-compatible tool-calling client.

The model/provider is swappable via env vars so the same tool schemas
(backend/llm/tools.py) work against Kimi (Moonshot's OpenAI-compatible API,
or via OpenRouter), or any other provider that speaks the same
chat-completions + tool-calling shape. No provider-specific features (e.g.
Anthropic-style prompt caching) are used here by design -- this stays a
thin, swappable seam until a provider is actually chosen; see the plan's
Phase 2 notes.

Env vars:
    LLM_API_KEY   -- required to actually call out; chat_completion() raises
                     LLMNotConfiguredError if missing, rather than failing
                     deep inside a request.
    LLM_BASE_URL  -- OpenAI-compatible base URL (default: Moonshot's).
    LLM_MODEL     -- model id (default: "kimi-k2.6").
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"
DEFAULT_MODEL = "kimi-k2.6"


class LLMNotConfiguredError(Exception):
    """Raised when a chat call is attempted without LLM_API_KEY set."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatCompletion:
    text: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The assistant turn exactly as the provider returned it, in wire shape.
    # The agent loop has to append this verbatim before it can append the
    # matching tool results -- an OpenAI-style conversation rejects a `tool`
    # message that isn't preceded by the `assistant` message whose
    # tool_call_ids it answers.
    raw_message: dict = field(default_factory=dict)


def _client() -> OpenAI:
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise LLMNotConfiguredError(
            "LLM_API_KEY is not set. Set it (and optionally LLM_BASE_URL / "
            "LLM_MODEL) to enable the chat/constraint-proposal feature."
        )
    base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
    return OpenAI(api_key=api_key, base_url=base_url)


def chat_completion(system_prompt: str, messages: list[dict], tools: list[dict]) -> ChatCompletion:
    """One non-streaming tool-calling turn.

    `messages` is the OpenAI-style [{"role": ..., "content": ...}, ...]
    history (not including the system prompt -- that's passed separately
    since it's rebuilt fresh each call from current session state, not
    accumulated). Returns either plain text or one or more tool calls.
    """
    client = _client()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            tools=tools,
            tool_choice="auto",
        )
    except Exception:
        logger.exception("LLM chat_completion call failed (model=%s)", model)
        raise
    msg = response.choices[0].message

    tool_calls = []
    raw_tool_calls = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        raw_tool_calls.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
        )

    raw_message: dict = {"role": "assistant", "content": msg.content}
    if raw_tool_calls:
        raw_message["tool_calls"] = raw_tool_calls

    return ChatCompletion(text=msg.content, tool_calls=tool_calls, raw_message=raw_message)


def chat_completion_stream(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    on_text_delta,
) -> ChatCompletion:
    """Streaming equivalent of ``chat_completion`` with identical output.

    Text fragments are forwarded as they arrive, while fragmented tool-call
    arguments are accumulated and validated only after the provider closes
    the stream. The agent therefore keeps exactly the same safety boundary:
    streaming changes presentation, never when a write tool is executed.
    """
    client = _client()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    text_parts: list[str] = []
    tool_parts: dict[int, dict] = {}
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            tools=tools,
            tool_choice="auto",
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text_parts.append(delta.content)
                on_text_delta(delta.content)
            for tc in delta.tool_calls or []:
                part = tool_parts.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    part["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        part["name"] += tc.function.name
                    if tc.function.arguments:
                        part["arguments"] += tc.function.arguments
    except Exception:
        logger.exception("LLM streaming chat completion failed (model=%s)", model)
        raise

    calls: list[ToolCall] = []
    raw_calls: list[dict] = []
    for index in sorted(tool_parts):
        part = tool_parts[index]
        raw_args = part["arguments"] or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {}
        call_id = part["id"] or f"stream_call_{index}"
        calls.append(ToolCall(id=call_id, name=part["name"], arguments=args))
        raw_calls.append(
            {"id": call_id, "type": "function", "function": {"name": part["name"], "arguments": raw_args}}
        )
    text = "".join(text_parts) or None
    raw_message: dict = {"role": "assistant", "content": text}
    if raw_calls:
        raw_message["tool_calls"] = raw_calls
    return ChatCompletion(text=text, tool_calls=calls, raw_message=raw_message)


def text_completion(system_prompt: str, user_message: str) -> str:
    """One plain (no-tools) completion turn -- used for one-off narration
    tasks (e.g. explaining an infeasibility already proven deterministically
    by the solver) that don't need the constraint-proposal tool surface."""
    client = _client()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content or ""
