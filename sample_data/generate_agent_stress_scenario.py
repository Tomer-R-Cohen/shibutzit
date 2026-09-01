"""Generate a deliberately difficult, fully fictional agent test workbook.

The workbook is designed for conversational feasibility negotiation:

* 84 students and 6 destination classes permit exactly 14 students per class.
* Four default mandatory category rules are independently impossible.
* Source-school concentration makes an additional user-requested cap impossible.
* Seven-student friendship clusters compete with academic/source-school balance.
* Two non-blocking data-quality issues exercise file-aware conversation and edits.

No real student names or data are used.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


OUTPUT_PATH = Path(__file__).with_name("agent_stress_test_students.xlsx")
STUDENT_COUNT = 84


def student_name(student_id: int) -> str:
    return f"תלמידה תרחיש {student_id:03d}"


def friendship_requests(student_id: int) -> str:
    """Four mostly mutual requests inside a seven-student social cluster."""
    cluster_start = ((student_id - 1) // 7) * 7 + 1
    position = student_id - cluster_start
    peers = [
        cluster_start + ((position - 1) % 7),
        cluster_start + ((position + 1) % 7),
        cluster_start + ((position + 2) % 7),
        cluster_start + ((position + 3) % 7),
    ]
    names = [student_name(peer) for peer in peers]
    if student_id == 82:
        names[-1] = "תלמידה שאינה קיימת 999"
    if student_id == 83:
        names[-1] = "תלמידה תרחיש 081 שגוי"
    if student_id == 84:
        names = []
    return ", ".join(names)


def build_students() -> list[dict]:
    rows = []
    for student_id in range(1, STUDENT_COUNT + 1):
        if student_id <= 30:
            school = "בית ספר מקור א"
        elif student_id <= 54:
            school = "בית ספר מקור ב"
        elif student_id <= 72:
            school = "בית ספר מקור ג"
        else:
            school = "בית ספר מקור ד"

        if student_id <= 30:
            academic = "מצטיינת"
        elif student_id <= 60:
            academic = "בינונית"
        else:
            academic = "חלשה"

        # Intentional warnings, not blocking errors. They give the counselor
        # something concrete to inspect and correct conversationally.
        if student_id == 81:
            academic = "גבוהה מאוד"
        if student_id == 82:
            school = None

        rows.append(
            {
                "id": student_id,
                "last_name": f"תרחיש {student_id:03d}",
                "first_name": "תלמידה",
                "school": school,
                "current_class": ((student_id - 1) % 6) + 1,
                # Counts are deliberately incompatible with the shipped
                # defaults for six classes: 17, 7, 11, and 13 respectively.
                "ethiopian": "א" if 27 <= student_id <= 43 else None,
                "academic": academic,
                "differential": "כן" if 1 <= student_id <= 7 else None,
                "inclusion": "כן" if 1 <= student_id <= 5 or 8 <= student_id <= 13 else None,
                "hamar": "כן" if 14 <= student_id <= 26 else None,
                "friends": friendship_requests(student_id),
            }
        )
    return rows


def add_students_sheet(workbook: openpyxl.Workbook) -> None:
    sheet = workbook.active
    sheet.title = "תלמידות"
    sheet.sheet_view.rightToLeft = True
    sheet["A1"] = "תרחיש קצה סינתטי לבדיקת שיחה, אבחון וריכוך כללים"
    sheet["A2"] = "כל השמות והנתונים בקובץ זה בדויים לחלוטין"
    sheet["A1"].font = Font(bold=True, size=15, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="243B53")
    sheet.merge_cells("A1:K1")
    sheet.merge_cells("A2:K2")

    headers = [
        "מספר סידורי",
        "שם משפחה",
        "שם פרטי",
        'ביה"ס נוכחי',
        "כיתה",
        "מוצא",
        "הישגים לימודיים",
        "תלמידה דיפרנציאלית",
        "תלמידה בשילוב",
        'סטטוס ח"מ',
        "בקשות חברות (שמות, מופרד בפסיקים)",
    ]
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=4, column=column, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="486581")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_number, student in enumerate(build_students(), start=5):
        values = [
            student["id"],
            student["last_name"],
            student["first_name"],
            student["school"],
            student["current_class"],
            student["ethiopian"],
            student["academic"],
            student["differential"],
            student["inclusion"],
            student["hamar"],
            student["friends"],
        ]
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_number, column=column, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=column == 11)
            if row_number % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F5F7FA")

    widths = [14, 18, 14, 22, 10, 10, 20, 22, 18, 14, 72]
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = "A5"
    sheet.auto_filter.ref = f"A4:K{STUDENT_COUNT + 4}"


def add_guide_sheet(workbook: openpyxl.Workbook) -> None:
    sheet = workbook.create_sheet("Test Guide")
    sheet.sheet_view.rightToLeft = False
    sheet["A1"] = "Shibutzit conversational stress-test"
    sheet["A1"].font = Font(bold=True, size=16, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="243B53")
    sheet.merge_cells("A1:D1")

    rows = [
        ("Purpose", "Test whether the agent inspects the actual workbook, diagnoses infeasibility, asks for explicit approval, applies exact changes, runs the full solver, and discusses measured trade-offs."),
        ("Start naturally", "העליתי קובץ. אני צריכה 6 כיתות מאוזנות ורוצה לשמור כמה שיותר חברות יחד. תבדקי את הנתונים ותציעי איך להתחיל."),
        ("Demanding request", "אני רוצה בדיוק 14 תלמידות בכל כיתה. עד תלמידה דיפרנציאלית אחת, בדיוק 2 שילוב, בדיוק 3 ממוצא אתיופי ובדיוק 2 ח\"מ בכל כיתה. בנוסף, לא יותר מ-4 מאותו בית ספר. כל אלה חובה."),
        ("Expected behavior", "The agent should use workbook counts and solver evidence. It should not merely say 'no solution' or generically suggest relaxing rules."),
        ("Negotiation prompt", "תנתחי אילו כללים בלתי אפשריים בפני עצמם ותציעי את קבוצת השינויים הקטנה ביותר. אל תשני שום כלל בלי אישור שלי."),
        ("Approval test", "Use short follow-ups such as: כן; לכי על האפשרות הראשונה; תשאירי את גודל הכיתה קשיח; תרככי רק את כלל השילוב; keep everything else the same."),
        ("Result analysis", "למרות שכל כללי החובה מתקיימים, מה עדיין לא מאוזן בשיבוץ? תני לי שלוש דוגמאות ספציפיות מהכיתות והסבירי מה בדקת בפועל."),
        ("Trade-off test", "נסי לשפר את החברות בלי לשנות כללי חובה. אחר כך תשווי לגרסה הקודמת: מה השתפר, מה הורע וכמה תלמידות עברו?"),
        ("Student test", "למה תלמידה תרחיש 001 נמצאת בכיתה שלה? איזו חלופה בדקת, ומה יקרה אם נעביר אותה?"),
        ("Manual-control test", "תשאירי את תלמידה תרחיש 001 בכיתה הנוכחית, תנעלי אותה, ותנסי שוב לשפר את החברות."),
        ("Data-quality test", "תנתחי את איכות הקובץ עצמו. אילו רשומות או בקשות חברות דורשות בדיקה?"),
        ("Data-edit test", "After the agent identifies IDs 81/82, provide a fictional correction and ask it to update the project copy. The original workbook must remain unchanged."),
        ("Known arithmetic", "Hidden from the normal workflow unless you inspect this guide: 84 students; differential=7; inclusion=11; Ethiopian-origin=17; special-support=13; source schools=30/24/18/12."),
        ("Known workable direction", "A likely feasible relaxation set is differential 1–2, inclusion 1–2, Ethiopian-origin 2–3, special-support 2–3, and source-school A max 5, while retaining exactly 14 students per class."),
        ("Important", "A short simulation is evidence, not an applied change. Once you explicitly approve the exact tested change, the product should update the visible rule and launch a full solver run—not repeat the experiment."),
    ]

    for row_number, (label, detail) in enumerate(rows, start=3):
        label_cell = sheet.cell(row=row_number, column=1, value=label)
        detail_cell = sheet.cell(row=row_number, column=2, value=detail)
        label_cell.font = Font(bold=True, color="243B53")
        label_cell.fill = PatternFill("solid", fgColor="EAF0F6")
        for cell in (label_cell, detail_cell):
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.row_dimensions[row_number].height = 48

    sheet.column_dimensions["A"].width = 26
    sheet.column_dimensions["B"].width = 110
    sheet.freeze_panes = "A3"


def generate(path: Path = OUTPUT_PATH) -> Path:
    workbook = openpyxl.Workbook()
    add_students_sheet(workbook)
    add_guide_sheet(workbook)
    workbook.properties.title = "Shibutzit agent stress test"
    workbook.properties.subject = "Synthetic class-placement feasibility and trade-off scenario"
    workbook.properties.creator = "Shibutzit test data generator"
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


if __name__ == "__main__":
    output = generate()
    print(output)
