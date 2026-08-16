"""Local (non-LLM) resolution of student name mentions inside free-form
chat text.

`src.friendship_graph.resolve_requests` matches names from a structured,
delimiter-separated "requested names" cell -- this module solves a
different problem: finding and resolving name mentions anywhere inside an
arbitrary Hebrew sentence a counselor types in chat, so a raw name never
has to reach an LLM unresolved (a later chat/LLM layer tokenizes text using
this module's output before sending anything out).

Matching is exact-normalized-substring, reusing the same
`normalize_name`/`build_name_index` used everywhere else in the app for
full-name matching -- no fuzzy/typo tolerance, same tradeoff as the
friendship-request matcher: ambiguous or unmatched mentions are reported,
never guessed. One Hebrew-specific heuristic is applied: a single-letter
prefix conjunction/preposition (ו/ה/ב/ל/כ/ש/מ) directly attached to the
first word of a name (e.g. "ומיכל", "and Michal") is stripped before
matching, since that's overwhelmingly the most common way a name appears
mid-sentence in Hebrew. Multi-letter or non-leading prefixes are not
handled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

import pandas as pd

from src.column_mapping import FIELD_STUDENT_ID
from src.friendship_graph import build_name_index, normalize_name

MentionStatus = Literal["matched", "ambiguous", "unmatched"]

_MAX_WINDOW_TOKENS = 4
_PREFIX_LETTERS = "ובלכשמה"
_TOKEN_RE = re.compile(r"\S+")
_EDGE_PUNCT_RE = re.compile(r'^[.,!?;:"\'׳״()\[\]]+|[.,!?;:"\'׳״()\[\]]+$')
_ID_REF_RE = re.compile(r"^#(\d+)$")


@dataclass
class Mention:
    raw_text: str
    start: int
    end: int
    status: MentionStatus
    student_id: Optional[int] = None
    candidate_ids: list = field(default_factory=list)


def _tokenize(text: str) -> list[tuple[str, int, int]]:
    """Whitespace-split tokens with character offsets into `text`, trimming
    leading/trailing punctuation (but not interior characters, since Hebrew
    abbreviations like ח"מ carry a meaningful interior gershayim)."""
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        raw = m.group(0)
        trimmed = _EDGE_PUNCT_RE.sub("", raw)
        if not trimmed:
            continue
        offset = raw.find(trimmed)
        start = m.start() + offset
        tokens.append((trimmed, start, start + len(trimmed)))
    return tokens


def _strip_prefix(token: str) -> Optional[str]:
    """Strip a single attached Hebrew conjunction/preposition letter, if
    present (e.g. 'ומיכל' -> 'מיכל'). Returns None if not applicable."""
    if len(token) >= 2 and token[0] in _PREFIX_LETTERS:
        return token[1:]
    return None


def _longest_match_at(tokens: list[tuple[str, int, int]], i: int, name_index: dict):
    """Try windows starting at token index i, longest first (and, for the
    first token only, with a Hebrew prefix letter stripped). Returns
    (num_tokens_consumed, char_start, char_end, candidate_ids) or None."""
    max_len = min(_MAX_WINDOW_TOKENS, len(tokens) - i)
    first_word, first_start, _ = tokens[i]
    stripped_first = _strip_prefix(first_word)

    for length in range(max_len, 0, -1):
        window = tokens[i : i + length]
        window_end = window[-1][2]

        candidate = " ".join(w for w, _, _ in window)
        key = normalize_name(candidate)
        if key in name_index:
            return length, first_start, window_end, name_index[key]

        if stripped_first is not None:
            rest = [w for w, _, _ in window[1:]]
            alt_key = normalize_name(" ".join([stripped_first, *rest]))
            if alt_key in name_index:
                alt_start = first_start + (len(first_word) - len(stripped_first))
                return length, alt_start, window_end, name_index[alt_key]

    return None


def resolve_mentions_in_text(
    text: str,
    df: pd.DataFrame,
    name_index: Optional[dict] = None,
) -> list[Mention]:
    """Find every name mention in `text` and resolve it against `df`'s
    roster, scanning left to right and preferring the longest match at each
    position.

    Supports direct id references ("#12") in addition to full-name matches.
    Text that doesn't match anyone is simply not a mention -- there is no
    "unmatched free text" concept here (unlike `resolve_requests`, which
    operates on a field the school explicitly asked "who did you request"
    for); "unmatched" status is reserved for an explicit id reference to a
    nonexistent student.
    """
    if name_index is None:
        name_index = build_name_index(df)
    id_set = set(df[FIELD_STUDENT_ID].tolist())

    tokens = _tokenize(text)
    mentions: list[Mention] = []
    i = 0
    n = len(tokens)
    while i < n:
        word, start, end = tokens[i]

        id_match = _ID_REF_RE.match(word)
        if id_match:
            sid = int(id_match.group(1))
            if sid in id_set:
                mentions.append(Mention(raw_text=word, start=start, end=end, status="matched", student_id=sid))
            else:
                mentions.append(Mention(raw_text=word, start=start, end=end, status="unmatched"))
            i += 1
            continue

        found = _longest_match_at(tokens, i, name_index)
        if found is not None:
            length, m_start, m_end, candidates = found
            candidates = sorted(set(candidates))
            if len(candidates) == 1:
                mentions.append(
                    Mention(raw_text=text[m_start:m_end], start=m_start, end=m_end, status="matched", student_id=candidates[0])
                )
            else:
                mentions.append(
                    Mention(raw_text=text[m_start:m_end], start=m_start, end=m_end, status="ambiguous", candidate_ids=candidates)
                )
            i += length
        else:
            i += 1

    return mentions


def redact_text(text: str, mentions: list[Mention], token_for: Callable[[int], str]) -> str:
    """Replace each *matched* mention's span with an opaque token (via
    `token_for(student_id) -> str`), leaving everything else untouched.

    Callers must resolve ambiguous/unmatched mentions locally with the
    counselor first -- this function passes non-matched spans through as-is
    rather than guessing, so it should only ever be called once a message
    contains no ambiguous/unmatched mentions.
    """
    if not mentions:
        return text
    parts = []
    cursor = 0
    for m in sorted(mentions, key=lambda m: m.start):
        parts.append(text[cursor : m.start])
        if m.status == "matched" and m.student_id is not None:
            parts.append(token_for(m.student_id))
        else:
            parts.append(m.raw_text)
        cursor = m.end
    parts.append(text[cursor:])
    return "".join(parts)
