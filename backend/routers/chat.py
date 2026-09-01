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

import json
import logging
import math
import queue
import re
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from src.chat.mentions import Mention, redact_text, resolve_mentions_in_text
from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_CLASS,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_LABELS_HE,
    FIELD_FIRST_NAME,
    FIELD_LAST_NAME,
    FIELD_STUDENT_ID,
)
from src.constraints import Constraint, capacity_range_label_hebrew
from src.feasibility import analyze_feasibility
from src.metrics import academic_level_spread, violations_report

from ..llm.agent import run_agent_turn, run_grounded_analysis_turn
from ..llm.provider import LLMNotConfiguredError
from ..llm.prompts import (
    build_constraints_context,
    build_dataset_columns_context,
    build_planning_context,
    build_project_memory_context,
    build_result_context,
    build_roster_context,
    build_system_prompt,
)
from ..llm.read_tools import build_read_tool_definitions, execute_read_tool, groupable_field_kinds, groupable_fields
from ..llm.simulation_tools import execute_simulation_tool, is_simulation_tool
from ..llm.tools import TOOL_MODELS, ToolArgumentError, args_to_constraint
from ..data_edits import DataEditError, apply_confirmed_student_edit, normalize_student_value
from ..schemas import MoveStudentRequest
from ..session_store import PendingProposal, Session, store
from ..solver_inputs import build_solver_inputs
from ..utils import require

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatMessageRequest(BaseModel):
    message: str


class SolverResultFollowupRequest(BaseModel):
    version_ids: list[str] = Field(default_factory=list)


_STUDENT_TOKEN_RE = re.compile(r"STUDENT_[A-Za-z0-9]+")


def _display_student_names(text: str, sess: Session) -> str:
    """Restore counselor-facing names without ever sending them to the LLM."""
    if not text or sess.mapped_df is None:
        return text

    def replace(match: re.Match) -> str:
        token = match.group(0)
        sid = sess.token_map.id_for(token)
        if sid is None:
            return "התלמידה"
        row = sess.mapped_df[sess.mapped_df[FIELD_STUDENT_ID] == sid]
        if row.empty:
            return "התלמידה"
        record = row.iloc[0]
        parts = [str(record.get(field, "")).strip() for field in (FIELD_FIRST_NAME, FIELD_LAST_NAME)]
        name = " ".join(part for part in parts if part and part.casefold() != "nan")
        return name or "התלמידה"

    return _STUDENT_TOKEN_RE.sub(replace, text)


def _display_value(value, sess: Session):
    """Create a counselor-facing copy of a response without mutating memory."""
    if isinstance(value, str):
        return _display_student_names(value, sess)
    if isinstance(value, list):
        return [_display_value(item, sess) for item in value]
    if isinstance(value, dict):
        return {key: _display_value(item, sess) for key, item in value.items()}
    return value


class _StudentNameStream:
    """De-tokenize model deltas without leaking a token split across chunks."""

    marker = "STUDENT_"

    def __init__(self, sess: Session, emit):
        self.sess = sess
        self.emit = emit
        self.buffer = ""

    def feed(self, delta: str) -> None:
        self.buffer += delta
        keep_from = len(self.buffer)
        token_start = self.buffer.rfind(self.marker)
        if token_start >= 0 and re.fullmatch(r"STUDENT_[A-Za-z0-9]*", self.buffer[token_start:]):
            keep_from = token_start
        else:
            for length in range(min(len(self.marker) - 1, len(self.buffer)), 0, -1):
                if self.marker.startswith(self.buffer[-length:]):
                    keep_from = len(self.buffer) - length
                    break
        safe = self.buffer[:keep_from]
        self.buffer = self.buffer[keep_from:]
        if safe:
            self.emit(_display_student_names(safe, self.sess))

    def flush(self) -> None:
        if self.buffer:
            self.emit(_display_student_names(self.buffer, self.sess))
            self.buffer = ""


def _message_requests_rerun(message: str) -> bool:
    """Recognize an explicit rerun instruction even if the model omits its flag."""
    normalized = " ".join(message.casefold().split())
    return any(
        phrase in normalized
        for phrase in (
            "נסה שוב",
            "נסי שוב",
            "תנסה שוב",
            "תנסי שוב",
            "הרץ שוב",
            "הריצי שוב",
            "תריץ שוב",
            "תריצי שוב",
            "run again",
            "rerun",
            "optimize again",
        )
    )


def _explicit_solver_request(message: str) -> tuple[bool, int]:
    """Fallback for explicit solve commands when the model replies only in prose."""
    normalized = " ".join(message.casefold().split())
    explicit_phrases = (
        "תחלק",
        "חלקי",
        "תפיק שיבוץ",
        "הפיקי שיבוץ",
        "תריץ את השיבוץ",
        "תריצי את השיבוץ",
        "הרץ את השיבוץ",
        "הריצי את השיבוץ",
        "אפשרויות שיבוץ",
        "חלופות שיבוץ",
        "נסה שוב",
        "נסי שוב",
        "תנסה שוב",
        "תנסי שוב",
        "run the solver",
        "run again",
        "rerun",
    )
    requested = any(phrase in normalized for phrase in explicit_phrases)
    if not requested and ("שלוש אפשרויות" in normalized or "3 אפשרויות" in normalized):
        requested = True
    alternatives = 3 if any(
        phrase in normalized
        for phrase in ("שלוש אפשרויות", "3 אפשרויות", "כמה אפשרויות", "שלוש חלופות", "3 חלופות")
    ) else 1
    return requested, alternatives


def _asks_why_current_placement(message: str) -> bool:
    """Recognize a current-placement question, distinct from a version move."""
    normalized = " ".join(message.casefold().split())
    asks_why = any(term in normalized for term in ("למה", "מדוע", "why"))
    current_placement = any(term in normalized for term in ("שובצה", "נמצאת", "בכיתה", "כאן", "placed", "assigned"))
    version_move = any(term in normalized for term in ("עברה", "הועברה", "גרסה", "קודם", "לפני", "moved", "version", "previous"))
    return asks_why and current_placement and not version_move


def _asks_why_version_move(message: str) -> bool:
    normalized = " ".join(message.casefold().split())
    asks_why = any(term in normalized for term in ("למה", "מדוע", "why"))
    version_move = any(term in normalized for term in ("עברה", "הועברה", "גרסה", "moved", "version"))
    return asks_why and version_move


def _asks_about_class_size_imbalance(message: str) -> bool:
    """Recognize 'why is one class 13 and another 11?' style questions."""
    normalized = " ".join(message.casefold().split())
    asks_why = any(term in normalized for term in ("למה", "מדוע", "איך זה", "why", "how come"))
    size_signal = any(
        term in normalized
        for term in (
            "גודל כיתה",
            "גדלי הכיתות",
            "תלמידות בכיתה",
            "תלמידים בכיתה",
            "כיתה עם",
            "כיתות עם",
            "כיתות",
            "בכיתה",
            "גדולה",
            "גדול",
            "קטנה",
            "קטן",
            "class size",
            "class",
            "students in one class",
            "students and another",
        )
    )
    imbalance_signal = any(
        term in normalized
        for term in ("פער", "שונ", "לא שוו", "יותר", "פחות", "13", "11", "different", "uneven", "unbalance", "another")
    )
    return asks_why and size_signal and imbalance_signal


def _asks_for_assignment_analysis(message: str) -> bool:
    """Recognize requests to inspect the placement as a whole."""
    normalized = " ".join(message.casefold().split())
    placement = any(term in normalized for term in ("שיבוץ", "חלוקה", "assignment", "placement"))
    analysis = any(
        term in normalized
        for term in (
            "נתח",
            "תנתח",
            "תנתחי",
            "לא מאוזן",
            "חוסר איזון",
            "פערים",
            "מה לא טוב",
            "איפה הבעיה",
            "analyze",
            "analyse",
            "unbalanced",
            "imbalanced",
            "what is wrong",
        )
    )
    return placement and analysis


def _asks_for_rule_feasibility_analysis(message: str) -> bool:
    """Recognize requests to prove which active rules are possible alone."""
    normalized = " ".join(message.casefold().split())
    rule_signal = any(term in normalized for term in ("כלל", "חוק", "constraint", "rule"))
    feasibility_signal = any(
        term in normalized
        for term in (
            "בלתי אפשר",
            "לא אפשר",
            "אפשריים בפני עצמם",
            "אפשרי בפני עצמו",
            "היתכנות",
            "מתמטית",
            "feasib",
            "impossible",
            "possible on their own",
            "mathematically",
        )
    )
    analysis_signal = any(
        term in normalized
        for term in ("נתח", "תנתח", "תבדוק", "בדוק", "אילו", "איזה", "analyze", "analyse", "which")
    )
    return rule_signal and feasibility_signal and analysis_signal


def _requested_class_number(message: str) -> Optional[int]:
    normalized = " ".join(message.casefold().split())
    for pattern in (
        r"(?:כיתה|כיתת)\s*(\d+)",
        r"ז\s*[׳'\"]?\s*(\d+)",
        r"class\s*(\d+)",
    ):
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    return None


def _asks_for_class_analysis(message: str) -> bool:
    normalized = " ".join(message.casefold().split())
    if _requested_class_number(message) is None:
        return False
    return any(
        term in normalized
        for term in (
            "נתח",
            "תנתח",
            "למה",
            "מדוע",
            "לא מאוז",
            "בעיה",
            "חריג",
            "יותר מדי",
            "פחות מדי",
            "analyze",
            "analyse",
            "why",
            "unbalanced",
            "problem",
            "outlier",
        )
    )


def _asks_for_data_analysis(message: str) -> bool:
    normalized = " ".join(message.casefold().split())
    data_signal = any(term in normalized for term in ("קובץ", "נתונים", "אקסל", "excel", "file", "data", "roster"))
    analysis_signal = any(
        term in normalized
        for term in (
            "נתח",
            "תנתח",
            "בדוק",
            "חסר",
            "שגיא",
            "בעיה",
            "לתקן",
            "analyze",
            "analyse",
            "missing",
            "error",
            "problem",
            "correct",
        )
    )
    return data_signal and analysis_signal


def _explicit_student_data_edit(message: str, mentions: list[Mention], sess: Session) -> Optional[dict]:
    """Parse only unambiguous corrections; nuanced edits remain model-led."""
    matched = [mention for mention in mentions if mention.status == "matched" and mention.student_id is not None]
    if len(matched) != 1:
        return None
    normalized = " ".join(message.casefold().split())
    if not any(term in normalized for term in ("תעדכן", "עדכן", "תשנה", "שנה", "תקן", "לתקן", "update", "change", "correct", "set ")):
        return None

    field = None
    value = None
    for level in ("מצטיינת", "בינונית", "חלשה"):
        if level in normalized:
            field, value = FIELD_ACADEMIC_LEVEL, level
            break

    category_terms = (
        (FIELD_INCLUSION, ("שילוב", "inclusion")),
        (FIELD_DIFFERENTIAL, ("דיפר", "differential")),
        (FIELD_HAMAR, ('ח"מ', "ח״מ", "hamar")),
        (FIELD_ETHIOPIAN_ORIGIN, ("אתיופ", "ethiopian", "מוצא")),
    )
    if field is None:
        for candidate_field, terms in category_terms:
            if any(term in normalized for term in terms):
                field = candidate_field
                negative = any(
                    term in normalized
                    for term in ("לא ", "אינה", "אינו", "לבטל", "להסיר", "false", "not ", "isn't", "is not")
                )
                value = not negative
                break
    if field is None:
        return None

    return {
        "student": sess.token_map.token_for(matched[0].student_id),
        "field": field,
        "value": value,
        "rerun_after": _message_requests_rerun(message),
        "rationale_hebrew": "לעדכן את נתוני התלמידה לפי התיקון שמסרת",
    }


def _accepts_active_recommendation(message: str) -> bool:
    """Resolve short conversational approval against structured memory."""
    normalized = " ".join(message.casefold().split())
    accepts = any(
        term in normalized
        for term in (
            "כן",
            "תציע",
            "תציעי",
            "תחיל",
            "תחילי",
            "תשתמש",
            "תשתמשי",
            "לך על",
            "לכי על",
            "אשר",
            "apply",
            "use it",
            "go with",
            "yes",
            "כל החבילה",
            "את החבילה",
            "את כולם",
            "את כולן",
            "כולם",
            "כולן",
            "the whole package",
            "all of them",
        )
    )
    rejects = any(term in normalized for term in ("לא ", "אל ", "don't", "do not", "no "))
    return accepts and not rejects


