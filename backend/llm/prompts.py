"""System prompt and per-turn context blocks for the constraint agent.

The prompt's job changed. It used to be narrow -- turn a Hebrew sentence
into one typed tool call -- and it carried the entire roster inline, one
line per student, because that was the only way the model could know
anything. Now there are read tools (backend/llm/read_tools.py), so the
prompt carries a *summary* and tells the model to go look up specifics.

That swap matters twice over: it is what lets the model answer questions
about the assignment at all (the roster dump never contained the assignment
in the first place), and it takes the fixed per-call cost from ~217 roster
lines down to a fixed block, which is what makes a multi-step loop
affordable.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.column_mapping import (
    FIELD_ACADEMIC_LEVEL,
    FIELD_CURRENT_SCHOOL,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_HAMAR,
    FIELD_INCLUSION,
)
from src.constraints import Constraint

SYSTEM_PROMPT_TEMPLATE = """את/ה עוזר/ת מקצועי/ת שמסייע/ת ליועצת בית ספר לבנות ולבדוק שיבוץ תלמידות לכיתות.

יש לך שני סוגי כלים, והם מתנהגים אחרת:

**כלי קריאה** (get_solve_summary, get_class_sizes, get_class_composition, get_violations,
get_active_rules, explain_student_placement, query_roster) - רצים מיד ומחזירים לך נתונים
אמיתיים מהשיבוץ הנוכחי. אפשר לקרוא לכמה מהם ברצף לפני שעונים.

**כלי בדיקה** (simulate_capacity_change, simulate_class_count, simulate_rule_toggle) - מריצים
שיבוץ ניסיוני אמיתי עם שינוי היפותטי ומחזירים השוואה למצב הנוכחי, בלי להחיל שום דבר.
השתמש/י בהם כשנשאלת "מה יקרה אם" - אל תנחש/י את התוצאה, בדוק/בדקי אותה. מוגבלים לשתי
בדיקות לשאלה, אז בחר/י את הווריאציה המשמעותית ביותר.

**כלי כתיבה** (propose_*, modify_constraint, remove_constraint) - לא מבצעים כלום בעצמם.
כל קריאה כזו נעצרת ומוצגת ליועצת לאישור מפורש לפני שהיא נכנסת לתוקף.

איך לעבוד:
- **לעולם אל תנחש/י נתונים.** אם נשאלת שאלה על השיבוץ - גדלים, הרכב, הפרות, מיקום של
  תלמידה, מספרים מכל סוג - קרא/י לכלי הקריאה המתאים וענה/י מהנתונים שחזרו. אסור לענות
  "ייתכן ש..." או "יכול להיות ש..." על משהו שכלי קריאה יכול לענות עליו בוודאות.
- **סדר העבודה הטבעי הוא: לבדוק את הנתונים, להריץ בדיקה, ואז להציע.** אם את/ה עומד/ת
  להציע שינוי בכלל - קודם הרץ/הריצי אותו ככלי בדיקה, וכלול/י בהצעה מה הבדיקה הראתה.
  הצעה שמגובה במספרים שווה הרבה יותר מהצעה שמנוסחת יפה.
- אחרי שקראת/ה את הנתונים, ענה/י תשובה קצרה, ישירה ומספרית, ואם יש צעד המשך טבעי -
  הצע/י אותו במשפט אחד ("בדקתי - הידוק ל-35-36 עובד ומקטין את הפער לאחד. לעדכן?").
- תוצאות בדיקה הן אינדיקציה, לא הבטחה: הן רצות בתקציב זמן מקוצר. דווח/י על הכיוון
  והסדר גודל ("הפער יורד משלוש לאחת"), לא על המספרים כאילו הם סופיים.
- אם בדיקה מחזירה שהשינוי לא אפשרי - זו תשובה שימושית. אמור/אמרי אותה במפורש ולאיזה
  כלל היא מתנגשת.
- הצעת כלל חדש היא לא תחליף לבדיקה. אם לא ברור אם הכלל צריך להיות חובה או מועדף,
  שאל/י שאלה קצרה במקום לנחש.
- **הקטגוריות משתנות מבית ספר לבית ספר.** התבסס/י אך ורק על העמודות שמופיעות בהקשר למטה או
  שחוזרות מ-get_dataset_columns. אם היועצת מדברת על משהו שאין לו עמודה - אמור/אמרי זאת ושאל/י
  אם להגדיר את זה כקבוצה ידנית של תלמידות. אל תמציא/י עמודה.
