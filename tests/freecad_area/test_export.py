"""表の組み立てとExcel/CSV出力のテスト。"""
import csv

import pytest

from freecad_area.export import ExportError, write_area_table
from freecad_area.rooms import Room
from freecad_area.table import build_table


def test_table_without_levels_has_two_columns():
    headers, rows = build_table([Room("リビング", 16.56), Room("キッチン", 8.28)])
    assert headers == ["部屋名", "床面積 (㎡)"]
    assert rows == [["リビング", 16.56], ["キッチン", 8.28], ["合計", 24.84]]


def test_table_adds_subtotals_per_floor():
    rooms = [
        Room("リビング", 16.56, "1階"),
        Room("キッチン", 8.28, "1階"),
        Room("主寝室", 13.24, "2階"),
    ]
    headers, rows = build_table(rooms)
    assert headers == ["部屋名", "階", "床面積 (㎡)"]
    assert rows == [
        ["リビング", "1階", 16.56],
        ["キッチン", "1階", 8.28],
        ["1階 小計", "1階", 24.84],
        ["主寝室", "2階", 13.24],
        ["2階 小計", "2階", 13.24],
        ["合計", "", 38.08],
    ]


def test_single_floor_gets_no_subtotal_row():
    headers, rows = build_table([Room("リビング", 16.56, "1階")])
    assert [row[0] for row in rows] == ["リビング", "合計"]


def test_rooms_are_grouped_by_floor_even_if_the_document_order_mixes_them():
    rooms = [Room("A", 1.0, "1階"), Room("B", 2.0, "2階"), Room("C", 4.0, "1階")]
    _, rows = build_table(rooms)
    assert [row[0] for row in rows] == ["A", "C", "1階 小計", "B", "2階 小計", "合計"]
    assert rows[2][2] == 5.0


def test_unknown_area_is_blank_and_excluded_from_the_total():
    _, rows = build_table([Room("リビング", 16.56), Room("物置", None)])
    assert rows[1] == ["物置", None]
    assert rows[-1] == ["合計", 16.56]


def test_areas_are_rounded_to_two_decimals():
    _, rows = build_table([Room("リビング", 16.5649), Room("キッチン", 8.2751)])
    assert rows[0][1] == 16.56
    # 合計は丸める前の値から計算します（表示上のずれを避けるため）。
    assert rows[-1][1] == 24.84


def test_csv_is_written_with_a_bom_so_excel_shows_japanese(tmp_path):
    path = tmp_path / "床面積.csv"
    write_area_table([Room("リビング", 16.56, "1階")], str(path))
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["部屋名", "階", "床面積 (㎡)"]
    assert rows[1] == ["リビング", "1階", "16.56"]
    assert rows[-1] == ["合計", "", "16.56"]


def test_unknown_area_becomes_an_empty_csv_cell(tmp_path):
    path = tmp_path / "床面積.csv"
    write_area_table([Room("物置", None)], str(path))
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1] == ["物置", ""]


def test_xlsx_keeps_areas_as_numbers(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "床面積.xlsx"
    write_area_table([Room("リビング", 16.56, "1階"), Room("主寝室", 13.24, "2階")],
                     str(path), sheet_title="床面積表")
    ws = openpyxl.load_workbook(str(path))["床面積表"]
    assert [c.value for c in ws[1]] == ["部屋名", "階", "床面積 (㎡)"]
    total = ws.cell(row=ws.max_row, column=3)
    assert total.value == pytest.approx(29.8)
    assert isinstance(total.value, float)
    assert total.number_format == "0.00"
    assert ws.cell(row=ws.max_row, column=1).font.bold
    assert ws.freeze_panes == "A2"


def test_unknown_extension_is_rejected(tmp_path):
    with pytest.raises(ExportError, match="拡張子"):
        write_area_table([Room("リビング", 16.56)], str(tmp_path / "床面積.txt"))
