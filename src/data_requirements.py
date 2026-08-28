"""What the spreadsheet needs to contain, worked out before it exists.

The app used to be unusable until a workbook was uploaded: the chat was hard
-gated on `sess.mapped_df`, so a counselor could not talk through how to
split the year until after she had already built the file. That is backwards.
The decisions -- how many classes, which groups must be kept apart, what
balance matters -- come first, and they are exactly what determines which
columns the file needs.

So planning produces two things: rules, and a list of columns the rules will
need. This module is the second one. A requirement is a promise about the
data ("there will be a yes/no column marking twins"), recorded while it is
still just an intention, and checked off once a workbook arrives that
actually has it.

Nothing here constrains a solve. It is a checklist the counselor fills in
Excel, and the input to the guidance the agent gives about doing so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional

RequirementKind = Literal["flag", "category", "number"]

KIND_LABELS_HE: dict[str, str] = {
    "flag": "עמודת סימון (כן/ריק)",
    "category": "עמודת קטגוריה (ערך אחד מתוך רשימה)",
    "number": "עמודת מספר",
}

KIND_HOWTO_HE: dict[str, str] = {
    "flag": 'סמנו "כן" בשורות הרלוונטיות והשאירו את השאר ריק.',
    "category": "מלאו בכל שורה ערך אחד מתוך הרשימה.",
    "number": "מלאו מספר בכל שורה.",
}


@dataclass
class DataRequirement:
    """One column the counselor needs to add to the workbook."""

    label: str  # the Hebrew column header to create, e.g. "תאומות"
    kind: RequirementKind
    reason: str  # why it's needed, in the counselor's own terms
    values: list[str] = field(default_factory=list)  # suggested values, category only
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "kind_label": KIND_LABELS_HE.get(self.kind, self.kind),
            "how_to_fill": KIND_HOWTO_HE.get(self.kind, ""),
            "reason": self.reason,
            "values": list(self.values),
        }


def match_requirements(requirements: list[DataRequirement], schema=None) -> list[dict]:
    """Mark each requirement satisfied or missing against a loaded workbook.

    Matching is on the visible column label rather than a key, because the
    counselor types the header into Excel by hand -- she is copying the name
    off the checklist, not pasting an internal identifier. Comparison is
    whitespace- and case-insensitive for the same reason.
    """
    have: dict[str, str] = {}
    for col in (schema.extras if schema is not None else []):
        have[str(col.label).strip().lower()] = col.key

    out = []
    for req in requirements:
        key = have.get(req.label.strip().lower())
        entry = req.to_dict()
        entry["satisfied"] = key is not None
        entry["column_key"] = key
        out.append(entry)
    return out


def summarize(requirements: list[DataRequirement], schema=None) -> dict:
    matched = match_requirements(requirements, schema)
    missing = [m for m in matched if not m["satisfied"]]
    return {
        "requirements": matched,
        "total": len(matched),
        "satisfied": len(matched) - len(missing),
        "missing": len(missing),
    }