def _requests_entire_recommendation_package(message: str) -> bool:
    normalized = " ".join(message.casefold().split())
    return any(
        phrase in normalized
        for phrase in (
            "כל החבילה",
            "את החבילה",
            "את כולם",
            "את כולן",
            "כולם",
            "כולן",
            "כל השינויים",
            "the whole package",
            "all of them",
            "apply all",
        )
    )


def _capacity_change_details(target: Constraint, new_min: int | None, new_max: int | None) -> tuple[dict, str]:
    """Build a synchronized args/label update for one existing capacity rule."""
    next_args = dict(target.args)
    next_args.update({"min": new_min, "max": new_max})
    if next_args.get("group", {}).get("kind") == "all":
        next_args["size_diff"] = 0 if new_min == new_max else next_args.get("size_diff", 0)
    group = next_args.get("group", {})
    if group.get("kind") == "all":
        label = f"גודל כיתה בדיוק {new_min}" if new_min == new_max else f"גודל כיתה בין {new_min} ל-{new_max}"
    elif group.get("kind") == "field" and group.get("field") in {
        FIELD_ETHIOPIAN_ORIGIN,
        FIELD_INCLUSION,
        FIELD_HAMAR,
    }:
        label = capacity_range_label_hebrew(group["field"], new_min, new_max)
    elif group.get("field") == FIELD_DIFFERENTIAL:
        label = f"עד {new_max} תלמידות דיפרנציאליות לכיתה"
    else:
        label = target.label_hebrew
    return next_args, label


def _build_capacity_package_proposal(sess: Session, recommendation: dict) -> PendingProposal:
    """Turn a proven set of arithmetic relaxations into one atomic proposal."""
    batch = []
    descriptions = []
    for item in recommendation.get("items", []):
        target = next(
            (
                constraint
                for constraint in sess.constraints
                if constraint.id == item.get("constraint_id") and constraint.active and constraint.type == "capacity"
            ),
            None,
        )
        if target is None:
            raise ToolArgumentError("one of the recommended rules is no longer active; rerun feasibility analysis")
        new_min = item.get("min")
        new_max = item.get("max")
        next_args, new_label = _capacity_change_details(target, new_min, new_max)
        if next_args == target.args:
            continue
        batch.append(
            {
                "constraint_id": target.id,
                "changes": {"args": next_args, "label_hebrew": new_label},
                "from": {"min": target.args.get("min"), "max": target.args.get("max")},
                "to": {"min": new_min, "max": new_max},
            }
        )
        descriptions.append(
            f"{target.label_hebrew}: {target.args.get('min')}–{target.args.get('max')} → {new_min}–{new_max}"
        )
    if not batch:
        raise ToolArgumentError("all recommended changes are already active")
    summary = "להחיל יחד את כל הריכוכים שנבדקו חשבונית: " + "; ".join(descriptions)
    return PendingProposal(
        kind="modify",
        summary_hebrew=summary,
        changes={"batch": batch},
        evidence={
            "basis": "arithmetic_feasibility_package",
            "changes_hard_rule": True,
            "item_count": len(batch),
            "analysis": recommendation.get("evidence"),
        },
    )


def _assistant_offered_to_apply_recommendation(text: str) -> bool:
    """Whether the preceding answer asked for approval to make a tested change real.

    A successful simulation is not itself an edit.  When the assistant then
    explicitly asks whether to apply that exact change, a short ``yes`` is the
    counselor's approval -- making them approve the same decision twice is both
    unnatural and, with a small model, prone to launching the simulation again.
    """
    normalized = " ".join((text or "").casefold().split())
    return any(
        phrase in normalized
        for phrase in (
            "להחיל",
            "ליישם",
            "באופן קבוע",
            "לעדכן את הכלל",
            "לעדכן את כלל",
            "שאעדכן",
            "שיבוץ מלא",
            "העשייה הרשמית",
            "עשייה הרשמית",
            "apply this",
            "apply the change",
            "make this permanent",
            "run the full assignment",
        )
    )


def _remember_successful_simulation_recommendation(sess: Session, turn_steps: list[dict], answer: str) -> None:
    """Persist an exact actionable change from any successful model-led trial.

    The deterministic analysis paths already create ``active_recommendation``.
    Natural follow-ups can make the model call a simulation tool directly,
    though.  Without this normalization, the measured result exists only in
    prose and a later "yes" can cause GPT-4o mini to repeat the experiment.
    """
    for step in reversed(turn_steps):
        if not step.get("ok"):
            continue
        tool = step.get("tool")
        if tool not in {
            "simulate_capacity_change",
            "simulate_balance_priority",
            "simulate_friendship_priority",
        }:
            continue
        evidence = step.get("result") or {}
        after = evidence.get("after") or {}
        if evidence.get("feasible") is not True or int(after.get("violations", 0) or 0) != 0:
            continue
        args = step.get("args") or {}
        target = next(
            (item for item in sess.constraints if item.id == args.get("constraint_id") and item.active),
            None,
        )
        if target is None:
            continue

        recommendation = None
        if tool == "simulate_capacity_change" and target.type == "capacity":
            new_min = args.get("min", target.args.get("min"))
            new_max = args.get("max", target.args.get("max"))
            if new_min is not None and new_max is not None and (
                new_min != target.args.get("min") or new_max != target.args.get("max")
            ):
                recommendation = {
                    "kind": "capacity_change",
                    "constraint_id": target.id,
                    "min": int(new_min),
                    "max": int(new_max),
                }
        elif tool == "simulate_balance_priority" and target.type == "balance" and args.get("weight") is not None:
            if args["weight"] != target.args.get("weight"):
                recommendation = {
                    "kind": "balance_priority_change",
                    "constraint_id": target.id,
                    "weight": args["weight"],
                }
        elif tool == "simulate_friendship_priority" and target.type == "friendship_objective":
            changed = {
                key: args[key]
                for key in ("weight_mutual", "weight_two_friends")
                if args.get(key) is not None and args[key] != target.args.get(key)
            }
            if changed:
                recommendation = {
                    "kind": "friendship_priority_change",
                    "constraint_id": target.id,
                    **changed,
                }

        if recommendation is not None:
            recommendation.update(
                {
                    "source_question": sess.chat_history[-1].get("content", "") if sess.chat_history else "",
                    "evidence": evidence,
                    "approval_ready": _assistant_offered_to_apply_recommendation(answer),
                }
            )
            sess.active_recommendation = recommendation
            return


def _confirmed_chat_response(applied: dict) -> dict:
    """Adapt the confirmation endpoint payload to a normal chat response."""
    return {
        "reply": applied["confirmation_message"],
        "pending_proposal": None,
        "steps": [],
        "state_changed": applied.get("state_changed", True),
        "solver_run_requested": applied.get("solver_run_requested", False),
        "solver_run_count": 1,
        "suggestions": [],
        "result_state": applied.get("result_state"),
    }


def _grounded_class_size_explanation(turn_steps: list[dict]) -> Optional[str]:
    size_step = next(
        (item for item in reversed(turn_steps) if item.get("tool") == "get_class_sizes" and item.get("ok")),
        None,
    )
    if size_step is None:
        return None
    data = size_step.get("result") or {}
    classes = data.get("classes") or []
    if not classes:
        return None
    smallest = data.get("smallest", 0)
    largest = data.get("largest", 0)
    small_classes = [str(item["class"]) for item in classes if item.get("size") == smallest]
    large_classes = [str(item["class"]) for item in classes if item.get("size") == largest]
    rule = data.get("size_rule") or {}
    lo, hi = rule.get("min"), rule.get("max")

    if smallest == largest:
        return f"בדקתי את השיבוץ הנוכחי: בכל הכיתות יש {smallest} תלמידות, ולכן כרגע אין פער בגודל הכיתות."

    opening = (
        f"בדקתי את השיבוץ עצמו. בכיתה {', '.join(large_classes)} יש {largest} תלמידות, "
        f"ובכיתה {', '.join(small_classes)} יש {smallest}. "
    )
    if rule:
        rule_text = (
            f"כלל גודל הכיתה הפעיל מאפשר {lo if lo is not None else 0}–{hi if hi is not None else 'ללא תקרה'} תלמידות בכיתה, "
            "ולכן שני הגדלים עומדים בכלל החובה. "
        )
    else:
        rule_text = "לא מצאתי כלל פעיל שמחייב גודל אחיד בין הכיתות. "
    reason = (
        "השוויון עצמו אינו יעד שהמנוע ממקסם כרגע: בתוך הטווח המותר הוא רשאי להשתמש בגמישות כדי לשפר את יתר היעדים, "
        "כמו חברות ואיזון לימודי. זה מסביר מה ההגדרות מאפשרות, אך אינו מוכיח איזה יעד מסוים גרם דווקא לחלוקה הזאת."
    )

    simulation = next(
        (item for item in reversed(turn_steps) if item.get("tool") == "simulate_capacity_change" and item.get("ok")),
        None,
    )
    if simulation is None:
        return opening + rule_text + reason
    trial = simulation.get("result") or {}
    if trial.get("feasible"):
        before, after = trial.get("before") or {}, trial.get("after") or {}
        after_sizes = after.get("class_sizes") or []
        target = f"{min(after_sizes)}–{max(after_sizes)}" if after_sizes else "טווח הדוק יותר"
        measured = f" בדיקת ניסיון עם גודל {target} הצליחה וכל כללי החובה נשמרו."
        if before.get("friendship_available"):
            measured += (
                f" חברות הדדית השתנתה מ-{before.get('mutual_pct', 0):g}% ל-{after.get('mutual_pct', 0):g}%, "
                f"ושתי חברות מ-{before.get('two_friends_pct', 0):g}% ל-{after.get('two_friends_pct', 0):g}%."
            )
        if before.get("academic_spread") is not None and after.get("academic_spread") is not None:
            measured += f" מדד הפער הלימודי השתנה מ-{before['academic_spread']} ל-{after['academic_spread']}."
        measured += " זו הרצת ניסיון קצרה בלבד. אם תרצי, אוכל להציע לעדכן את כלל הגודל; השינוי ייכנס לתוקף רק לאחר אישורך."
        return opening + rule_text + reason + measured
    if trial.get("feasible") is False:
        return opening + rule_text + reason + " בדיקת טווח הדוק יותר לא מצאה שיבוץ אפשרי לפי כללי החובה הנוכחיים."
    return opening + rule_text + reason


def _grounded_student_explanation(turn_steps: list[dict]) -> Optional[str]:
    """Render only facts the placement-inspection tool actually verified."""
    step = next(
        (
            item
            for item in reversed(turn_steps)
            if item.get("tool") == "explain_student_placement" and item.get("ok")
        ),
        None,
    )
    if step is None:
        return None
    data = step.get("result") or {}
    if data.get("error") or data.get("assigned_class") is None:
        return None

    student = data.get("student", "התלמידה")
    assigned_class = data["assigned_class"]
    checks = data.get("direct_move_checks") or []
    other_blockers = {
        (rule.get("label_hebrew") or rule.get("type"))
        for check in checks
        for rule in check.get("new_blocking_rules", [])
        if rule.get("type") != "locked" and (rule.get("label_hebrew") or rule.get("type"))
    }

    if data.get("locked"):
        opening = (
            f"{student} נמצאת בכיתה {assigned_class}, והשיבוץ שלה מקובע שם ידנית. "
            "הקיבוע הוא הסיבה המאומתת לכך שלא ניתן להעביר אותה כרגע ישירות לכיתה אחרת."
        )
        if other_blockers:
            blocker_text = " בבדיקת העברה של התלמידה בלבד נמצאו גם התנגשויות אפשריות עם: " + ", ".join(
                sorted(other_blockers)
            ) + "."
        else:
            blocker_text = " לא נמצא כלל חובה אחר שחוסם את כל החלופות; כדי לבחון מעבר צריך קודם לבטל את הקיבוע."
    else:
        feasible = [str(check["class"]) for check in checks if check.get("direct_move_preserves_hard_rules")]
        opening = f"{student} נמצאת בכיתה {assigned_class}."
        if feasible:
            blocker_text = (
                " העברה שלה בלבד לכיתות " + ", ".join(feasible)
                + " אינה יוצרת הפרת חובה חדשה, ולכן הנתונים אינם מוכיחים שהכיתה הנוכחית הייתה האפשרות היחידה."
            )
        elif other_blockers:
            blocker_text = " העברה ישירה נחסמת לפי הכללים המאומתים: " + ", ".join(sorted(other_blockers)) + "."
        else:
            blocker_text = " אין בבדיקה גורם מאומת שמסביר לבדו את הבחירה בכיתה הזו."

    friendship = data.get("friend_requests") or {}
    if friendship.get("requested", 0) == 0:
        friendship_text = " לא הוזנו עבורה בקשות חברות, ולכן חברות לא יכולה להסביר את הבחירה."
    else:
        friendship_text = (
            f" מתוך {friendship.get('requested', 0)} בקשות חברות, "
            f"{friendship.get('placed_together', 0)} נמצאות איתה בכיתה."
        )
    limit = " אין בתוצאה תיעוד של סיבה יחידה שבגללה המנגנון בחר בין כמה חלופות תקינות."
    return opening + blocker_text + friendship_text + limit


