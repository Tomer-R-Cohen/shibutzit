import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.session_store import store


@pytest.mark.parametrize("header_start_row", [0, 3])
def test_uploaded_workbook_infers_header_and_does_not_truncate_rows(header_start_row):
    """User uploads must not inherit the bundled workbook's rows 4..221."""
    source = pd.DataFrame(
        {
            "מספר סידורי": range(1, 231),
            "שם משפחה": [f"משפחה {i}" for i in range(1, 231)],
            "שם פרטי": [f"תלמידה {i}" for i in range(1, 231)],
            'ביה"ס נוכחי': ["בית ספר"] * 230,
            "כיתה": ["ו1"] * 230,
            "מוצא": [""] * 230,
            "הישגים לימודיים": ["בינונית"] * 230,
        }
    )
    workbook = io.BytesIO()
    source.to_excel(workbook, index=False, startrow=header_start_row)
    workbook.seek(0)

    session_id = f"upload-bounds-{header_start_row}"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
    client = TestClient(backend_main.app)
    response = client.post(
        "/api/workbook/load",
        headers=headers,
        params={"use_default": "false", "header_row": 0, "first_data_row": 0, "last_data_row": 0},
        files={"file": ("students.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["row_count"] == 230
    assert "שם פרטי" in payload["columns"]
    sess = store.get_or_create(session_id)
    assert sess.loaded_wb.header_row_1indexed == header_start_row + 1
    assert sess.loaded_wb.last_data_row_1indexed is None
    store.reset(session_id)


@pytest.mark.parametrize("header_start_row", [0, 3])
def test_unresolved_required_columns_cannot_be_silently_marked_manual(header_start_row):
    source = pd.DataFrame(
        {
            "Surname": ["One", "Two"],
            "Given": ["A", "B"],
            "SchoolName": ["School", "School"],
            "SourceClass": ["6A", "6B"],
            "Level": ["high", "medium"],
        }
    )
    workbook = io.BytesIO()
    source.to_excel(workbook, index=False, startrow=header_start_row)
    workbook.seek(0)

    session_id = f"upload-required-mapping-{header_start_row}"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
    client = TestClient(backend_main.app)
    loaded = client.post(
        "/api/workbook/load",
        headers=headers,
        params={"use_default": "false", "header_row": 0, "first_data_row": 0, "last_data_row": 0},
        files={"file": ("students.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert loaded.status_code == 200
    guess = client.get("/api/mapping/guess", headers=headers).json()

    bypass = dict(guess["mapping"])
    bypass.update({"last_name": "Surname", "current_school": "SchoolName", "current_class": "SourceClass", "academic_level": "Level"})
    rejected = client.post(
        "/api/mapping/apply",
        headers=headers,
        json={"mapping": bypass, "manual_fields": [*guess["manual_fields"], "first_name"]},
    )
    assert rejected.status_code == 400
    assert "שם פרטי" in rejected.json()["detail"]

    complete = dict(bypass)
    complete["first_name"] = "Given"
    applied = client.post(
        "/api/mapping/apply",
        headers=headers,
        json={"mapping": complete, "manual_fields": guess["manual_fields"]},
    )
    assert applied.status_code == 200, applied.text
    students = client.get("/api/students", headers=headers).json()["rows"]
    assert [row["student_id"] for row in students] == [1, 2], "missing ids should be generated safely"
    assert [row["first_name"] for row in students] == ["A", "B"]
    store.reset(session_id)


def test_upload_discovers_roster_table_behind_cover_sheet():
    workbook = io.BytesIO()
    roster = pd.DataFrame(
        {
            "Surname": ["One", "Two", "Three"],
            "Given": ["A", "B", "C"],
            "SchoolName": ["North", "South", "North"],
            "SourceClass": ["6A", "6B", "6A"],
            "Level": ["high", "medium", "low"],
        }
    )
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame({"Instructions": ["This workbook contains a student roster."]}).to_excel(writer, sheet_name="Read me", index=False)
        roster.to_excel(writer, sheet_name="Roster", index=False, startrow=3)
    workbook.seek(0)

    session_id = "upload-cover-sheet"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
    client = TestClient(backend_main.app)
    response = client.post(
        "/api/workbook/load",
        headers=headers,
        params={"use_default": "false", "header_row": 0, "first_data_row": 0, "last_data_row": 0},
        files={"file": ("students.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["active_sheet"] == "Roster"
    assert response.json()["row_count"] == 3
    assert response.json()["columns"] == list(roster.columns)
    sess = store.get_or_create(session_id)
    assert sess.loaded_wb.header_row_1indexed == 4
    store.reset(session_id)
