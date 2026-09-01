import pandas as pd

from src.excel_loader import load_workbook


def test_fully_blank_rows_are_never_loaded_as_students(tmp_path):
    path = tmp_path / "students.xlsx"
    source = pd.DataFrame(
        [
            {"id": 1, "first": "א", "last": "א"},
            {"id": None, "first": None, "last": None},
            {"id": 2, "first": "ב", "last": "ב"},
        ]
    )
    source.to_excel(path, index=False, startrow=3)

    workbook = load_workbook(
        str(path),
        header_row_1indexed=4,
        first_data_row_1indexed=5,
        last_data_row_1indexed=7,
    )

    assert workbook.raw_df["id"].tolist() == [1, 2]
    assert any("שורות ריקות לחלוטין" in note for note in workbook.notes)