- אל תריץ/י שיבוץ בעצמך. הרצת השיבוץ היא תמיד פעולה נפרדת שהיועצת מבצעת.

שפה וזהות:
- ענה/י אך ורק בעברית - אף לא מילה אחת באנגלית. כלי הקריאה מחזירים שדות באנגלית;
  זה נתון גולמי בלבד, תרגם/י אותו לעברית טבעית ואל תצטט/י שמות שדות.
- כתוב/כתבי בעברית שיחתית, כאילו את/ה מדבר/ת עם היועצת פנים אל פנים. בלי כותרות
  מודגשות, בלי רשימות ממוספרות של שדות טכניים, בלי סוגריים עם שמות משתנים.
- תלמידות מיוצגות בטוקנים אנונימיים (למשל STUDENT_a1b2c3) ולא בשמותיהן - זה מכוון.
  לעולם אל תבקש/י שם אמיתי ואל תנחש/י אחד. כשמדברים על תלמידה, השתמש/י בטוקן שלה.
- כשאת/ה קורא/ת לכלי כתיבה, כלול/י תמיד נימוק קצר בעברית שמסביר בדיוק מה ההצעה
  אומרת - זה בדיוק מה שהיועצת תראה כדי לאשר או לדחות.
- החזר/י רק את התשובה לשאלה הנוכחית. אל תוסיף/י בסוף תפריט, רשימת שאלות המשך
  או הצעות ממוספרות; הממשק מייצר צעדי המשך מובנים בנפרד ממצב המערכת.
- כשקראת לכלי, בסס/י את התשובה על הנתון שחזר ממנו. אין צורך לציין את שם הכלי
  או לתאר את התהליך הטכני שעשית.

הקשר נוכחי:

{planning_context}

{roster_context}

{columns_context}

{result_context}

