"""FreeCADマクロ（freecad/床面積集計.FCMacro）のテスト。

FreeCAD本体は無いので、マクロが使う `FreeCAD` モジュールだけを差し替えて
実行しています。
"""
import csv
import pathlib
import sys
import types

import pytest

from freecad_area.rooms import MM2_PER_M2

from .fakes import Doc, Obj, Quantity

MACRO = pathlib.Path(__file__).resolve().parents[2] / "freecad" / "床面積集計.FCMacro"


class _Console:
    def __init__(self):
        self.messages = []
        self.warnings = []

    def PrintMessage(self, text):  # noqa: N802 - FreeCADのAPI名
        self.messages.append(text)

    def PrintWarning(self, text):  # noqa: N802 - FreeCADのAPI名
        self.warnings.append(text)


def _load_macro(monkeypatch, document):
    """マクロを読み込む（自動実行はさせない）。"""
    app = types.ModuleType("FreeCAD")
    app.Console = _Console()
    app.GuiUp = False
    app.ActiveDocument = document
    monkeypatch.setitem(sys.modules, "FreeCAD", app)
    namespace = {"__name__": "macro_under_test", "__file__": str(MACRO)}
    exec(compile(MACRO.read_text(encoding="utf-8"), str(MACRO), "exec"), namespace)
    return namespace, app


def _space(name, label, area_m2):
    return Obj(name, label, IfcType="Space", Area=Quantity(area_m2 * MM2_PER_M2))


def test_macro_exports_the_active_document(monkeypatch, tmp_path):
    living, bedroom = _space("Space", "リビング", 16.56), _space("Space001", "主寝室", 13.24)
    doc = Doc([Obj("Floor", "1階", Group=[living, bedroom]), living, bedroom])
    macro, app = _load_macro(monkeypatch, doc)

    out = tmp_path / "床面積.csv"
    assert macro["export_floor_area"](str(out)) == str(out)

    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1] == ["リビング", "1階", "16.56"]
    assert rows[-1] == ["合計", "", "29.8"]
    assert "29.80 ㎡" in "".join(app.Console.messages)


def test_macro_warns_when_no_document_is_open(monkeypatch, tmp_path):
    macro, app = _load_macro(monkeypatch, None)
    assert macro["export_floor_area"](str(tmp_path / "x.csv")) is None
    assert "開いている文書がありません" in "".join(app.Console.warnings)


def test_macro_warns_when_there_are_no_spaces(monkeypatch, tmp_path):
    macro, app = _load_macro(monkeypatch, Doc([Obj("Wall", "壁", IfcType="Wall")]))
    assert macro["export_floor_area"](str(tmp_path / "x.csv")) is None
    assert "Arch Space" in "".join(app.Console.warnings)


def test_macro_reports_rooms_without_area(monkeypatch, tmp_path):
    doc = Doc([_space("Space", "リビング", 16.0), Obj("Space001", "物置", IfcType="Space")])
    macro, app = _load_macro(monkeypatch, doc)
    macro["export_floor_area"](str(tmp_path / "床面積.csv"))
    assert "物置" in "".join(app.Console.warnings)


def test_macro_default_path_follows_the_saved_file(monkeypatch, tmp_path):
    doc = Doc([])
    doc.FileName = str(tmp_path / "住宅.FCStd")
    doc.Label = "住宅"
    macro, _ = _load_macro(monkeypatch, doc)
    assert macro["_default_path"](doc, ".xlsx") == str(tmp_path / "住宅_床面積.xlsx")

    unsaved = Doc([])
    unsaved.FileName = ""
    unsaved.Label = "無題"
    path = macro["_default_path"](unsaved, ".csv")
    assert path.endswith("無題_床面積.csv")
    assert pathlib.Path(path).parent.is_dir()


def test_macro_finds_the_package_from_its_own_location(monkeypatch, tmp_path):
    macro, _ = _load_macro(monkeypatch, Doc([]))
    roots = list(macro["_candidate_roots"]())
    assert str(MACRO.parents[1]) in roots
    macro["_import_package"]()  # 例外が出なければよい


def test_macro_unsupported_extension_is_reported(monkeypatch, tmp_path):
    macro, app = _load_macro(monkeypatch, Doc([_space("Space", "リビング", 16.0)]))
    assert macro["export_floor_area"](str(tmp_path / "床面積.txt")) is None
    assert "書き出せませんでした" in "".join(app.Console.warnings)