def _grounded_student_version_explanation(turn_steps: list[dict]) -> Optional[str]:
    """Describe a student's measured version delta without inventing causality."""
    step = next(
        (
            item
            for item in reversed(turn_steps)
            if item.get("tool") == "compare_student_versions" and item.get("ok")
        ),
        None,
    )
    if step is None:
        return None
    data = step.get("result") or {}
    if data.get("error"):
        return None
    before, after = data.get("before") or {}, data.get("after") or {}
    if before.get("class") is None or after.get("class") is None:
        return None

    student = data.get("student", "התלמידה")
    from_version, to_version = before.get("version_number"), after.get("version_number")
    if not data.get("moved"):
        return (
            f"{student} לא עברה כיתה בין גרסה {from_version} לגרסה {to_version}; "
            f"בשתי הגרסאות היא נמצאת בכיתה {after['class']}."
        )

    parts = [
        f"{student} עברה מכיתה {before['class']} בגרסה {from_version} לכיתה {after['class']} בגרסה {to_version}."
    ]
    before_friends = before.get("friend_requests") or {}
    after_friends = after.get("friend_requests") or {}
    requested = max(int(before_friends.get("requested", 0)), int(after_friends.get("requested", 0)))
    if requested == 0:
        parts.append("לא הוזנו עבורה בקשות חברות, ולכן חברות אינה הסבר אפשרי למעבר.")
    else:
        parts.append(
            f"מספר החברות שביקשה ונמצאות איתה השתנה מ-{before_friends.get('placed_together', 0)} "
            f"ל-{after_friends.get('placed_together', 0)} מתוך {requested}."
        )

    academic_before = before.get("academic_level_spread")
    academic_after = after.get("academic_level_spread")
    if academic_before is not None and academic_after is not None:
        direction = "השתפר" if academic_after < academic_before else "נחלש" if academic_after > academic_before else "נשאר ללא שינוי"
        parts.append(f"מדד האיזון הלימודי הכולל {direction} ({academic_before} ל-{academic_after}); זו תצפית על הגרסאות, לא הוכחה לסיבת המעבר.")

    return_check = data.get("return_to_previous_class_check") or {}
    if return_check.get("available"):
        blockers = [
            rule.get("label_hebrew") or rule.get("type")
            for rule in return_check.get("new_blocking_rules", [])
            if rule.get("label_hebrew") or rule.get("type")
        ]
        if blockers:
            parts.append(
                "בגרסה החדשה, החזרה שלה לבדה לכיתה הקודמת הייתה יוצרת הפרת חובה חדשה: "
                + ", ".join(sorted(set(blockers)))
                + "."
            )
        else:
            parts.append(
                "בדיקה שבה מחזירים רק אותה לכיתה הקודמת אינה יוצרת הפרת חובה חדשה, "
                "ולכן כלל חובה אינו מסביר לבדו את המעבר."
            )
    elif return_check:
        parts.append("לא ניתן לבדוק החזרה ישירה, משום שמבנה הכיתות השתנה בין הגרסאות.")

    parts.append("הגרסאות אינן מתעדות גורם יחיד שבגללו המנוע בחר במהלך הזה מבין כמה שיבוצים אפשריים.")
    return " ".join(parts)


def _academic_spread(sess: Session, version) -> Optional[int]:
    """Sum of per-level class-count spreads; zero is perfectly even."""
    stored = version.metrics.get("academic_level_spread")
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        return int(stored)
    df = sess.mapped_df
    if df is None:
        return None
    num_classes = int(version.run_config.get("num_classes", sess.run_config.num_classes))
    return academic_level_spread(df, version.assignment, num_classes)


def _grounded_solver_comparison(
    sess: Session,
    requested_ids: list[str],
    baseline_id: Optional[str] = None,
) -> Optional[str]:
    """Concise measured comparison for multi-option runs; never invent a ranking."""
    versions = [version for version in sess.assignment_versions if version.id in requested_ids]
    versions.sort(key=lambda version: requested_ids.index(version.id))
    if len(versions) < 2:
        return None

    academic = {version.id: _academic_spread(sess, version) for version in versions}
    all_valid = all(version.metrics.get("violations_count", 0) == 0 for version in versions)
    clauses = []
    previous = None
    for version in versions:
        metrics = version.metrics
        sizes = metrics.get("class_sizes") or []
        size_text = f"{min(sizes)}–{max(sizes)}" if sizes else "לא זמין"
        moved_text = ""
        if previous is not None:
            ids = set(previous.assignment) | set(version.assignment)
            moved = sum(previous.assignment.get(sid) != version.assignment.get(sid) for sid in ids)
            moved_text = f", ו-{moved} תלמידות השתנו לעומת הגרסה הקודמת"
        friendship_text = (
            f"{metrics.get('mutual_satisfied_pct', 0):g}% עם בקשה הדדית, "
            f"{metrics.get('two_friends_satisfied_pct', 0):g}% עם לפחות שתי חברות, "
            if metrics.get("students_with_requests", 0) > 0
            else "אין נתוני בקשות חברות למדידה, "
        )
        mandatory_text = (
            "כל כללי החובה מתקיימים"
            if metrics.get("violations_count", 0) == 0
            else f"{metrics.get('violations_count', 0)} חריגות מכללי חובה"
        )
        clauses.append(f"בגרסה {version.number}: {friendship_text}גדלי כיתות {size_text}, {mandatory_text}{moved_text}")
        previous = version

    def friendship_two_weight(version) -> float:
        rule = next(
            (item for item in version.constraints if item.get("type") == "friendship_objective" and item.get("active")),
            None,
        )
        return float((rule or {}).get("args", {}).get("weight_two_friends", 0))

    def comparable_run_config(version) -> dict:
        # Search time and deterministic tie-break seed affect how a solution
        # is found, not what the counselor asked the solver to optimize.
        # Alternative runs intentionally advance the seed, so including it
        # here would make three genuine alternatives look incomparable.
        return {
            key: value
            for key, value in version.run_config.items()
            if key not in {"random_seed", "time_limit_seconds"}
        }

    same_configuration = all(
        version.constraints == versions[0].constraints
        and comparable_run_config(version) == comparable_run_config(versions[0])
        for version in versions[1:]
    )
    two_weights = [friendship_two_weight(version) for version in versions]
    valid_versions = [version for version in versions if version.metrics.get("violations_count", 0) == 0]
    scored_versions = [
        version
        for version in valid_versions
        if isinstance(version.metrics.get("objective_value"), (int, float))
        and not isinstance(version.metrics.get("objective_value"), bool)
        and math.isfinite(float(version.metrics["objective_value"]))
    ]
    friendship_available = all(version.metrics.get("students_with_requests", 0) > 0 for version in versions)
    if not valid_versions:
        best = []
        recommendation_basis = "no_valid"
    elif same_configuration and scored_versions:
        best_score = max(float(version.metrics["objective_value"]) for version in scored_versions)
        best = [version for version in scored_versions if float(version.metrics["objective_value"]) == best_score]
        recommendation_basis = "overall"
    elif friendship_available and two_weights[-1] > two_weights[0]:
        best_two = max(version.metrics.get("two_friends_satisfied_pct", 0) for version in valid_versions)
        best = [version for version in valid_versions if version.metrics.get("two_friends_satisfied_pct", 0) == best_two]
        recommendation_basis = "two_friends"
    else:
        best = []
        recommendation_basis = "not_comparable"
    academic_values = {value for value in academic.values() if value is not None}
    validity = "כל כללי החובה מתקיימים בכל שלוש החלופות. " if all_valid and len(versions) == 3 else (
        "כל כללי החובה מתקיימים בכל החלופות. " if all_valid else "יש הבדלים בעמידה בכללי החובה. "
    )
    if not academic_values:
        academic_text = "אין בקובץ מידע לימודי שמאפשר להשוות איזון לימודי. "
    elif len(academic_values) == 1:
        academic_text = "האיזון הלימודי זהה לפי המדד הזמין. "
    else:
        comparable_academic = [version for version in versions if academic[version.id] is not None]
        academic_text = f"הפער הלימודי הקטן ביותר נמצא בגרסה {min(comparable_academic, key=lambda item: academic[item.id]).number}. "
    baseline_text = ""
    baseline = next((version for version in sess.assignment_versions if version.id == baseline_id), None)
    if baseline is not None and len(best) == 1 and baseline.id != best[0].id:
        recommended = best[0]
        ids = set(baseline.assignment) | set(recommended.assignment)
        moved = sum(baseline.assignment.get(sid) != recommended.assignment.get(sid) for sid in ids)
        academic_before = _academic_spread(sess, baseline)
        academic_after = academic[recommended.id]
        academic_direction = "אינו זמין להשוואה"
        if academic_before is not None and academic_after is not None:
            academic_direction = "השתפר" if academic_after < academic_before else "נחלש" if academic_after > academic_before else "נשאר ללא שינוי"
        friendship_change = ""
        if baseline.metrics.get("students_with_requests", 0) > 0 and recommended.metrics.get("students_with_requests", 0) > 0:
            friendship_change = (
                f"יעד שתי החברות השתנה מ-{baseline.metrics.get('two_friends_satisfied_pct', 0):g}% "
                f"ל-{recommended.metrics.get('two_friends_satisfied_pct', 0):g}%, והבקשות ההדדיות מ-"
                f"{baseline.metrics.get('mutual_satisfied_pct', 0):g}% ל-"
                f"{recommended.metrics.get('mutual_satisfied_pct', 0):g}%, "
            )
        baseline_text = f"לעומת השיבוץ שהיה פעיל לפני ההרצה, {friendship_change}{moved} תלמידות עברו כיתה, והאיזון הלימודי {academic_direction}."

    if len(best) == 1:
        recommended = best[0]
        reason = (
            "משיגה את התוצאה הגבוהה ביותר ביעד של שתי חברות"
            if recommendation_basis == "two_friends"
            else "קיבלה את הציון הכולל הגבוה ביותר לפי סדרי העדיפויות הפעילים"
        )
        recommendation = f"אני ממליץ על גרסה {recommended.number}, כי היא {reason}."
    elif recommendation_basis == "no_valid":
        recommendation = "אין גרסה תקינה שאפשר להמליץ עליה לפני תיקון חריגות החובה."
    elif recommendation_basis == "not_comparable":
        recommendation = (
            "הגרסאות נוצרו עם סדרי עדיפויות שונים, ולכן הציון הכולל שלהן אינו בר-השוואה; "
            "הבחירה צריכה להתבסס על השינוי במדדים שמוצג כאן."
        )
    else:
        recommendation = (
            "אין יתרון איכותי מדוד בין הגרסאות המובילות; השארת הנוכחית תחסוך שינוי, "
            "אבל אינה הופכת אותה לטובה יותר."
        )
    return validity + "; ".join(clauses) + ". " + academic_text + baseline_text + " " + recommendation


def _proposal_from_friendship_simulation(message: str, turn_steps: list[dict], sess: Session):
    """Turn an explicitly requested, measured priority trial into an approvable change."""
    normalized = message.casefold()
    if not any(phrase in normalized for phrase in ("תציע", "הצע", "לאשר", "apply", "approve")):
        return None
    step = next(
        (
            item
            for item in reversed(turn_steps)
            if item.get("tool") == "simulate_friendship_priority" and item.get("ok")
        ),
        None,
    )
    if step is None or not (step.get("result") or {}).get("feasible"):
        return None
    args = step.get("args") or {}
    target = next((item for item in sess.constraints if item.id == args.get("constraint_id")), None)
    if target is None or target.type != "friendship_objective":
        return None
    asks_for_increase = any(
        phrase in normalized for phrase in ("יותר חשיבות", "להעלות", "עדיפות גבוהה", "increase", "higher")
    )
    if asks_for_increase:
        current_mutual = float(target.args.get("weight_mutual", 0))
        current_two = float(target.args.get("weight_two_friends", 0))
        proposed_mutual = float(args.get("weight_mutual", current_mutual))
        proposed_two = float(args.get("weight_two_friends", current_two))
        specifically_two = "שתי חברות" in normalized or "two friend" in normalized
        if (specifically_two and proposed_two <= current_two) or (
            not specifically_two and proposed_two <= current_two and proposed_mutual <= current_mutual
        ):
            return None
    next_args = dict(target.args)
    for key in ("weight_mutual", "weight_two_friends"):
        if args.get(key) is not None and float(args[key]) > 0:
            next_args[key] = args[key]
    if next_args == target.args:
        return None
    evidence = step["result"]
    proposal = PendingProposal(
        kind="modify",
        summary_hebrew="להחיל את עדיפות החברות שנבדקה, בלי לשנות אף כלל חובה",
        target_constraint_id=target.id,
        changes={"args": next_args},
        evidence=evidence,
    )
    before = evidence.get("before") or {}
    after = evidence.get("after") or {}
    summary = (
        f"בדיקת הניסיון העלתה את היעד של לפחות שתי חברות מ-{before.get('two_friends_pct', 0):g}% "
        f"ל-{after.get('two_friends_pct', 0):g}%, ואת הבקשות ההדדיות מ-"
        f"{before.get('mutual_pct', 0):g}% ל-{after.get('mutual_pct', 0):g}%. "
        "אני מציעה להחיל את העדיפות שנבדקה; אף כלל חובה לא ישתנה. לאשר?"
    )
    proposal.summary_hebrew = summary
    return proposal, summary