{constraints_context}
"""


def build_planning_context(planning: bool, num_classes: int, requirements=None) -> str:
    """Which half of the job we are in, and what has been decided so far.

    Planning mode is the case that did not exist before: no workbook, so no
    roster, no assignment, and no data-reading tool that can return anything.
    Saying so plainly is what stops the model calling six of them and then
    apologising -- and it is what lets it act as an advisor instead, which is
    the whole point of being reachable before the file exists.
    """
    reqs = list(requirements or [])
    if not planning:
        line = f"מצב: קובץ נטען וניתן לעבוד על הנתונים עצמם. השכבה מחולקת ל-{num_classes} כיתות."
        if reqs:
            line += (
                f" יש {len(reqs)} עמודות ברשימת הדרישות מתקופת התכנון - "
                "אפשר לבדוק מול הקובץ עם get_data_requirements."
            )
        return line

    lines = [
        "מצב: **תכנון מקדים - עדיין לא נטען קובץ.**",
        f"מספר הכיתות המתוכנן כרגע: {num_classes} (אפשר לשנות עם set_class_count).",
        "",
        "בשלב הזה את/ה יועץ/ת שמוביל/ה, לא פקיד/ה שממתין/ה להוראות:",
        "- כלי הקריאה על תוצאות ועל תלמידות יחזירו שאין נתונים. אל תקרא/י להם.",
        "- **הצע/י כללים ביוזמתך.** את/ה יודע/ת איך נראה שיבוץ טוב: כיתות בגודל דומה, פיזור מאוזן "
        "של רמות הלימוד, פיזור של תלמידות מאותו בית ספר קודם, מכסה סבירה לכל קטגוריה, ומענה "
        "לבקשות חברות. אל תשאל/י \"מה תרצי?\" ותחכה/י - אמור/אמרי מה את/ה ממליץ/ה ולמה, והצע/י "
        "את הכלל הראשון מיד. אחרי שהיועצת מאשרת כלל, הצע/י את הבא בתור עד שהתמונה שלמה.",
        "- **גם עמודות את/ה מציע/ה ביוזמתך.** אם שיקול מקובל דורש עמודה שאין - למשל תאומות או "
        "אחיות - אמור/אמרי \"בדרך כלל כדאי גם...\" ורשום/רשמי אותה ב-note_required_data, בלי לחכות "
        "שהיועצת תעלה את זה בעצמה. היא לא יודעת מה אפשר לבקש; זה התפקיד שלך.",
        "- שאל/י שאלה רק כשהתשובה באמת משנה מה תעשה/י (חובה או מועדף? כמה בכיתה?). אל תשאל/י "
        "שאלות פתוחות במקום להציע.",
        "- **פעולה קודמת לדיבור.** אם מגיע לך לקרוא לכלי - קרא/י לו *באותו תור*, לפני שאת/ה כותב/ת "
        "משפט. משפטים כמו \"אני ארשום\", \"אני אכניס דרישה\", \"נעבוד על זה עכשיו\" או \"אני מציע "
        "לרשום\" **לא עושים כלום** - הם רק נראים ליועצת כאילו קרה משהו, וזה גרוע מכלום. קודם "
        "הכלי, אחר כך תיאור של מה שקרה בפועל.",
        "- **לפני note_required_data - בדוק/בדקי שהעמודה לא קיימת כבר.** רמת/הישגים לימודיים, "
        "בית ספר קודם, כיתה קודמת, מוצא, שילוב, דיפרנציאלית וח\"מ **קיימות בכל קובץ** (ראה/י רשימת "
        "העמודות למטה). לבקשה כמו \"לאזן את רמות הלימוד\" הכלי הנכון הוא propose_balance על "
        "academic_level - **לא** רישום עמודה חדשה. רשום/רשמי עמודה רק כשבאמת אין כזו: תאומות, "
        "אחיות, שכנות, בעיות התנהגות וכדומה.",
        "- אם היועצת אומרת שלא ראתה שמשהו נוסף - היא צודקת: זה אומר שלא קראת לכלי. קרא/י לו עכשיו "
        "במקום להתנצל ולהסביר.",
        "- אל תבקש/י שמות של תלמידות בשלב הזה. שמות נכנסים יחד עם הקובץ, לא בשיחה.",
        "- כשנראה שסיימתם, סכם/י בקצרה: כמה כיתות, אילו כללים, ואילו עמודות צריך להכין.",
    ]
    if reqs:
        lines.append("")
        lines.append("עמודות שכבר סוכמו: " + ", ".join(r.label for r in reqs))
    return "\n".join(lines)


# The columns every roster has, whatever else it carries. Kept in step with
# read_tools.groupable_fields() -- these are exactly the built-in fields a
# rule may name.
STANDARD_COLUMNS = [
    ("academic_level", "הישגים לימודיים", "קטגוריה"),
    ("current_school", 'ביה"ס קודם', "קטגוריה"),
    ("current_class", "כיתה קודמת", "קטגוריה"),
    ("ethiopian_origin", "מוצא אתיופי", "סימון"),
    ("differential", "דיפרנציאלית", "סימון"),
    ("inclusion", "שילוב", "סימון"),
    ("hamar", 'ח"מ', "סימון"),
]


def build_dataset_columns_context(schema=None) -> str:
    """Every column a rule may name -- the standard ones and this school's own.

    The standard list used to be missing entirely: the block said "only the
    standard fields" without ever saying which. So when a counselor asked to
    balance academic levels, the model had no way to know `academic_level`
    already exists in every roster, and recorded it as a column she needed to
    go and create. The right answer was a balance rule it could have proposed
    on the spot. Naming them is the fix.
    """
    lines = [
        "עמודות סטנדרטיות שקיימות בכל קובץ - אפשר לכתוב עליהן כללים מיד, **בלי** לבקש מהיועצת",
        "להוסיף אותן לאקסל:",
    ]
    for key, label, kind in STANDARD_COLUMNS:
        lines.append(f'- {key} ("{label}") - {kind}')
    lines.append("(בנוסף: שם, מזהה ובקשות חברות מטופלות אוטומטית.)")
    standard = "\n".join(lines)

    extras = list(schema.extras) if schema is not None else []
    if not extras:
        return standard + "\n\nעמודות ייחודיות לבית הספר הזה: אין (עדיין)."

    lines = []
    for c in extras:
        if c.kind == "flag":
            lines.append(f"- {c.key} (\"{c.label}\") - סימון כן/לא, {c.true_count} תלמידות מסומנות")
        elif c.kind == "category":
            shown = ", ".join(str(v) for v in c.values[:8])
            more = f" ועוד {len(c.values) - 8}" if len(c.values) > 8 else ""
            lines.append(f'- {c.key} ("{c.label}") - קטגוריה, ערכים: {shown}{more}')
        else:
            lines.append(f'- {c.key} ("{c.label}") - מספרי, {c.filled_count} ערכים')
    return (
        standard
        + "\n\nעמודות נוספות שקיימות בקובץ של בית הספר הזה (אפשר לכתוב עליהן כללים בדיוק כמו על "
        "הסטנדרטיות):\n"
        + "\n".join(lines)
    )


def build_roster_context(df=None, token_map=None) -> str:
    """A shape-of-the-data summary, not the data.

    This used to emit one line per student (~217 lines, rebuilt on every
    call). Nothing in it was per-student *useful* to the model unless it was
    reasoning about that specific student -- which is now `query_roster` and
    `explain_student_placement`, on demand. `token_map` is accepted and
    ignored so existing callers/tests don't break.
    """
    if df is None:
        return "נתוני תלמידות: טרם נטען קובץ, אין עדיין רשימת תלמידות."

    n = len(df)
    lines = [f"סה\"כ {n} תלמידות בנתונים."]

    if FIELD_ACADEMIC_LEVEL in df.columns:
        levels = df[FIELD_ACADEMIC_LEVEL].value_counts().to_dict()
        if levels:
            lines.append("התפלגות הישגים: " + ", ".join(f"{k} - {int(v)}" for k, v in levels.items()))

    cats = [
        (FIELD_DIFFERENTIAL, "דיפרנציאלית"),
        (FIELD_ETHIOPIAN_ORIGIN, "מוצא אתיופי"),
        (FIELD_INCLUSION, "שילוב"),
        (FIELD_HAMAR, 'ח"מ'),
    ]
    present = [f"{label} - {int(df[field].fillna(False).astype(bool).sum())}" for field, label in cats if field in df.columns]
    if present:
        lines.append("קטגוריות: " + ", ".join(present))

    if FIELD_CURRENT_SCHOOL in df.columns:
        schools = df[FIELD_CURRENT_SCHOOL].dropna().unique().tolist()
        if schools:
            lines.append(f"בתי ספר מקור ({len(schools)}): " + ", ".join(str(s) for s in schools[:12]))

    lines.append("לפרטים על תלמידה מסוימת או על תת-קבוצה - השתמש/י ב-query_roster או ב-explain_student_placement.")
    return "\n".join(lines)


def build_result_context(
    has_result: bool,
    num_classes: int,
    class_sizes: Optional[list[int]] = None,
    stale: bool = False,
) -> str:
    """Whether there is an assignment to talk about at all.

    Deliberately thin: just enough for the model to know a result exists and
    that the read tools will work. The numbers themselves come from the
    tools, so the prose in an answer can never drift from the artifact the
    counselor is looking at.
    """
    if not has_result:
        return (
            "מצב השיבוץ: טרם הופק שיבוץ בסשן הזה. כלי הקריאה על תוצאות יחזירו שאין תוצאה. "
            "אפשר עדיין לדבר על הנתונים ועל הכללים."
        )
    sizes = f" גדלים נוכחיים: {class_sizes}." if class_sizes else ""
    warn = " שים/י לב: הכללים השתנו מאז ההרצה, כך שהתוצאה אינה מעודכנת." if stale else ""
    return (
        f"מצב השיבוץ: קיים שיבוץ פעיל ל-{num_classes} כיתות.{sizes}{warn} "
        "לכל שאלה על התוצאה - קרא/י לכלי הקריאה, אל תנחש/י."
    )


def build_constraints_context(constraints: list[Constraint]) -> str:
    active = [c for c in constraints if c.active]
    if not active:
        return "אין כללים פעילים כרגע."
    lines = [f"- [{c.id}] {c.label_hebrew} ({'חובה' if c.hard else 'מועדף'}, מקור: {c.source})" for c in active]
    return (
        "כללים פעילים כרגע (תיאור בלבד - לערכים המספריים המדויקים קרא/י ל-get_active_rules):\n"
        + "\n".join(lines)
    )


def build_system_prompt(
    roster_context: str,
    constraints_context: str,
    result_context: str = "",
    columns_context: str = "",
    planning_context: str = "",
) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        planning_context=planning_context,
        roster_context=roster_context,
        columns_context=columns_context,
        result_context=result_context,
        constraints_context=constraints_context,
    )
