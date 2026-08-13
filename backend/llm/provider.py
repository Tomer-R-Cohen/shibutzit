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
import os
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

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

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system_prompt}, *messages],
        tools=tools,
        tool_choice="auto",
    )
    msg = response.choices[0].message

    tool_calls = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    return ChatCompletion(text=msg.content, tool_calls=tool_calls)


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