def _explicit_friendship_priority_proposal(message: str) -> bool:
    normalized = message.casefold()
    friendship = "חבר" in normalized or "friend" in normalized
    proposal = any(
        phrase in normalized
        for phrase in ("תציע", "הצע", "יותר חשיבות", "עדיפות גבוהה", "להעלות את העדיפות", "apply")
    )
    return friendship and proposal


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
        current_version = next(
            (version for version in sess.assignment_versions if version.id == sess.current_version_id),
            None,
        )
        has_friendship_data = bool(
            current_version and current_version.metrics.get("students_with_requests", 0) > 0
        )
        if "get_class_sizes" in tools:
            suggestions = [
                {"label": "בדיקת הרכב הכיתות", "message": "בדוק את הרכב הכיתות והצבע על פערים משמעותיים."},
            ]
            suggestions.append(
                {"label": "בדיקת בקשות חברות", "message": "בדוק את המענה לבקשות החברות בשיבוץ."}
                if has_friendship_data
                else {"label": "בדיקת איזון לימודי", "message": "בדוק את האיזון הלימודי בין הכיתות."}
            )
            return suggestions
        suggestions = [{"label": "איתור פערים", "message": "אילו פערים משמעותיים כדאי לבדוק בשיבוץ?"}]
        suggestions.insert(
            0,
            {"label": "בדיקת בקשות חברות", "message": "בדוק את המענה לבקשות החברות בשיבוץ."}
            if has_friendship_data
            else {"label": "בדיקת איזון לימודי", "message": "בדוק את האיזון הלימודי בין הכיתות."},
        )
        return suggestions
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


def _build_proposal(
    tool_name: str,
    raw_args: dict,
    sess: Session,
    user_message: Optional[str] = None,
) -> tuple[PendingProposal, str]:
    model_cls = TOOL_MODELS.get(tool_name)
    if model_cls is None:
        raise ToolArgumentError(f"unknown tool: {tool_name}")
    args = model_cls(**raw_args)

    if tool_name == "propose_student_data_edit":
        if sess.mapped_df is None:
            raise ToolArgumentError("a mapped workbook is required before correcting student data")
        student_id = sess.token_map.id_for(args.student)
        if student_id is None:
            raise ToolArgumentError("unknown student token")
        row = sess.mapped_df.loc[sess.mapped_df[FIELD_STUDENT_ID] == student_id]
        if row.empty:
            raise ToolArgumentError("student no longer exists in the project data")
        safe_fields = {
            FIELD_CURRENT_SCHOOL,
            FIELD_CURRENT_CLASS,
            FIELD_ACADEMIC_LEVEL,
            FIELD_DIFFERENTIAL,
            FIELD_ETHIOPIAN_ORIGIN,
            FIELD_INCLUSION,
            FIELD_HAMAR,
            *(item.key for item in sess.dataset_schema.extras),
        }
        if args.field not in safe_fields:
            raise ToolArgumentError(
                "that field is not editable through this tool; inspect get_student_record and use one of its editable keys"
            )
        sensitive_terms = {
            FIELD_DIFFERENTIAL: ("דיפר", "differential"),
            FIELD_ETHIOPIAN_ORIGIN: ("אתיופ", "ethiopian", "origin", "מוצא"),
            FIELD_INCLUSION: ("שילוב", "inclusion"),
            FIELD_HAMAR: ('ח"מ', "ח״מ", "hamar"),
        }
        if args.field in sensitive_terms:
            normalized_message = (user_message or "").casefold()
            if not any(term.casefold() in normalized_message for term in sensitive_terms[args.field]):
                raise ToolArgumentError(
                    "a sensitive category value may be changed only when the counselor explicitly states that category in this message"
                )
        extra_kinds = {item.key: item.kind for item in sess.dataset_schema.extras}
        try:
            normalized_value = normalize_student_value(sess.mapped_df, args.field, args.value, extra_kinds)
        except DataEditError as exc:
            raise ToolArgumentError(str(exc)) from exc
        old_value = row.iloc[0][args.field]
        if old_value == normalized_value:
            raise ToolArgumentError("the requested value is already active")
        label = FIELD_LABELS_HE.get(
            args.field,
            next((item.label for item in sess.dataset_schema.extras if item.key == args.field), args.field),
        )
        summary = (
            f"{args.rationale_hebrew} השדה '{label}' ישתנה מ-'{old_value}' ל-'{normalized_value}' "
            "בעותק העבודה; קובץ המקור יישמר ללא שינוי. לאשר?"
        )
        return (
            PendingProposal(
                kind="data_action",
                summary_hebrew=summary,
                action="edit_student_data",
                action_args={
                    "student_id": student_id,
                    "field": args.field,
                    "value": normalized_value,
                    "rerun_after": args.rerun_after,
                },
            ),
            summary,
        )

    if tool_name == "propose_student_placement":
        if sess.adjustment_state is None or sess.opt_result is None or not sess.opt_result.is_feasible:
            raise ToolArgumentError("a successful assignment is required before moving a student")
        student_id = sess.token_map.id_for(args.student)
        if student_id is None or student_id not in sess.adjustment_state.assignment:
            raise ToolArgumentError("unknown student token")
        if not 1 <= args.class_number <= sess.run_config.num_classes:
            raise ToolArgumentError(f"class_number must be between 1 and {sess.run_config.num_classes}")
        current_class = sess.adjustment_state.assignment[student_id] + 1
        if student_id in sess.locked_assignment and args.class_number != current_class:
            raise ToolArgumentError(
                "student placement is manually locked; the counselor must explicitly approve unlocking it before a move"
            )
        candidate = dict(sess.adjustment_state.assignment)
        candidate[student_id] = args.class_number - 1
        _cfg, constraints = build_solver_inputs(sess)
        before_count = len(violations_report(sess.mapped_df, sess.adjustment_state.assignment, constraints, _cfg.num_classes))
        after_count = len(violations_report(sess.mapped_df, candidate, constraints, _cfg.num_classes))
        warning = ""
        if after_count > before_count:
            warning = f" ההעברה תוסיף {after_count - before_count} חריגות ממכסות חובה לפני אופטימיזציה מחדש."
        summary = f"{args.rationale_hebrew} (מכיתה {current_class} לכיתה {args.class_number}).{warning}"
        proposal = PendingProposal(
            kind="assignment_action",
            summary_hebrew=summary,
            action="move_student",
            action_args={
                "student_id": student_id,
                "new_class": args.class_number,
                "locked": args.lock_after_move,
                "rerun_after": args.rerun_after,
            },
        )
        return proposal, f"הבנתי את שינוי השיבוץ. לאשר את ההעברה?{warning}"

    if tool_name == "propose_student_lock":
        if sess.adjustment_state is None or sess.opt_result is None or not sess.opt_result.is_feasible:
            raise ToolArgumentError("a successful assignment is required before changing a lock")
        student_id = sess.token_map.id_for(args.student)
        if student_id is None or student_id not in sess.adjustment_state.assignment:
            raise ToolArgumentError("unknown student token")
        class_number = sess.adjustment_state.assignment[student_id] + 1
        proposal = PendingProposal(
            kind="assignment_action",
            summary_hebrew=args.rationale_hebrew,
            action="set_student_lock",
            action_args={
                "student_id": student_id,
                "class_number": class_number,
                "locked": args.locked,
                "rerun_after": args.rerun_after,
            },
        )
        verb = "לקבע" if args.locked else "לבטל את הקיבוע של"
        return proposal, f"הבנתי: {verb} התלמידה בכיתה {class_number}. לאשר?"

    if tool_name == "propose_restore_version":
        version = next((item for item in sess.assignment_versions if item.id == args.version_id), None)
        if version is None:
            raise ToolArgumentError("unknown assignment version; call get_assignment_versions first")
        proposal = PendingProposal(
            kind="assignment_action",
            summary_hebrew=args.rationale_hebrew,
            action="restore_version",
            action_args={"version_id": version.id, "version_number": version.number},
        )
        return proposal, f"הבנתי: לשחזר את גרסה {version.number}. לאשר את השחזור?"

    if tool_name == "modify_constraint":
        target = next((c for c in sess.constraints if c.id == args.constraint_id), None)
        if target is None:
            raise ToolArgumentError(f"constraint {args.constraint_id} not found")
        if args.hard is True and target.type in {"balance", "friendship_objective"}:
            raise ToolArgumentError(
                "balance and friendship objectives are preferences, not mandatory feasibility rules; "
                "change their priority/weight instead. Read the active rules before selecting another target."
            )
        changes = {}
        if args.hard is not None:
            changes["hard"] = args.hard
        if args.active is not None:
            changes["active"] = args.active
        next_args = dict(target.args)
        numeric_change = False
        if args.min_per_class is not None or args.max_per_class is not None:
            if target.type != "capacity":
                raise ToolArgumentError("min/max can only modify a capacity rule")
            if args.min_per_class is not None:
                next_args["min"] = args.min_per_class
            if args.max_per_class is not None:
                next_args["max"] = args.max_per_class
            if next_args.get("min") is not None and next_args.get("max") is not None and next_args["min"] > next_args["max"]:
                raise ToolArgumentError("minimum cannot be greater than maximum")
            numeric_change = True
        if args.weight is not None:
            if target.type != "balance":
                raise ToolArgumentError("weight can only modify a balance preference")
            next_args["weight"] = args.weight
            numeric_change = True
        if args.weight_mutual is not None or args.weight_two_friends is not None:
            if target.type != "friendship_objective":
                raise ToolArgumentError("friendship weights can only modify the friendship objective")
            if args.weight_mutual is not None:
                next_args["weight_mutual"] = args.weight_mutual
            if args.weight_two_friends is not None:
                next_args["weight_two_friends"] = args.weight_two_friends
            numeric_change = True
        if numeric_change:
            changes["args"] = next_args
            # The counselor-facing rationale is required to state the exact
            # new interpretation, so it also prevents a stale numeric label.
            changes["label_hebrew"] = args.rationale_hebrew
        if not changes:
            raise ToolArgumentError("the modification did not specify any change")
        effective_changes = {
            key: value for key, value in changes.items() if getattr(target, key) != value
        }
        if not effective_changes:
            raise ToolArgumentError(
                "the requested setting is already active; do not create a no-op proposal. "
                "Continue with the rest of the counselor's request, including a requested solver run."
            )
        changes = effective_changes
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


