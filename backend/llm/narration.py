"""Turns a solver-proven infeasibility conflict set into a plain-Hebrew
explanation.

The conflict itself is never invented or diagnosed by the LLM -- it's
already known deterministically, via `src.optimizer`'s CP-SAT
assumption-literal conflict extraction (`OptimizationResult.
conflicting_constraint_ids`). The model's only job here is phrasing an
already-known fact clearly and suggesting a next step. If the LLM isn't
configured or the call fails for any reason, a plain deterministic
fallback message is used instead -- seeing *that* a solve is infeasible
(and which rules are responsible) must never break because an unrelated
feature (chat) isn't configured or is briefly unavailable.
"""

from __future__ import annotations

from src.constraints import Constraint

from .provider import LLMNotConfiguredError, text_completion

NARRATION_SYSTEM_PROMPT = """את/ה עוזר/ת שמסביר/ה ליועצת/מחנכת למה שיבוץ תלמידות לכיתות נכשל.
הפתרון עצמו כבר הוכח על ידי מנוע האופטימיזציה כבלתי אפשרי, בגלל צירוף ספציפי של כללים
שסותרים זה את זה - זו עובדה נתונה, לא דבר שאת/ה צריך/ה לנחש או לחשב מחדש. התפקיד שלך
הוא רק לנסח את זה בעברית ברורה ותמציתית, ולהציע צעד הבא (למשל: להפוך אחד הכללים
למועדף/רך במקום חובה, או להסיר אותו). פסקה קצרה אחת, לא רשימה ארוכה."""


def _fallback_message(conflicting: list[Constraint]) -> str:
    lines = [f"- {c.label_hebrew} ({'חובה' if c.hard else 'מועדף'})" for c in conflicting]
    return (
        "השיבוץ אינו אפשרי בגלל הצירוף הבא של כללים סותרים:\n"
        + "\n".join(lines)
        + "\nאפשר להפוך אחד מהם למועדף (רך) או להסיר אותו ולנסות שוב."
    )


RESULT_SYSTEM_PROMPT = """את/ה עוזר/ת שמסביר/ה ליועצת/מחנכת מה יצא משיבוץ תלמידות לכיתות
שכבר הורץ והסתיים בהצלחה. המספרים נתונים ומדויקים - אל תמציא/י מספרים ואל תחשב/י מחדש.
כתב/י 1-2 משפטים קצרים בעברית: מה יצא טוב, ומה שווה לבדוק. בלי רשימות, בלי כותרות,
בלי לחזור על כל המספרים - רק הקריאה המקצועית שלהם."""


def relaxation_candidate(conflicting: list[Constraint]) -> Constraint | None:
    """Pick which rule to suggest softening out of a proven conflict set.

    Rules the counselor added herself (chat/manual) come first: a built-in
    default like the class-size range is usually a real policy, whereas an
    ad-hoc exception is the likelier thing to bend. Only hard rules are
    candidates -- softening an already-soft rule would change nothing,
    since only hard rules can make a model infeasible.

    Note this is a *suggestion*: the conflict set is "sufficient", so
    relaxing one member breaks this particular conflict but another may
    surface behind it. The wording downstream says so rather than
    promising a fix.
    """
    hard = [c for c in conflicting if c.hard]
    if not hard:
        return None
    return next((c for c in hard if c.source != "builtin_default"), hard[0])


def narrate_result(summary: str) -> str | None:
    """A short human read of a *successful* solve. Returns None when the
    LLM isn't configured -- unlike infeasibility (where the user must see
    the conflict), commentary is purely additive, so its absence should
    leave the result artifact untouched rather than inserting filler."""
    try:
        text = text_completion(system_prompt=RESULT_SYSTEM_PROMPT, user_message=summary)
    except Exception:
        # Covers LLMNotConfiguredError and any transient provider failure --
        # both mean "no commentary", never a failed solve response.
        return None
    return text.strip() or None


def narrate_infeasibility(conflicting: list[Constraint]) -> str:
    """conflicting: the Constraint objects matching
    OptimizationResult.conflicting_constraint_ids. Empty when the solve
    timed out without CP-SAT proving infeasibility (a different situation
    from a proven conflict -- handled with its own message, not sent to
    the LLM, since there's no conflict set to narrate)."""
    if not conflicting:
        return "השיבוץ אינו אפשרי או שהזמן לא הספיק להוכיח זאת. אפשר לנסות להגדיל את מגבלת הזמן, או לבדוק את דוח האפשרות."

    fallback = _fallback_message(conflicting)
    rules_list = "\n".join(f"- {c.label_hebrew} ({'חובה' if c.hard else 'מועדף'})" for c in conflicting)
    user_message = f"הכללים הבאים סותרים זה את זה, ולכן השיבוץ בלתי אפשרי:\n{rules_list}"

    try:
        text = text_completion(system_prompt=NARRATION_SYSTEM_PROMPT, user_message=user_message)
    except LLMNotConfiguredError:
        return fallback
    except Exception:
        # Narration is a convenience on top of an already-correct, already-
        # deterministic result; never let it turn a successful infeasibility
        # diagnosis into a broken /api/optimize response.
        return fallback

    return text.strip() or fallback
