"""FreeCAD（Arch/BIM）の部屋から床面積表を作るツール。

使い方は2通りあります。

* **FreeCADの中でマクロとして実行する**（`freecad/床面積集計.FCMacro`）。
  開いている文書の `Arch Space` から床面積を集計してExcel/CSVに出力します。
* **FreeCADなしで `.FCStd` を直接読む**（`freecad-floor-area` コマンド）。
  保存済みファイルに記録されている面積の値を読み出します。

床面積は `Shape.Area`（立体の全表面積）ではなく、`Space` が持つ
`Area` プロパティ（水平投影の床面積）を使います。詳しくは
`docs/freecad_floor_area.md` を参照してください。
"""
from .rooms import Room, collect_rooms, floor_area_from_shape, is_space, total_area_m2
from .table import build_table
from .export import ExportError, write_area_table

__all__ = [
    "Room",
    "collect_rooms",
    "floor_area_from_shape",
    "is_space",
    "total_area_m2",
    "build_table",
    "write_area_table",
    "ExportError",
]