def _process_chat_message(req: ChatMessageRequest, x_session_id: str, on_text_delta=None, on_event=None):
    sess = store.get_or_create(x_session_id)
    df = sess.mapped_df
    mentions: list[Mention] = []

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

    # The approval card and chat are two controls over the same project
    # state.  A counselor who types "yes" while an exact proposal is visibly
    # pending has explicitly approved it; do not send that answer back to the
    # model where it may repeat the preceding experiment.
    if sess.pending_proposal is not None and _accepts_active_recommendation(req.message):
        return _confirmed_chat_response(confirm_pending_proposal(x_session_id))

    cfg, constraints = build_solver_inputs(sess)
    has_result = sess.opt_result is not None and sess.opt_result.is_feasible and sess.adjustment_state is not None
    class_sizes = None
    if has_result:
        sizes = [0] * cfg.num_classes
        for cls in sess.adjustment_state.assignment.values():
            if 0 <= cls < cfg.num_classes:
                sizes[cls] += 1
        class_sizes = sizes

    recommendation = sess.active_recommendation
    if recommendation and _accepts_active_recommendation(req.message):
        if recommendation.get("kind") == "capacity_change_batch":
            if not _requests_entire_recommendation_package(req.message):
                reply = "האם לאשר רק את השינוי הראשון, או את כל חבילת הריכוכים שהצגתי?"
                sess.chat_history.append({"role": "assistant", "content": reply})
                store.save(sess)
                return {
                    "reply": reply,
                    "pending_proposal": None,
                    "steps": [],
                    "state_changed": False,
                    "solver_run_requested": False,
                    "suggestions": [],
                    "result_state": sess.result_state(),
                }
            try:
                proposal = _build_capacity_package_proposal(sess, recommendation)
            except ToolArgumentError as exc:
                sess.active_recommendation = None
                reply = f"חבילת השינויים כבר אינה עדכנית ({exc}). אבצע בדיקת היתכנות חדשה לפני שינוי כלשהו."
                sess.chat_history.append({"role": "assistant", "content": reply})
                store.save(sess)
                return {
                    "reply": reply,
                    "pending_proposal": None,
                    "steps": [],
                    "state_changed": False,
                    "solver_run_requested": False,
                    "suggestions": [],
                    "result_state": sess.result_state(),
                }
            # "Apply the whole package" is explicit approval of the exact
            # package just presented. Stage it through the same authoritative
            # confirmation path so history and stale-result handling remain
            # identical to clicking the approval card.
            sess.pending_proposal = proposal
            sess.active_recommendation = None
            return _confirmed_chat_response(confirm_pending_proposal(x_session_id))
        target = next(
            (item for item in sess.constraints if item.id == recommendation.get("constraint_id") and item.active),
            None,
        )
        if recommendation.get("kind") == "capacity_change" and target is not None and target.type == "capacity":
            new_min = int(recommendation["min"])
            new_max = int(recommendation["max"])
            next_args = dict(target.args)
            next_args.update({"min": new_min, "max": new_max})
            if next_args.get("group", {}).get("kind") == "all":
                next_args["size_diff"] = 0 if new_min == new_max else next_args.get("size_diff", 0)
            group = next_args.get("group", {})
            if group.get("kind") == "all":
                new_label = (
                    f"גודל כיתה בדיוק {new_min}"
                    if new_min == new_max
                    else f"גודל כיתה בין {new_min} ל-{new_max}"
                )
            else:
                new_label = capacity_range_label_hebrew(group.get("field", target.label_hebrew), new_min, new_max)
            summary = (
                f"הבנתי: לעדכן את '{target.label_hebrew}' מ-{target.args.get('min')}–{target.args.get('max')} "
                f"ל-{new_min}–{new_max}. זה השינוי שנבדק בניסוי; אף כלל חובה אחר לא ישתנה. לאשר?"
            )
            proposal = PendingProposal(
                kind="modify",
                summary_hebrew=summary,
                target_constraint_id=target.id,
                changes={"args": next_args, "label_hebrew": new_label},
                evidence={"basis": "measured_trial", "trial": recommendation.get("evidence")},
            )
            sess.pending_proposal = proposal
            sess.active_recommendation = None
            if recommendation.get("approval_ready"):
                return _confirmed_chat_response(confirm_pending_proposal(x_session_id))
            sess.chat_history.append({"role": "assistant", "content": summary})
            store.save(sess)
            return {
                "reply": summary,
                "pending_proposal": asdict(proposal),
                "steps": [],
                "state_changed": False,
                "solver_run_requested": False,
                "suggestions": [],
                "result_state": sess.result_state(),
            }
        if recommendation.get("kind") in {"balance_priority_change", "friendship_priority_change"} and target is not None:
            expected_type = "balance" if recommendation["kind"] == "balance_priority_change" else "friendship_objective"
            if target.type == expected_type:
                next_args = dict(target.args)
                changed_parts = []
                for key in ("weight", "weight_mutual", "weight_two_friends"):
                    if key in recommendation:
                        old_value = target.args.get(key)
                        new_value = recommendation[key]
                        next_args[key] = new_value
                        changed_parts.append(f"{key}: {old_value}→{new_value}")
                summary = (
                    f"הבנתי: לעדכן את העדיפות של '{target.label_hebrew}' ({', '.join(changed_parts)}). "
                    "זה השינוי שנבדק בניסוי; כל כללי החובה יישארו ללא שינוי. לאשר?"
                )
                proposal = PendingProposal(
                    kind="modify",
                    summary_hebrew=summary,
                    target_constraint_id=target.id,
                    changes={"args": next_args},
                    evidence={"basis": "measured_trial", "trial": recommendation.get("evidence")},
                )
                sess.pending_proposal = proposal
                sess.active_recommendation = None
                if recommendation.get("approval_ready"):
                    return _confirmed_chat_response(confirm_pending_proposal(x_session_id))
                sess.chat_history.append({"role": "assistant", "content": summary})
                store.save(sess)
                return {
                    "reply": summary,
                    "pending_proposal": asdict(proposal),
                    "steps": [],
                    "state_changed": False,
                    "solver_run_requested": False,
                    "suggestions": [],
                    "result_state": sess.result_state(),
                }
        # A stale recommendation must never be reconstructed against a
        # different rule. Clear it and let the normal agent investigate.
        sess.active_recommendation = None

    explicit_data_edit = _explicit_student_data_edit(req.message, mentions, sess) if df is not None else None
    if explicit_data_edit is not None:
        record = execute_read_tool("get_student_record", {"student": explicit_data_edit["student"]}, sess)
        try:
            proposal, summary = _build_proposal(
                "propose_student_data_edit",
                explicit_data_edit,
                sess,
                req.message,
            )
        except (ValidationError, ToolArgumentError) as exc:
            reply = f"לא הצלחתי להכין את תיקון הנתון בבטחה ({exc}). אפשר לציין את הערך המדויק?"
            sess.chat_history.append({"role": "assistant", "content": reply})
            store.save(sess)
            return {
                "reply": reply,
                "pending_proposal": None,
                "steps": [{"tool": "get_student_record", "ok": "error" not in record}],
                "state_changed": False,
                "solver_run_requested": False,
                "suggestions": [],
                "result_state": sess.result_state(),
            }
        sess.pending_proposal = proposal
        sess.chat_history.append({"role": "assistant", "content": summary})
        store.save(sess)
        return {
            "reply": summary,
            "pending_proposal": asdict(proposal),
            "steps": [{"tool": "get_student_record", "ok": "error" not in record}],
            "state_changed": False,
            "solver_run_requested": False,
            "suggestions": [],
            "result_state": sess.result_state(),
        }

    # Gather a whole-assignment evidence packet before the model answers the
    # most important analysis questions. Facts are guaranteed; interpretation
    # and conversational judgment remain with the LLM.
    prefetched_steps: list[dict] = []
    evidence_context = ""
    evidence_payload = None
    final_instruction = ""
    size_question = has_result and _asks_about_class_size_imbalance(req.message)
    broad_analysis = has_result and _asks_for_assignment_analysis(req.message)
    matched_for_reasoning = [m for m in mentions if m.status == "matched" and m.student_id is not None]
    version_question = has_result and len(matched_for_reasoning) == 1 and _asks_why_version_move(req.message)
    current_placement_question = (
        has_result and len(matched_for_reasoning) == 1 and _asks_why_current_placement(req.message)
    )
    requested_class_number = _requested_class_number(req.message)
    class_analysis_question = (
        has_result
        and not matched_for_reasoning
        and requested_class_number is not None
        and 1 <= requested_class_number <= cfg.num_classes
        and _asks_for_class_analysis(req.message)
    )
    data_analysis_question = df is not None and _asks_for_data_analysis(req.message)
    rule_feasibility_question = df is not None and _asks_for_rule_feasibility_analysis(req.message)
    if rule_feasibility_question:
        feasibility = execute_read_tool("analyze_rule_feasibility", {}, sess)
        active_rules = execute_read_tool("get_active_rules", {}, sess)
        prefetched_steps.extend(
            [
                {
                    "tool": "analyze_rule_feasibility",
                    "args": {},
                    "ok": "error" not in feasibility,
                    "result": feasibility,
                },
                {
                    "tool": "get_active_rules",
                    "args": {},
                    "ok": "error" not in active_rules,
                    "result": active_rules,
                },
            ]
        )
        recent_user_requirements = [
            item.get("content", "")
            for item in sess.chat_history[-8:]
            if item.get("role") == "user"
        ]
        evidence_payload = {
            "independent_rule_feasibility": feasibility,
            "authoritative_active_rules": active_rules,
            "recent_user_requirements": recent_user_requirements,
        }
        impossible_rules = feasibility.get("independently_impossible_rules", [])
        package_items = []
        for item in impossible_rules:
            relaxation = item.get("minimal_independent_relaxation") or {}
            if item.get("constraint_id") and relaxation:
                package_items.append(
                    {
                        "constraint_id": item["constraint_id"],
                        "min": relaxation.get("min"),
                        "max": relaxation.get("max"),
                        "evidence": item,
                    }
                )
        if package_items:
            sess.active_recommendation = {
                "kind": "capacity_change_batch",
                "items": package_items,
                "source_question": redacted,
                "evidence": feasibility,
            }
        final_instruction = (
            "ענה/י רק מן הראיות המספריות. פתח/י במספר כללי החובה שנמצאו בלתי אפשריים בפני עצמם. לכל אחד "
            "מהם הצג/י: מספר התלמידות בקבוצה, החשבון מול מספר הכיתות, והריכוך המזערי המדויק שמופיע תחת "
            "minimal_independent_relaxation. אין להשתמש ב'אולי', 'עלול להיות' או בניחוש. כל כלל שמופיע "
            "כ-independently_feasible חייב להיות מתואר כאפשרי בפני עצמו, בלי לטעון שהוא אפשרי בשילוב עם "
            "שאר הכללים. אם recent_user_requirements מזכיר כלל מספרי שאינו מופיע ב-authoritative_active_rules, "
            "ציין/י במפורש שהוא עדיין לא פעיל ולכן לא נבדק—אל תעמיד/י פנים שהוחל. הצע/י את קבוצת השינויים "
            "המזערית, אבל אל תשנה/י אף כלל ואל תקרא/י לכלי כתיבה. סיים/י בבקשת אישור ממוקדת לשינוי הראשון "
            "או לכל החבילה. העדף/י פסקאות ורשימה קצרה; אל תחזור/י על כל כללי ההעדפה."
        )
    elif data_analysis_question:
        data_quality = execute_read_tool("analyze_data_quality", {}, sess)
        dataset_columns = execute_read_tool("get_dataset_columns", {}, sess)
        prefetched_steps.extend(
            [
                {
                    "tool": "analyze_data_quality",
                    "args": {},
                    "ok": "error" not in data_quality,
                    "result": data_quality,
                },
                {
                    "tool": "get_dataset_columns",
                    "args": {},
                    "ok": "error" not in dataset_columns,
                    "result": dataset_columns,
                },
            ]
        )
        evidence_payload = {
            "data_quality": data_quality,
            "dataset_structure": dataset_columns,
        }
        final_instruction = (
            "נתח/י את הקובץ עצמו, לא את איכות השיבוץ. פתח/י במספר שגיאות חוסמות ואזהרות, ואז ציין/י את "
            "הבעיות הספציפיות והיקפן. הבדל/י בין עמודה שלא קיימת, ערך חסר, ערך לא תקין ובקשת חברות שלא "
            "נפתרה. אם הערך הנכון אינו מופיע בראיות, אל תנחש/י אותו ואל תיצור/י הצעת שינוי; שאל/י שאלה ממוקדת "
            "אחת. אם אין בעיות, אמור/אמרי זאת במפורש והזכר/י רק מגבלת נתונים משמעותית אחת, אם קיימת. "
            "ענה/י בשניים או שלושה קטעים קצרים, ללא כותרות, הדגשות או רשימה ממוספרת, ובחר/י לכל היותר שלוש "
            "בעיות מהותיות. אל תציג/י נתון תקין כבעיה ואל תחזור/י על כל רשימת העמודות."
        )
    elif version_question:
        version_numbers = [int(value) for value in re.findall(r"(?:גרסה|version)\s*(\d+)", req.message, re.IGNORECASE)]
        version_by_number = {version.number: version for version in sess.assignment_versions}
        compare_args = {"student": sess.token_map.token_for(matched_for_reasoning[0].student_id)}
        if len(version_numbers) >= 2 and all(number in version_by_number for number in version_numbers[:2]):
            compare_args["from_version_id"] = version_by_number[version_numbers[0]].id
            compare_args["to_version_id"] = version_by_number[version_numbers[1]].id
        comparison = execute_read_tool("compare_student_versions", compare_args, sess)
        prefetched_steps.append(
            {
                "tool": "compare_student_versions",
                "args": compare_args,
                "ok": "error" not in comparison,
                "result": comparison,
            }
        )
        if "error" not in comparison:
            evidence_payload = comparison
            final_instruction = (
                "תאר/י מה השתנה בפועל בין שתי הגרסאות: הכיתה, מענה החברות, מדד האיזון הלימודי ובדיקת "
                "החזרה לכיתה הקודמת. חובה לומר במפורש שתצפית על שיפור במדד אינה הוכחה לסיבת המעבר, "
                "ושהגרסאות אינן מתעדות גורם יחיד לבחירת המנוע. אל תמציא/י שאופטימיזציה, חברות או איזון "
                "גרמו למעבר; הצג/י אותם כסיבה רק אם בדיקת החובה מוכיחה חסימה. זו השוואת גרסאות ולא ניסוי. "
                "אל תסיק/י מרמת הישגים 'תחרותיות', 'מנהיגות' או תכונה אנושית אחרת שאינה מופיעה בראיות."
            )
    elif current_placement_question:
        token = sess.token_map.token_for(matched_for_reasoning[0].student_id)
        placement = execute_read_tool("explain_student_placement", {"student": token}, sess)
        prefetched_steps.append(
            {
                "tool": "explain_student_placement",
                "args": {"student": token},
                "ok": "error" not in placement,
                "result": placement,
            }
        )
        alternative_trial = None
        if "error" not in placement and not placement.get("locked"):
            checks = placement.get("direct_move_checks") or []
            ranked_checks = sorted(
                checks,
                key=lambda check: (
                    not check.get("direct_move_preserves_hard_rules", False),
                    -int(check.get("mutual_friends_there", 0)),
                    -int(check.get("requested_friends_there", 0)),
                    int(check.get("class", 0)),
                ),
            )
            if ranked_checks:
                alternative_args = {"student": token, "class_number": ranked_checks[0]["class"]}
                alternative_trial = execute_simulation_tool("simulate_student_move", alternative_args, sess)
                prefetched_steps.append(
                    {
                        "tool": "simulate_student_move",
                        "args": alternative_args,
                        "ok": "error" not in alternative_trial,
                        "result": alternative_trial,
                    }
                )
        evidence_payload = {
            "verified_current_placement": placement,
            "measured_best_alternative_trial": alternative_trial,
        }
        final_instruction = (
            "הסבר/י קודם מה ידוע בפועל על השיבוץ הנוכחי של התלמידה: הכיתה, הקיבוע אם קיים, ומענה החברות. "
            "לאחר מכן הבדל/י בין חלופות שנחסמו על ידי כלל חובה לבין חלופות שהיו אפשריות ולכן מוכיחות שהכיתה "
            "הנוכחית לא הייתה האפשרות היחידה. אם measured_best_alternative_trial קיים, פרט/י את החלופה שנבדקה, "
            "את השפעתה על התלמידה ואת השינויים הכלליים בחברות ובאיזון הלימודי. אם נמצאו החלפות בטוחות, הצג/י "
            "את הטובה ביותר כאפשרות ולא כהמלצה אוטומטית. חובה לומר שאין תיעוד של גורם יחיד לבחירת המנוע, אלא אם "
            "קיבוע או כלל חובה מוכיחים אותו. אל תמציא/י סיבתיות מתוך שיפור במדד בלבד."
        )
    elif class_analysis_question and not size_question:
        class_profile = execute_read_tool(
            "get_class_composition",
            {"class_number": requested_class_number},
            sess,
        )
        whole_analysis = execute_read_tool("analyze_assignment_quality", {}, sess)
        prefetched_steps.extend(
            [
                {
                    "tool": "get_class_composition",
                    "args": {"class_number": requested_class_number},
                    "ok": "error" not in class_profile,
                    "result": class_profile,
                },
                {
                    "tool": "analyze_assignment_quality",
                    "args": {},
                    "ok": "error" not in whole_analysis,
                    "result": whole_analysis,
                },
            ]
        )
        evidence_payload = {
            "requested_class": requested_class_number,
            "class_profile": class_profile,
            "all_class_profiles": whole_analysis.get("class_profiles"),
            "ranked_assignment_findings": whole_analysis.get("diagnostic_findings"),
            "hard_rule_compliance": whole_analysis.get("hard_rule_compliance"),
            "metric_definitions": whole_analysis.get("metric_definitions"),
        }
        final_instruction = (
            f"נתח/י את כיתה {requested_class_number} ביחס לכיתות האחרות, לא בפני עצמה. זהה/י לכל היותר שלושה "
            "הבדלים משמעותיים ומספריים בגודל, בהרכב, בהישגים או בחברות. אל תכנה/י הבדל הפרה אם כללי החובה "
            "מתקיימים. הבדל/י בין ממצא, כלל פעיל וסיבה שלא הוכחה. אם יש בעיה משמעותית, הצע/י בדיקה אחת "
            "ממוקדת שתוכל לזהות תיקון; אל תציע/י העברת תלמידה מסוימת בלי תוצאת סימולציה שתומכת בכך."
        )
    elif size_question or broad_analysis:
        if size_question:
            sess.active_recommendation = None
        analysis_result = execute_read_tool("analyze_assignment_quality", {}, sess)
        simulation_result = None
        move_options_result = None
        diagnostic_trial_result = None
        prefetched_steps.append(
            {"tool": "analyze_assignment_quality", "args": {}, "ok": "error" not in analysis_result, "result": analysis_result}
        )
        if size_question and "error" not in analysis_result:
            metrics = analysis_result.get("measured_current_state") or {}
            size_rule = analysis_result.get("class_size_rule") or {}
            if metrics.get("class_size_spread", 0) > 0:
                move_options_result = execute_simulation_tool("find_class_size_balance_moves", {}, sess)
                prefetched_steps.append(
                    {
                        "tool": "find_class_size_balance_moves",
                        "args": {},
                        "ok": "error" not in move_options_result,
                        "result": move_options_result,
                    }
                )
            target_min = len(df) // cfg.num_classes
            target_max = -(-len(df) // cfg.num_classes)
            already_tight = size_rule.get("min") == target_min and size_rule.get("max") == target_max
            if metrics.get("class_size_spread", 0) > 0 and size_rule.get("id") and not already_tight:
                simulation_args = {"constraint_id": size_rule["id"], "min": target_min, "max": target_max}
                simulation_result = execute_simulation_tool("simulate_capacity_change", simulation_args, sess)
                prefetched_steps.append(
                    {
                        "tool": "simulate_capacity_change",
                        "args": simulation_args,
                        "ok": "error" not in simulation_result,
                        "result": simulation_result,
                    }
                )
                if simulation_result.get("feasible") is True:
                    sess.active_recommendation = {
                        "kind": "capacity_change",
                        "constraint_id": size_rule["id"],
                        "min": target_min,
                        "max": target_max,
                        "source_question": redacted,
                        "evidence": simulation_result,
                    }
        elif broad_analysis and "error" not in analysis_result:
            findings = analysis_result.get("diagnostic_findings", [])
            suggested_test = findings[0].get("suggested_test") if findings else None
            if suggested_test:
                simulation_name = suggested_test.get("tool")
                simulation_args = {key: value for key, value in suggested_test.items() if key != "tool"}
                if simulation_name and is_simulation_tool(simulation_name):
                    diagnostic_trial_result = execute_simulation_tool(simulation_name, simulation_args, sess)
                    prefetched_steps.append(
                        {
                            "tool": simulation_name,
                            "args": simulation_args,
                            "ok": "error" not in diagnostic_trial_result,
                            "result": diagnostic_trial_result,
                        }
                    )
                    if diagnostic_trial_result.get("feasible") is True and diagnostic_trial_result.get("after", {}).get("violations") == 0:
                        if simulation_name == "simulate_balance_priority":
                            sess.active_recommendation = {
                                "kind": "balance_priority_change",
                                "constraint_id": simulation_args["constraint_id"],
                                "weight": simulation_args["weight"],
                                "source_question": redacted,
                                "evidence": diagnostic_trial_result,
                            }
                        elif simulation_name == "simulate_friendship_priority":
                            sess.active_recommendation = {
                                "kind": "friendship_priority_change",
                                "constraint_id": simulation_args["constraint_id"],
                                **{
                                    key: simulation_args[key]
                                    for key in ("weight_mutual", "weight_two_friends")
                                    if key in simulation_args
                                },
                                "source_question": redacted,
                                "evidence": diagnostic_trial_result,
                            }
                        elif simulation_name == "simulate_capacity_change":
                            sess.active_recommendation = {
                                "kind": "capacity_change",
                                "constraint_id": simulation_args["constraint_id"],
                                "min": simulation_args["min"],
                                "max": simulation_args["max"],
                                "source_question": redacted,
                                "evidence": diagnostic_trial_result,
                            }
        if size_question and "error" not in analysis_result:
            metrics = analysis_result.get("measured_current_state") or {}
            size_rule = analysis_result.get("class_size_rule") or {}
            trial = simulation_result or {}
            evidence_payload = {
                "verified_current_assignment": {
                    "class_sizes": metrics.get("class_sizes"),
                    "size_spread": metrics.get("class_size_spread"),
                    "hard_violations": metrics.get("violations_count"),
                    "solver_status": metrics.get("solver_status"),
                },
                "verified_configuration": {
                    "active_size_rule": size_rule,
                    "meaning": (
                        "כלל החובה מאפשר כל גודל בתוך המינימום והמקסימום. שוויון בגודל הכיתות אינו יעד "
                        f"אופטימיזציה, ולכן כל גודל בטווח {size_rule.get('min')}–{size_rule.get('max')} חוקי."
                    ),
                    "other_active_objectives": analysis_result.get("active_optimization_priorities"),
                },
                "causality_limit": (
                    "זה מוכיח מדוע פער 13/11 היה מותר. זה לא מוכיח שחברות, הישגים או יעד אחר גרמו לחלוקה "
                    "המסוימת. מותר להזכיר אותם רק כיעדים פעילים או כפשרות שנמדדו, לא כסיבה מוכחת."
                ),
                "completed_counterfactual_trial": {
                    "already_completed": simulation_result is not None,
                    "change_tested": trial.get("change"),
                    "feasible": trial.get("feasible"),
                    "solver_status": trial.get("solver_status"),
                    "before": trial.get("before"),
                    "after": trial.get("after"),
                    "deltas": trial.get("deltas"),
                    "detail": trial.get("detail"),
                    "caveat": trial.get("caveat"),
                },
                "verified_direct_move_options": move_options_result,
            }
            final_instruction = (
                "בתשובה חייבים להופיע ארבעה דברים, בניסוח שיחתי שלך: (1) הטווח הפעיל המדויק "
                f"{size_rule.get('min')}–{size_rule.get('max')} והעובדה "
                "ששוויון בגודל אינו כרגע יעד; (2) אמירה כנה שאי אפשר להוכיח מהתוצאה לבדה איזה יעד גרם "
                "לחלוקה המסוימת; (3) תוצאת הניסוי שכבר הסתיים, כולל הגדלים לפני ואחרי; (4) כל שינוי שנמדד "
                "בחברות ובפער הלימודי, גם אם הוא אפס או שלילי. אין לומר שהבדיקה עומדת להתחיל. בסוף שאל/י "
                "אם להציע את כלל הגודל המדויק שנבדק; אל תחיל/י אותו עדיין. אם יש מועמדות תחת "
                "verified_direct_move_options, ציין/י את ההעברה הישירה המדורגת ראשונה ואת השינויים המדודים "
                "שלה בחברות ובפער הלימודי. הבדל/י בינה לבין הניסוי המלא. אם לא נמצאה העברה בטוחה, אמר/י "
                "שכל ההעברות הישירות שנבדקו הפרו כלל חובה או לא שיפרו את פער הגדלים."
            )
        else:
            evidence_payload = {
                "assignment_analysis": analysis_result,
                "completed_targeted_trial": diagnostic_trial_result,
            }
            final_instruction = (
                "נתח/י את השיבוץ כמכלול ולא כרשימת מדדים גנרית. חובה: (1) לומר תחילה אם כל כללי החובה "
                "מתקיימים; (2) לזהות לכל היותר שלושה פערים משמעותיים מתוך class_profiles ולכמת אותם; "
                "(3) לפרש כל מדד רק לפי metric_definitions — בפרט academic_level_spread אינו טווח ציונים; "
                "(4) להבדיל בין פער שנמדד, כלל או עדיפות פעילים, וסיבה שטרם הוכחה; (5) להתחשב בכך ש-FEASIBLE "
                "אינו הוכחת אופטימליות; (6) להציע בדיקת נגד ממוקדת אחת שהכי כדאי להריץ בהמשך. אל תגיד/י "
                "שהכללים 'נכשלו' אם hard_rule_compliance מראה שאין חריגות. התחל/י מהממצאים המדורגים תחת "
                "diagnostic_findings ולא מסריקה גנרית של הטבלה. אם completed_targeted_trial קיים, הצג/י אותו כניסוי "
                "שכבר הסתיים: מה נבדק, מה השתפר, מה הורע והאם כל כללי החובה נשמרו. אל תציע/י להריץ שוב את אותו ניסוי."
            )
        evidence_context = (
            "\n\nEVIDENCE ALREADY GATHERED FOR THIS QUESTION:\n"
            + json.dumps(evidence_payload, ensure_ascii=False, default=str)
            + "\nReason over this evidence in a natural Hebrew conversation. Do not repeat these tool calls. "
            "Distinguish what the assignment proves, what the configuration allowed, and what a trial measured. "
            "Do not use a canned template and do not invent an exact solver cause. "
            + final_instruction
            + " Answer the question and invite the next decision; do not call a write tool unless the counselor "
            "explicitly asked to make a change."
        )

    system_prompt = build_system_prompt(
        build_roster_context(df),
        build_constraints_context(constraints),
        build_result_context(has_result, cfg.num_classes, class_sizes, stale=sess.result_state()["is_stale"]),
        build_dataset_columns_context(sess.dataset_schema),
        build_planning_context(df is None, cfg.num_classes, sess.data_requirements),
        build_project_memory_context(sess.user_notes, sess.decision_history),
    ) + evidence_context

    try:
        if (
            size_question
            or broad_analysis
            or version_question
            or current_placement_question
            or class_analysis_question
            or data_analysis_question
            or rule_feasibility_question
        ) and evidence_payload is not None:
            turn = run_grounded_analysis_turn(
                redacted,
                evidence_payload,
                final_instruction,
                on_text_delta=on_text_delta,
            )
        else:
            turn = run_agent_turn(
                sess,
                system_prompt,
                sess.chat_history,
                validate_write=lambda call: _build_proposal(call.name, call.arguments, sess, req.message),
                on_text_delta=on_text_delta,
                on_event=on_event,
            )
    except LLMNotConfiguredError as e:
        # Don't persist the user turn without a matching reply -- leave the
        # history as it was before this call and surface a clear error.
        sess.chat_history.pop()
        raise HTTPException(status_code=503, detail=str(e))

    if prefetched_steps:
        turn.steps = prefetched_steps + turn.steps
        if on_event is not None:
            for step in prefetched_steps:
                on_event({"type": "tool", "tool": step["tool"], "ok": step["ok"]})

    # Normalize model-selected simulations into the same structured memory as
    # deterministic diagnostics.  This must happen before the answer is saved
    # so the very next short follow-up can apply the exact measured change.
    _remember_successful_simulation_recommendation(sess, turn.steps, turn.text or "")

    # What the agent looked at, so the counselor can see it worked rather
    # than just waited. Read tools only -- writes are shown as the proposal.
    steps = [{"tool": s["tool"], "ok": s["ok"]} for s in turn.steps]
    solver_run_requested = any(s["tool"] == "request_solver_run" and s["ok"] for s in turn.steps)
    solver_run_count = next(
        (int(s["args"].get("alternatives", 1)) for s in turn.steps if s["tool"] == "request_solver_run" and s["ok"]),
        1,
    )
    explicit_run, explicit_count = _explicit_solver_request(req.message)
    model_undercounted_explicit_options = solver_run_requested and explicit_count == 3 and solver_run_count != 3
    if model_undercounted_explicit_options:
        # The user's explicit request wins over an under-specified model tool
        # call. This is the deterministic safety net for "כמה אפשרויות": it
        # must produce three real solver runs, not a prose promise plus one.
        solver_run_count = 3
    # A planning tool changed persisted state (checklist entry, class
    # count). The UI uses this to re-read the panels rather than poll --
    # "the rules list updates live" is this flag plus a refresh key.
    state_changed = turn.state_changed

    if turn.write_call is not None:
        if turn.write_call.name == "modify_constraint":
            raw = turn.write_call.arguments
            target = next((item for item in sess.constraints if item.id == raw.get("constraint_id")), None)
            has_friendship_weight = raw.get("weight_mutual") is not None or raw.get("weight_two_friends") is not None
            already_tested = any(
                item.get("tool") == "simulate_friendship_priority" and item.get("ok") for item in turn.steps
            )
            if target is not None and target.type == "friendship_objective" and has_friendship_weight and not already_tested:
                simulation_args = {"constraint_id": target.id}
                for key in ("weight_mutual", "weight_two_friends"):
                    if raw.get(key) is not None:
                        simulation_args[key] = raw[key]
                evidence = execute_simulation_tool("simulate_friendship_priority", simulation_args, sess)
                simulated_step = {
                    "tool": "simulate_friendship_priority",
                    "args": simulation_args,
                    "ok": "error" not in evidence,
                    "result": evidence,
                }
                turn.steps.append(simulated_step)
                steps.append({"tool": "simulate_friendship_priority", "ok": simulated_step["ok"]})
                if on_event is not None:
                    on_event({"type": "tool", "tool": "simulate_friendship_priority", "ok": simulated_step["ok"]})
                measured = _proposal_from_friendship_simulation(req.message, turn.steps, sess)
                if measured is not None:
                    proposal, summary = measured
                    sess.pending_proposal = proposal
                    sess.chat_history.append({"role": "assistant", "content": summary})
                    store.save(sess)
                    return {
                        "reply": summary,
                        "pending_proposal": asdict(proposal),
                        "steps": steps,
                        "state_changed": state_changed,
                        "solver_run_requested": False,
                        "suggestions": [],
                    }
                reply = "בדיקת הניסיון לא אישרה את שינוי העדיפות, ולכן לא יצרתי שינוי לאישור."
                sess.chat_history.append({"role": "assistant", "content": reply})
                store.save(sess)
                return {
                    "reply": reply,
                    "pending_proposal": None,
                    "steps": steps,
                    "state_changed": state_changed,
                    "solver_run_requested": False,
                    "suggestions": [],
                }
        try:
            proposal, summary = _build_proposal(turn.write_call.name, turn.write_call.arguments, sess, req.message)
        except (ValidationError, ToolArgumentError) as e:
            reply = f"לא הצלחתי לפרש את הבקשה כראוי ({e}). אפשר לנסח אחרת?"
            sess.chat_history.append({"role": "assistant", "content": reply})
            store.save(sess)
            return {"reply": reply, "pending_proposal": None, "steps": steps, "state_changed": state_changed, "solver_run_requested": False, "suggestions": []}

        if (
            proposal.kind == "assignment_action"
            and proposal.action in {"move_student", "set_student_lock"}
            and _message_requests_rerun(req.message)
        ):
            proposal.action_args["rerun_after"] = True
            summary = summary.rstrip() + " לאחר האישור אריץ את השיבוץ מחדש ואשמור את הקיבוע."

        sess.pending_proposal = proposal
        sess.chat_history.append({"role": "assistant", "content": summary})
        store.save(sess)
        return {"reply": summary, "pending_proposal": asdict(proposal), "steps": steps, "state_changed": state_changed, "solver_run_requested": False, "suggestions": []}

    simulated_proposal = _proposal_from_friendship_simulation(req.message, turn.steps, sess)
    if simulated_proposal is not None:
        proposal, summary = simulated_proposal
        sess.pending_proposal = proposal
        sess.chat_history.append({"role": "assistant", "content": summary})
        store.save(sess)
        return {
            "reply": summary,
            "pending_proposal": asdict(proposal),
            "steps": steps,
            "state_changed": state_changed,
            "solver_run_requested": False,
            "suggestions": [],
        }

    if _explicit_friendship_priority_proposal(req.message):
        objective = next((item for item in sess.constraints if item.type == "friendship_objective" and item.active), None)
        if objective is not None:
            simulation_args = {
                "constraint_id": objective.id,
                "weight_two_friends": float(objective.args.get("weight_two_friends", 1)) + 2,
            }
            evidence = execute_simulation_tool("simulate_friendship_priority", simulation_args, sess)
            simulated_step = {
                "tool": "simulate_friendship_priority",
                "args": simulation_args,
                "ok": "error" not in evidence,
                "result": evidence,
            }
            turn.steps.append(simulated_step)
            steps.append({"tool": "simulate_friendship_priority", "ok": simulated_step["ok"]})
            if on_event is not None:
                on_event({"type": "tool", "tool": "simulate_friendship_priority", "ok": simulated_step["ok"]})
            measured = _proposal_from_friendship_simulation(req.message, turn.steps, sess)
            if measured is not None:
                proposal, summary = measured
                sess.pending_proposal = proposal
                sess.chat_history.append({"role": "assistant", "content": summary})
                store.save(sess)
                return {
                    "reply": summary,
                    "pending_proposal": asdict(proposal),
                    "steps": steps,
                    "state_changed": state_changed,
                    "solver_run_requested": False,
                    "suggestions": [],
                }

    version_explanation = None if version_question else _grounded_student_version_explanation(turn.steps)
    placement_explanation = None if current_placement_question else _grounded_student_explanation(turn.steps)
    matched_mentions = [mention for mention in mentions if mention.status == "matched" and mention.student_id is not None]
    if (
        version_explanation is None
        and placement_explanation is None
        and not current_placement_question
        and has_result
        and len(matched_mentions) == 1
        and _asks_why_current_placement(req.message)
    ):
        # Tool choice is model-variable. A current-placement question must
        # never degrade to generic prose merely because the model first
        # attempted a version comparison in a one-version project.
        token = sess.token_map.token_for(matched_mentions[0].student_id)
        evidence = execute_read_tool("explain_student_placement", {"student": token}, sess)
        fallback_step = {
            "tool": "explain_student_placement",
            "args": {"student": token},
            "ok": "error" not in evidence,
            "result": evidence,
        }
        turn.steps.append(fallback_step)
        steps.append({"tool": fallback_step["tool"], "ok": fallback_step["ok"]})
        if on_event is not None:
            on_event({"type": "tool", "tool": fallback_step["tool"], "ok": fallback_step["ok"]})
        placement_explanation = _grounded_student_explanation(turn.steps)

    reply = version_explanation or placement_explanation or turn.text or ""
    if not solver_run_requested and explicit_run:
        solver_run_requested = True
        solver_run_count = explicit_count
        steps.append({"tool": "request_solver_run", "ok": True})
        option_text = "שלוש חלופות" if explicit_count == 3 else "חלופה אחת"
        reply = (
            f"הבקשה מוכנה: אפיק {option_text} לפי כל כללי החובה הפעילים, "
            "ואציג את התוצאות וההבדלים ביניהן כשההרצה תסתיים."
        )
    elif model_undercounted_explicit_options:
        reply = (
            "הבקשה מוכנה: אפיק שלוש חלופות אמיתיות לפי כל כללי החובה הפעילים, "
            "ואציג את התוצאות, ההבדלים ומספר התלמידות שעברו כשההרצה תסתיים."
        )
    sess.chat_history.append({"role": "assistant", "content": reply})
    store.save(sess)
    return {
        "reply": _display_student_names(reply, sess),
        "pending_proposal": None,
        "steps": steps,
        "state_changed": state_changed,
        "solver_run_requested": solver_run_requested,
        "solver_run_count": max(1, min(3, solver_run_count)),
        "suggestions": _suggested_actions(sess, steps),
        "result_state": sess.result_state(),
    }


@router.post("/api/chat/message")
def send_chat_message(req: ChatMessageRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return _display_value(_process_chat_message(req, x_session_id), sess)


def _ndjson_response(run):
    def generate():
        events: queue.Queue = queue.Queue()
        finished = object()

        def emit(payload: dict) -> None:
            events.put(payload)

        def work() -> None:
            try:
                result = run(emit)
                emit({"type": "result", "data": result})
            except HTTPException as exc:
                emit({"type": "error", "status": exc.status_code, "detail": exc.detail})
            except Exception:
                logger.exception("streaming chat worker failed")
                emit({"type": "error", "status": 500, "detail": "שגיאה במהלך תשובת העוזר."})
            finally:
                events.put(finished)

        yield json.dumps({"type": "status", "status": "thinking"}, ensure_ascii=False) + "\n"
        threading.Thread(target=work, daemon=True).start()
        while True:
            event = events.get()
            if event is finished:
                break
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/chat/message/stream")
def stream_chat_message(req: ChatMessageRequest, x_session_id: str = Header(...)):
    """NDJSON stream of model deltas/tool activity plus one final response."""
    def run(emit):
        sess = store.get_or_create(x_session_id)
        display_stream = _StudentNameStream(sess, lambda text: emit({"type": "delta", "text": text}))
        try:
            result = _process_chat_message(req, x_session_id, on_text_delta=display_stream.feed, on_event=emit)
        finally:
            display_stream.flush()
        return _display_value(result, sess)

    return _ndjson_response(run)


def _continue_after_solver(req: SolverResultFollowupRequest, x_session_id: str, on_text_delta=None, on_event=None):
    """Resume the conversation after requested solver runs, using read-only tools."""
    sess = store.get_or_create(x_session_id)
    require(sess.adjustment_state, "No successful assignment is available to analyze.")
    cfg, constraints = build_solver_inputs(sess)
    sizes = [0] * cfg.num_classes
    for cls in sess.adjustment_state.assignment.values():
        if 0 <= cls < cfg.num_classes:
            sizes[cls] += 1

    system_prompt = build_system_prompt(
        build_roster_context(sess.mapped_df),
        build_constraints_context(constraints),
        build_result_context(True, cfg.num_classes, sizes, stale=sess.result_state()["is_stale"]),
        build_dataset_columns_context(sess.dataset_schema),
        build_planning_context(False, cfg.num_classes, sess.data_requirements),
        build_project_memory_context(sess.user_notes, sess.decision_history),
    ) + (
        "\n\nThe solver run requested by the counselor has just completed. This is a read-only continuation turn. "
        "Call get_assignment_versions and any other read tools needed, then continue the original conversation "
        "with a concise factual summary. Compare alternatives when present and make a recommendation only from "
        "measured results. Never expose opaque version ids; refer only to visible version numbers. If no student "
        "submitted friendship requests, say that friendship quality cannot be measured and never describe zero "
        "percentages as failed or unmet requests; in Hebrew use the unambiguous wording 'לא הוזנו בקשות חברות'. "
        "If the options are equivalent on reported metrics, explicitly "
        "say there is no measured quality reason to prefer one; keeping the current option only avoids another "
        "change. Summarize a size list as a natural range instead of printing a raw array. Do not repeat every "
        "metric already visible in the structured comparison. Do not mention an individual student unless that "
        "student's move or lock is one of the solver run changes being summarized. Use one short paragraph "
        "without headings, bold text, or a numbered list. Do not request another solver run in this turn. Continue "
        "to answer in Hebrew."
    )
    known_ids = {version.id for version in sess.assignment_versions}
    requested = [version_id for version_id in req.version_ids if version_id in known_ids]
    comparison_ids = list(requested)
    baseline_id = None
    first_requested_index = next(
        (index for index, version in enumerate(sess.assignment_versions) if requested and version.id == requested[0]),
        None,
    )
    if first_requested_index is not None and first_requested_index > 0:
        baseline_id = sess.assignment_versions[first_requested_index - 1].id
    if len(comparison_ids) == 1:
        current_index = next(
            (index for index, version in enumerate(sess.assignment_versions) if version.id == comparison_ids[0]),
            None,
        )
        if current_index is not None and current_index > 0:
            comparison_ids.insert(0, sess.assignment_versions[current_index - 1].id)
    internal_message = {
        "role": "user",
        "content": (
            "[Internal system event] Solver runs completed. Versions created in response to the last request: "
            + (", ".join(requested) if requested else "the current version")
            + ". Analyze the actual results and continue the dialogue with the counselor."
        ),
    }
    try:
        turn = run_agent_turn(
            sess,
            system_prompt,
            [*sess.chat_history, internal_message],
            tools_override=build_read_tool_definitions(),
            on_text_delta=on_text_delta,
            on_event=on_event,
        )
    except LLMNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))

    reply = _grounded_solver_comparison(sess, comparison_ids, baseline_id=baseline_id) or turn.text or ""
    sess.chat_history.append({"role": "assistant", "content": reply})
    store.save(sess)
    steps = [{"tool": step["tool"], "ok": step["ok"]} for step in turn.steps]
    return {"reply": _display_student_names(reply, sess), "steps": steps, "suggestions": _suggested_actions(sess, steps)}


