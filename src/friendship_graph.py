"""Friendship request graph: parsing, name normalization, and matching.

Model: a directed graph where an edge A->B means "A requested B as a
friend". A pair is mutual when both A->B and B->A exist. Names are
normalized (whitespace, nikud/quote variants) and matched preferring a
unique student-id match, falling back to a normalized full-name match.
Ambiguous or unmatched names are never auto-merged; they are reported for
the user to resolve manually.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from src.column_mapping import (
    FIELD_FIRST_NAME,
    FIELD_FRIEND_REQUESTS,
    FIELD_LAST_NAME,
    FIELD_STUDENT_ID,
)

_NIKUD_RE = re.compile(r"[֑-ׇ]")
_QUOTE_CHARS = {"׳": "'", "״": '"', "‘": "'", "’": "'", "“": '"', "”": '"'}
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalize a Hebrew name for matching: strip nikud, unify quotes,
    collapse whitespace, and casefold."""
    if name is None:
        return ""
    text = str(name)
    text = unicodedata.normalize("NFC", text)
    text = _NIKUD_RE.sub("", text)
    for src, dst in _QUOTE_CHARS.items():
        text = text.replace(src, dst)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text.casefold()


def split_requested_names(raw: str) -> list[str]:
    """Split a free-text friend-request cell into individual candidate names."""
    if raw is None:
        return []
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return []
    parts = re.split(r"[,;\n/]+", text)
    return [p.strip() for p in parts if p.strip()]


@dataclass
class NameResolutionResult:
    matched: dict[int, list[int]] = field(default_factory=dict)  # student_id -> [requested student_ids]
    unmatched: list[tuple] = field(default_factory=list)  # (requester_id, raw_name)
    ambiguous: list[tuple] = field(default_factory=list)  # (requester_id, raw_name, candidate_ids)


def build_name_index(df: pd.DataFrame) -> dict[str, list[int]]:
    """Build a normalized-full-name -> [student_id,...] index."""
    index: dict[str, list[int]] = {}
    for _, row in df.iterrows():
        full = f"{row[FIELD_FIRST_NAME]} {row[FIELD_LAST_NAME]}"
        key = normalize_name(full)
        index.setdefault(key, []).append(row[FIELD_STUDENT_ID])
        # Also index reversed order and last-name-only+first-name-only combos
        alt = f"{row[FIELD_LAST_NAME]} {row[FIELD_FIRST_NAME]}"
        index.setdefault(normalize_name(alt), []).append(row[FIELD_STUDENT_ID])
    return index


def resolve_requests(df: pd.DataFrame) -> NameResolutionResult:
    """Resolve free-text friend-request names to student ids.

    Args:
        df: mapped student DataFrame containing FIELD_FRIEND_REQUESTS.

    Returns:
        NameResolutionResult with matched edges plus unmatched/ambiguous
        names flagged for manual user review (never auto-merged).
    """
    result = NameResolutionResult()
    name_index = build_name_index(df)
    id_set = set(df[FIELD_STUDENT_ID].tolist())

    for _, row in df.iterrows():
        requester_id = row[FIELD_STUDENT_ID]
        raw_field = row.get(FIELD_FRIEND_REQUESTS, "")
        names = split_requested_names(raw_field)
        for raw_name in names:
            # Direct id reference support, e.g. "#12"
            if raw_name.startswith("#"):
                try:
                    target_id = int(raw_name[1:])
                except ValueError:
                    target_id = None
                if target_id is not None and target_id in id_set:
                    result.matched.setdefault(requester_id, []).append(target_id)
                    continue
                result.unmatched.append((requester_id, raw_name))
                continue

            key = normalize_name(raw_name)
            candidates = name_index.get(key, [])
            candidates = sorted(set(candidates) - {requester_id}) or sorted(set(candidates))
            if len(candidates) == 1:
                result.matched.setdefault(requester_id, []).append(candidates[0])
            elif len(candidates) > 1:
                result.ambiguous.append((requester_id, raw_name, candidates))
            else:
                result.unmatched.append((requester_id, raw_name))

    return result


def is_mutual(a: int, b: int, matched: dict[int, list[int]]) -> bool:
    return b in matched.get(a, []) and a in matched.get(b, [])


def build_edges(matched: dict[int, list[int]]) -> list[tuple[int, int, bool]]:
    """Return list of (from_id, to_id, is_mutual) directed edges."""
    edges = []
    for a, targets in matched.items():
        for b in targets:
            edges.append((a, b, is_mutual(a, b, matched)))
    return edges


def unmatched_report(result: NameResolutionResult) -> pd.DataFrame:
    rows = []
    for requester_id, raw_name in result.unmatched:
        rows.append({"תלמידה מבקשת": requester_id, "שם שלא נמצא": raw_name, "סוג": "לא נמצא"})
    for requester_id, raw_name, candidates in result.ambiguous:
        rows.append(
            {
                "תלמידה מבקשת": requester_id,
                "שם שלא נמצא": raw_name,
                "סוג": f"דו-משמעי ({len(candidates)} מועמדות: {candidates})",
            }
        )
    return pd.DataFrame(rows)
