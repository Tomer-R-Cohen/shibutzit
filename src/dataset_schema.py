"""Whatever else is in the spreadsheet.

The app has eleven semantic fields it knows by name (see column_mapping.py),
and until now `apply_mapping` built a fresh table containing only those --
every other column in the uploaded workbook was silently dropped. That made
the product a tool for one school's spreadsheet: a school with a "twins"
column or a "needs a quiet classroom" column had nowhere to put it.

The solver never needed that restriction. `src/optimizer.py` contains zero
references to differential/inclusion/hamar/ethiopian_origin -- it works off
Constraint objects whose `group` selector is already generic ({"kind":
"field", "field": <any column>}). So the fix is not in the engine. It is
here: keep the extra columns, work out what kind of thing each one is, and
let the rest of the app address them by name.

What this module deliberately does *not* do is guess meaning. It can tell
that a column holds yes/no values, or a handful of repeated categories, or
numbers -- that is enough to constrain on. What "מיוחד" actually signifies
is a question for the counselor, not a regex.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

import pandas as pd

ColumnKind = Literal["flag", "category", "number"]

# Values that mean yes/no in the spreadsheets this app sees. Deliberately
# generous: Hebrew כן/לא, the single-letter marks the source workbook uses
# (א, V, ✓), and the usual 1/0 and TRUE/FALSE.
_TRUE_TOKENS = {"1", "כן", "true", "v", "✓", "א", "yes", "+", "x"}
_FALSE_TOKENS = {"0", "לא", "false", "no", "-", ""}
_BOOLISH = _TRUE_TOKENS | _FALSE_TOKENS

# Above this many distinct values a text column is free text (names, notes,
# comments), not a category anyone can write a placement rule about.
MAX_CATEGORY_VALUES = 12

# Columns whose header looks like commentary rather than data. Matched
# loosely and only used to skip; a false negative just means one useless
# column shows up in the list.
_NOTE_HEADER = re.compile(r"הערה|הערות|comment|note|remark", re.IGNORECASE)


@dataclass
class ExtraColumn:
    """One spreadsheet column the app didn't already know about."""

    key: str  # column name inside the mapped DataFrame
    source_column: str  # original header text, as it appeared in the file
    label: str  # what to show a human; defaults to the header
    kind: ColumnKind
    values: list[str] = field(default_factory=list)  # category only
    true_count: int = 0  # flag only
    filled_count: int = 0  # non-empty cells, so sparse columns are visible


@dataclass
class DatasetSchema:
    extras: list[ExtraColumn] = field(default_factory=list)

    def get(self, key: str) -> Optional[ExtraColumn]:
        return next((c for c in self.extras if c.key == key), None)

    def keys(self) -> list[str]:
        return [c.key for c in self.extras]

    def to_dicts(self) -> list[dict]:
        return [asdict(c) for c in self.extras]


def sanitize_key(source_column: str, taken: set[str]) -> str:
    """A stable, collision-free DataFrame column name for an extra column.

    Prefixed `x_` so an extra can never shadow a semantic field, and so any
    code reading a mapped frame can tell the two apart at a glance. Hebrew
    is left intact -- pandas, JSON and the model all handle it, and a
    transliterated key would be unreadable to the counselor.
    """
    base = re.sub(r"\s+", "_", str(source_column).strip())
    base = re.sub(r"[^\w֐-׿]+", "", base) or "col"
    key = f"x_{base}"
    if key not in taken:
        return key
    i = 2
    while f"{key}_{i}" in taken:
        i += 1
    return f"{key}_{i}"


def _norm(v: Any) -> str:
    return str(v).strip().lower()


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "nan", "none", "nat")


def classify_series(s: pd.Series) -> tuple[Optional[ColumnKind], list[str], int]:
    """Work out what kind of column this is from its values alone.

    Returns (kind, distinct_values, true_count). kind is None for columns
    nothing useful can be done with: empty, or free text with too many
    distinct values to constrain on.
    """
    non_blank = [v for v in s.tolist() if not _is_blank(v)]
    if not non_blank:
        return None, [], 0

    normed = [_norm(v) for v in non_blank]

    # Flag: every filled cell is a yes/no token, and the column actually
    # splits the roster. A column where nobody is flagged, or where everybody
    # is, describes no subgroup -- offering it as something to constrain on
    # would just be noise in the counselor's list.
    if set(normed) <= _BOOLISH:
        true_count = sum(1 for v in normed if v in _TRUE_TOKENS)
        if 0 < true_count < len(s):
            return "flag", [], true_count

    distinct = list(dict.fromkeys(str(v).strip() for v in non_blank))
    # One distinct value is a constant, not a variable.
    if len(distinct) < 2:
        return None, [], 0

    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_blank):
        return "number", [], 0

    if len(distinct) <= MAX_CATEGORY_VALUES:
        return "category", distinct, 0

    return None, [], 0


def detect_extra_columns(raw_df: pd.DataFrame, mapped_source_columns: set[str]) -> DatasetSchema:
    """Describe every column in the workbook the app doesn't already use.

    `mapped_source_columns` is the set of raw headers already claimed by a
    semantic field, so a school whose file happens to contain a column the
    app knows by name doesn't get it twice.
    """
    schema = DatasetSchema()
    taken: set[str] = set()

    for source in raw_df.columns:
        if source in mapped_source_columns:
            continue
        header = str(source).strip()
        # pandas names blank headers "Unnamed: 4"; those are layout, not data.
        if not header or header.startswith("Unnamed:") or _NOTE_HEADER.search(header):
            continue

        kind, values, true_count = classify_series(raw_df[source])
        if kind is None:
            continue

        key = sanitize_key(header, taken)
        taken.add(key)
        filled = int(sum(1 for v in raw_df[source].tolist() if not _is_blank(v)))
        schema.extras.append(
            ExtraColumn(
                key=key,
                source_column=str(source),
                label=header,
                kind=kind,
                values=values,
                true_count=true_count,
                filled_count=filled,
            )
        )

    return schema


def attach_extra_columns(mapped_df: pd.DataFrame, raw_df: pd.DataFrame, schema: DatasetSchema) -> pd.DataFrame:
    """Copy the detected extras onto the mapped frame under their keys.

    Flags are normalized to real booleans so `resolve_group_members`'s
    `bool(row.get(field))` test means what it says -- a column of "כן"/""
    strings would otherwise read as all-true, since any non-empty string is
    truthy in Python. That bug would silently put every student in the group.
    """
    out = mapped_df.copy()
    if len(out) != len(raw_df):
        # Assignment below is positional; mapping never drops rows, so this
        # would mean an upstream change silently misaligned every extra
        # column against the wrong students.
        raise ValueError(f"row count mismatch: mapped={len(out)} raw={len(raw_df)}")
    for col in schema.extras:
        series = raw_df[col.source_column]
        if col.kind == "flag":
            out[col.key] = [(not _is_blank(v)) and _norm(v) in _TRUE_TOKENS for v in series.tolist()]
        elif col.kind == "number":
            out[col.key] = pd.to_numeric(series, errors="coerce").tolist()
        else:
            out[col.key] = ["" if _is_blank(v) else str(v).strip() for v in series.tolist()]
    return out