@router.post("/api/chat/solver-result")
def continue_after_solver(req: SolverResultFollowupRequest, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return _display_value(_continue_after_solver(req, x_session_id), sess)


@router.post("/api/chat/solver-result/stream")
def stream_after_solver(req: SolverResultFollowupRequest, x_session_id: str = Header(...)):
    def run(emit):
        sess = store.get_or_create(x_session_id)
        display_stream = _StudentNameStream(sess, lambda text: emit({"type": "delta", "text": text}))
        try:
            result = _continue_after_solver(req, x_session_id, on_text_delta=display_stream.feed, on_event=emit)
        finally:
            display_stream.flush()
        return _display_value(result, sess)

    return _ndjson_response(run)


@router.post("/api/chat/confirm")
def confirm_pending_proposal(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    proposal = sess.pending_proposal
    if proposal is None:
        raise HTTPException(status_code=409, detail="אין הצעה ממתינה לאישור.")

    decision_summary = proposal.summary_hebrew
    solver_run_requested = False
    confirmation_message = "אושר ועודכן ברשימת הכללים."
    rules_changed = False
    if proposal.kind == "propose":
        constraint = Constraint(**proposal.constraint)
        sess.constraints.append(constraint)
        result = asdict(constraint)
        rules_changed = True
    elif proposal.kind == "modify":
        batch = (proposal.changes or {}).get("batch")
        if isinstance(batch, list):
            # Validate every target before touching any of them. This makes
            # the package atomic: a stale/missing rule aborts the whole edit.
            resolved = []
            for item in batch:
                target = next((c for c in sess.constraints if c.id == item.get("constraint_id")), None)
                changes = item.get("changes")
                if target is None or not isinstance(changes, dict):
                    sess.pending_proposal = None
                    store.save(sess)
                    raise HTTPException(
                        status_code=409,
                        detail="חבילת השינויים כבר אינה עדכנית. לא שונה אף כלל; יש להריץ בדיקת היתכנות מחדש.",
                    )
                resolved.append((target, changes))
            for target, changes in resolved:
                for key, value in changes.items():
                    setattr(target, key, value)
            result = {
                "label_hebrew": f"{len(resolved)} כללי חובה עודכנו יחד",
                "constraints": [asdict(target) for target, _changes in resolved],
            }
            confirmation_message = (
                f"אושרו ועודכנו יחד {len(resolved)} כללי חובה. "
                "אני מריץ עכשיו שיבוץ מלא אחד עם כל החבילה שאישרת."
            )
        else:
            target = next((c for c in sess.constraints if c.id == proposal.target_constraint_id), None)
            if target is None:
                sess.pending_proposal = None
                store.save(sess)
                raise HTTPException(status_code=409, detail="הכלל כבר לא קיים.")
            for k, v in (proposal.changes or {}).items():
                setattr(target, k, v)
            result = asdict(target)
        rules_changed = True
        # A relaxation staged by the optimizer is the continuation of a
        # failed solve, not an isolated settings edit. Once the counselor
        # explicitly approves it, resume the workflow automatically. Chat-
        # proposed rule edits remain non-running unless the user asked to
        # solve, so confirming an ordinary proposal never starts surprise
        # work.
        evidence_basis = (proposal.evidence or {}).get("basis")
        if evidence_basis in {"measured_trial", "solver_conflict", "arithmetic_feasibility_package"}:
            remaining_arithmetic_conflicts = (
                analyze_feasibility(sess.mapped_df, sess.constraints, sess.run_config.num_classes).infeasible
                if sess.mapped_df is not None
                else []
            )
            solver_run_requested = not remaining_arithmetic_conflicts
            if remaining_arithmetic_conflicts:
                confirmation_message = (
                    f"השינוי אושר, אבל עדיין יש {len(remaining_arithmetic_conflicts)} כללי חובה "
                    "שאינם אפשריים לפי נתוני התלמידות. לא אריץ עדיין שיבוץ נוסף; קודם צריך לטפל בכולם."
                )
            elif evidence_basis != "arithmetic_feasibility_package":
                confirmation_message = "אושר ועודכן ברשימת הכללים. אני מריץ עכשיו את השיבוץ מחדש עם השינוי שאישרת."
    elif proposal.kind == "remove":
        sess.constraints = [c for c in sess.constraints if c.id != proposal.target_constraint_id]
        result = {"removed": proposal.target_constraint_id}
        rules_changed = True
    elif proposal.kind == "data_action":
        action_args = proposal.action_args or {}
        if proposal.action != "edit_student_data":
            raise HTTPException(status_code=500, detail="פעולת נתונים לא מוכרת.")
        try:
            old_value, new_value = apply_confirmed_student_edit(
                sess,
                int(action_args["student_id"]),
                str(action_args["field"]),
                action_args.get("value"),
            )
        except DataEditError as exc:
            sess.pending_proposal = None
            store.save(sess)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        solver_run_requested = bool(action_args.get("rerun_after"))
        result = {
            "action": proposal.action,
            "student_id": int(action_args["student_id"]),
            "field": str(action_args["field"]),
            "old_value": old_value,
            "new_value": new_value,
        }
        confirmation_message = (
            "הנתון עודכן בעותק העבודה ונרשם בהיסטוריה. קובץ המקור נשאר ללא שינוי, "
            "והשיבוץ הקודם הוסר מהמצב הפעיל משום שהוא התבסס על הנתון הישן."
        )
        if solver_run_requested:
            confirmation_message += " כעת אריץ שיבוץ חדש עם הנתון המתוקן."
    elif proposal.kind == "assignment_action":
        from .optimize import adjustment_move, restore_version

        action_args = proposal.action_args or {}
        if proposal.action in ("move_student", "set_student_lock"):
            locked_value = (
                bool(action_args.get("locked"))
                if proposal.action == "set_student_lock" or action_args.get("locked") is True
                else None
            )
            response = adjustment_move(
                MoveStudentRequest(
                    student_id=int(action_args["student_id"]),
                    new_class=int(action_args.get("new_class") or action_args["class_number"]),
                    locked=locked_value,
                ),
                x_session_id,
            )
            solver_run_requested = bool(action_args.get("rerun_after"))
            result = {"action": proposal.action, **response}
            violations_count = int((response.get("metrics") or {}).get("violations_count", 0) or 0)
            if violations_count > 0:
                confirmation_message = (
                    f"שינוי השיבוץ בוצע ונשמר כטיוטה, אבל כעת יש {violations_count} חריגות מכללי חובה. "
                    "לא ניתן לאשר את השיבוץ הסופי עד שהחריגות יתוקנו."
                )
            else:
                confirmation_message = "שינוי השיבוץ בוצע. כל כללי החובה עדיין מתקיימים."
            if solver_run_requested:
                confirmation_message += " כעת אריץ אופטימיזציה מחדש תוך שמירה על הקיבוע."
        elif proposal.action == "restore_version":
            response = restore_version(str(action_args["version_id"]), x_session_id)
            result = {"action": proposal.action, **response}
            confirmation_message = f"גרסה {action_args.get('version_number')} שוחזרה והיא שוב הגרסה הפעילה."
        else:
            raise HTTPException(status_code=500, detail="פעולת שיבוץ לא מוכרת.")
    else:
        raise HTTPException(status_code=500, detail="סוג הצעה לא מוכר.")

    if rules_changed:
        sess.mark_inputs_changed()
    sess.decision_history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "decision": "approved",
        "kind": proposal.kind,
        "summary": decision_summary,
        "result": result,
    })
    sess.decision_history = sess.decision_history[-100:]
    sess.pending_proposal = None
    sess.chat_history.append({"role": "assistant", "content": confirmation_message})
    store.save(sess)
    return {
        "applied": True,
        "result": result,
        "result_state": sess.result_state(),
        "solver_run_requested": solver_run_requested,
        "state_changed": True,
        "confirmation_message": confirmation_message,
        "action_kind": proposal.action if proposal.kind in {"assignment_action", "data_action"} else None,
    }


@router.post("/api/chat/reject")
def reject_pending_proposal(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    if sess.pending_proposal is None:
        raise HTTPException(status_code=409, detail="אין הצעה ממתינה.")
    proposal = sess.pending_proposal
    sess.decision_history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "decision": "rejected",
        "kind": proposal.kind,
        "summary": proposal.summary_hebrew,
    })
    sess.decision_history = sess.decision_history[-100:]
    sess.pending_proposal = None
    sess.chat_history.append({"role": "assistant", "content": "בסדר, ההצעה בוטלה."})
    store.save(sess)
    return {"rejected": True}


@router.get("/api/chat/history")
def get_chat_history(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return {
        "messages": _display_value(sess.chat_history, sess),
        "pending_proposal": _display_value(asdict(sess.pending_proposal), sess) if sess.pending_proposal else None,
    }


@router.get("/api/project-memory")
def get_project_memory(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return {
        "notes": list(sess.user_notes),
        "decisions": list(sess.decision_history[-20:]),
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
