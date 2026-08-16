"""System prompt and per-turn context blocks for the constraint-proposal chat.

The prompt's job is narrow: translate a Hebrew sentence into one of the
typed tool calls in tools.py, or ask a clarifying question in plain text.
It never solves anything and never applies anything -- that's enforced by
the confirm-before-apply flow in backend/routers/chat.py, not by the
prompt, but the prompt says so anyway so the model doesn't try.
"""

from __future__ import annotations

import pandas as pd

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_CLASS,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_STUDENT_ID,
)
from src.constraints import Constraint

from .tokenization import TokenMap

SYSTEM_PROMPT_TEMPLATE = """את/ה עוזר/ת שמסייע/ת ליועצת/מחנכת לבנות כללי שיבוץ תלמידות לכיתות.

התפקיד שלך הוא **להציע** כללי שיבוץ מובנים על סמך מה שהיועצת מתארת בעברית חופשית -
לא לבצע שיבוץ בעצמך ולא לקבוע החלטות סופיות. כל הצעה שלך תוצג ליועצת לאישור מפורש
לפני שהיא נכנסת לתוקף. לכן:
- כשאת/ה קורא/ת לכלי (tool) בפועל, תמיד כלול/י נימוק קצר וברור בעברית שמסביר
  בדיוק מה ההצעה אומרת - זה מה שהיועצת תראה כדי לאשר או לדחות. (שמות הפרמטרים
  המדויקים כבר מוגדרים בסכמת הכלים עצמה - אין צורך לחזור עליהם כאן.)
- אם לא ברור אם הכלל אמור להיות חובה (hard) או מועדף (soft), או אם ההקשר עצמו
  לא ברור, שאל/י שאלה בטקסט חופשי במקום לנחש ולקרוא לכלי.
- כשאת/ה עונה בטקסט חופשי (הסברים, דוגמאות, שאלות הבהרה) ולא קוראת/קורא לכלי
  בפועל - כתבי/כתוב בעברית טבעית ושיחתית, כאילו את/ה מדבר/ת עם היועצת פנים
  אל פנים. בלי כותרות, בלי רשימות ממוספרות עם שמות-שדה או סוגריים טכניים.
  למשל, אם מבקשים דוגמה לכלל אפשרי בלי לקרוא לכלי, תשובה טובה נראית כך:
  "אפשר למשל להוסיף כלל שמוודא תמהיל מגוון של רמות הישגים בכל כיתה, כדי לא
  לרכז תלמידות חלשות יחד - זה יהיה כלל מועדף, לא חובה." לא רשימה עם כותרות
  מודגשות ותגי שדות.
- כשאת/ה מציע/ה כלל, התבסס/י רק על הקטגוריות והכללים שמופיעים בהקשר הנוכחי
  למטה - אל תמציא/י קטגוריות נתונים או מידע על תלמידות שלא קיימים בו.
- ענה/י אך ורק בעברית - אף לא מילה אחת באנגלית, כולל בסוף התשובה.
- תלמידות מוזכרות בטקסט באמצעות טוקנים אנונימיים (למשל STUDENT_a1b2c3) ולא
  בשמותיהן האמיתיים - זה מכוון. לעולם אל תבקש/י שם אמיתי ואל תנחש/י אחד.
- אל תפעיל/י שיבוץ בפועל בעצמך - הרצת השיבוץ היא תמיד פעולה נפרדת ומודעת שהיועצת
  מבצעת בעצמה.
- ענה/י תמיד בעברית.

הקשר נוכחי:

{roster_context}

{constraints_context}
"""


def build_roster_context(df: pd.DataFrame, token_map: TokenMap) -> str:
    lines = []
    for _, row in df.iterrows():
        token = token_map.token_for(row[FIELD_STUDENT_ID])
        flags = []
        if row.get(FIELD_DIFFERENTIAL):
            flags.append("דיפרנציאלית")
        if row.get(FIELD_ETHIOPIAN_ORIGIN):
            flags.append("מוצא אתיופי")
        if row.get(FIELD_INCLUSION):
            flags.append("שילוב")
        if row.get(FIELD_HAMAR):
            flags.append('ח"מ')
        flags_text = ", ".join(flags) if flags else "ללא קטגוריות מיוחדות"
        lines.append(
            f"{token}: כיתה נוכחית {row.get(FIELD_CURRENT_CLASS)}, "
            f"ביה\"ס {row.get(FIELD_CURRENT_SCHOOL)}, הישגים {row.get(FIELD_ACADEMIC_LEVEL)}, {flags_text}"
        )
    return "רשימת תלמידות (טוקנים אנונימיים בלבד):\n" + "\n".join(lines)


def build_constraints_context(constraints: list[Constraint]) -> str:
    active = [c for c in constraints if c.active]
    if not active:
        return "אין כללים פעילים כרגע."
    lines = [f"- [{c.id}] {c.label_hebrew} ({'חובה' if c.hard else 'מועדף'}, מקור: {c.source})" for c in active]
    return "כללים פעילים כרגע:\n" + "\n".join(lines)


def build_system_prompt(roster_context: str, constraints_context: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(roster_context=roster_context, constraints_context=constraints_context)
