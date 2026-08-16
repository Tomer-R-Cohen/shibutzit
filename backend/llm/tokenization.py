"""Per-session, opaque student-id <-> chat-token mapping.

Real student ids must never reach the LLM -- `src/chat/mentions.py`
resolves raw names in chat text to real ids locally, and this module is
the next step: mapping those real ids to opaque, session-scoped tokens
(e.g. STUDENT_a1b2c3) before anything is sent out, and mapping tool-call
responses back. Tokens are randomly generated per session, not derived
from the id itself (a token like "STUDENT_42" would trivially reverse to
row 42 of the roster) -- the mapping lives only in the session, never sent
anywhere.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenMap:
    id_to_token: dict = field(default_factory=dict)
    token_to_id: dict = field(default_factory=dict)

    def token_for(self, student_id) -> str:
        token = self.id_to_token.get(student_id)
        if token is None:
            token = f"STUDENT_{uuid.uuid4().hex[:6]}"
            self.id_to_token[student_id] = token
            self.token_to_id[token] = student_id
        return token

    def id_for(self, token: str) -> Optional[int]:
        return self.token_to_id.get(token)

    def ensure_all(self, student_ids) -> None:
        for sid in student_ids:
            self.token_for(sid)
