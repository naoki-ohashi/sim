"""`freecad-floor-area` コマンドのテスト。"""
import csv

import pytest

from freecad_area import cli

from .fcstd_fixture import document_xml, space_xml, storey_xml, write_fcstd


@pytest.fixture()
def house(tmp_path):
    xml = document_xml(
        [
            space_xml("Space", "リビング", 16.56),
            space_xml("Space001", "主寝室", 13.24),
            storey_xml("Floor", "1階", ["Space"]),
            storey_xml("Floor001", "2階", ["Space001"]),
        ],
        [("Space", "Part::FeaturePython"), ("Space001", "Part::FeaturePython"),
         ("Floor", "App::DocumentObjectGroupPython"),
         ("Floor001", "App::DocumentObjectGroupPython")],
    )
    return write_fcstd(tmp_path / "住宅.FCStd", xml)


def test_writes_csv_and_prints_the_table(house, tmp_path, capsys):
    out = tmp_path / "床面積.csv"
    assert cli.main([house, "-o", str(out)]) == 0

    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[-1] == ["合計", "", "29.8"]

    printed = capsys.readouterr().out
    assert "リビング" in printed and "合計" in printed
    assert str(out) in printed


def test_writes_xlsx(house, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "床面積.xlsx"
    assert cli.main([house, "-o", str(out), "--sheet", "面積表", "-q"]) == 0
    wb = openpyxl.load_workbook(str(out))
    assert wb.sheetnames == ["面積表"]


def test_default_output_sits_next_to_the_source(house):
    assert cli.main([house, "-q"]) == 0
    expected = house.replace(".FCStd", "_床面積")
    assert cli.default_output_path(house).startswith(expected)


def test_reports_a_document_without_rooms(tmp_path, capsys):
    path = write_fcstd(
        tmp_path / "空.FCStd",
        document_xml([storey_xml("Floor", "1階", [])],
                     [("Floor", "App::DocumentObjectGroupPython")]),
    )
    assert cli.main([path]) == 2
    assert "見つかりませんでした" in capsys.readouterr().err


def test_missing_file_is_an_error(tmp_path, capsys):
    assert cli.main([str(tmp_path / "ない.FCStd")]) == 1
    assert "エラー" in capsys.readouterr().err


def test_all_areas_flag_widens_the_search(tmp_path, capsys):
    path = write_fcstd(
        tmp_path / "スラブ.FCStd",
        document_xml([space_xml("Slab", "スラブ", 20.0, proxy=False)],
                     [("Slab", "Part::Feature")]),
    )
    assert cli.main([path]) == 2
    out = tmp_path / "床面積.csv"
    assert cli.main([path, "--all-areas", "-o", str(out), "-q"]) == 0
    assert "スラブ" in out.read_text(encoding="utf-8-sig")


def test_rooms_without_area_are_reported_on_stderr(tmp_path, capsys):
    path = write_fcstd(
        tmp_path / "面積なし.FCStd",
        document_xml([space_xml("Space", "リビング", 16.0),
                      space_xml("Space001", "物置", None)],
                     [("Space", "Part::FeaturePython"),
                      ("Space001", "Part::FeaturePython")]),
    )
    assert cli.main([path, "-o", str(tmp_path / "a.csv"), "-q"]) == 0
    assert "物置" in capsys.readouterr().err
