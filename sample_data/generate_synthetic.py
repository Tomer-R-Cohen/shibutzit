"""Generate a small synthetic student workbook for tests and demos.

Produces sample_data/synthetic_students.xlsx with ~28 clearly-fake students
covering all category combinations (differential, inclusion, hamar,
Ethiopian origin, academic levels) plus some friendship requests, laid out
with the SAME physical shape as the real workbook (header on row 4, data
starting row 5) so excel_loader/column_mapping can be exercised identically.
"""

from __future__ import annotations

import os

import openpyxl

FAKE_FIRST_NAMES = [
    "דוגמנית", "בדיקנית", "נסיינית", "לדוגמה", "טסטונית", "פקטית", "מוקנית",
    "דמיונית", "רגילה", "מיוחדת", "כללית", "פרטית", "משנית", "ראשית",
    "עזרנית", "חדשה", "ותיקה", "שנייה", "שלישית", "רביעית", "חמישית",
    "שישית", "שביעית", "שמינית", "תשיעית", "עשירית", "אחת עשרה", "שתים עשרה",
]
FAKE_LAST_NAMES = [
    "דוגמה", "בדיקה", "טסט", "נתון", "פקט", "מבחן", "סימולציה", "ניסוי",
]
SCHOOLS = ["בית ספר דוגמה א", "בית ספר דוגמה ב", "בית ספר דוגמה ג"]
LEVELS = ["מצטיינת", "בינונית", "חלשה"]


def build_rows(n: int = 28) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "idx": i,
                "last": FAKE_LAST_NAMES[i % len(FAKE_LAST_NAMES)],
                "first": FAKE_FIRST_NAMES[(i - 1) % len(FAKE_FIRST_NAMES)],
                "school": SCHOOLS[i % len(SCHOOLS)],
                "cur_class": i % 5,
                "origin": "א" if i % 4 == 0 else None,
                "level": LEVELS[i % 3],
            }
        )
    return rows


def write_workbook(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.cell(row=2, column=4, value="רשימה סינתטית לבדיקות - שכבת ז'")
    headers = ["", "מספר סידורי", "שם משפחה", "שם פרטי", 'ביה"ס נוכחי', "כיתה", "מוצא", "הישגים לימודיים"]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=4, column=col, value=h)

    rows = build_rows(28)
    r = 5
    for i, row in enumerate(rows):
        ws.cell(row=r, column=2, value=row["idx"])
        ws.cell(row=r, column=3, value=row["last"])
        ws.cell(row=r, column=4, value=row["first"])
        ws.cell(row=r, column=5, value=row["school"])
        ws.cell(row=r, column=6, value=row["cur_class"])
        ws.cell(row=r, column=7, value=row["origin"])
        ws.cell(row=r, column=8, value=row["level"])
        r += 1
        if i == 10:
            r += 1  # insert a blank spacer row, matching real workbook quirk

    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)


if __name__ == "__main__":
    write_workbook(os.path.join(os.path.dirname(__file__), "synthetic_students.xlsx"))
    print("wrote synthetic_students.xlsx")
