"""`freecad` バックエンド — FreeCADの `Part` モジュールによる立体化.

**FreeCAD は pip パッケージではありません。** `import FreeCAD` が通るのは、
FreeCAD本体（アプリケーション）がインストールされ、かつその `FreeCAD` /
`Part` モジュールが見える Python インタプリタから実行したときだけです。

- Windows/Mac: 公式インストーラでFreeCADを入れ、同梱の
  `bin/python.exe`（または `bin/python3`）から実行する
- Linux: `apt install freecad`（Debian/Ubuntu）または
  `conda install -c conda-forge freecad` のあと、対応するPythonから実行
- どの場合も、通常のシステムPythonから `pip install FreeCAD` はできません

このモジュールは `import FreeCAD` が失敗したら `Model3DBackendUnavailable`
を送出するだけで、それ以外は何もしません（原則H — 使えないのに黙って
別のバックエンドへ切り替えたり、不完全な結果を返したりしません）。

## `mesh` バックエンドとの違い

各階の外周だけでなく**内側の穴（中庭等）も正しく扱います**
（`Part.Face([外周ワイヤ] + [内側ワイヤ...])` が穴あき面を直接表現できる
ため）。`.FCStd`・`.step`・`.ifc` への書き出しに対応します。

## この環境での検証状況

このリポジトリの自動テスト環境にはFreeCADが入っていないため、
**このモジュールはFreeCADの公開APIの仕様に基づいて書いていますが、
実際にFreeCADで実行して確認できていません。** テストで検証できるのは
「FreeCADが無いときに `Model3DBackendUnavailable` が正しく送出されること」
までです（`tests/mvce/test_model3d.py`）。FreeCADが使える環境で試した際に
不具合があれば、`Part.Face` / `extrude` の呼び出し方を見直してください。
"""
from __future__ import annotations

from ..floors import FloorSlab
from .errors import Model3DBackendUnavailable


def _import_freecad():
    try:
        import FreeCAD  # type: ignore
        import Part  # type: ignore
    except ImportError as exc:
        raise Model3DBackendUnavailable(
            "FreeCAD が見つかりません。FreeCAD本体をインストールし、"
            "同梱のPython（例: FreeCAD/bin/python）から実行するか、"
            "FreeCADが見えるように環境を設定してから実行してください。"
            "詳細は mvce/model3d/freecad_backend.py の docstring を参照してください。"
        ) from exc
    return FreeCAD, Part


def _ring_without_closing_point(coords) -> list[tuple[float, float]]:
    coords = list(coords)
    if coords and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def _wire_from_ring(FreeCAD, Part, coords: list[tuple[float, float]]):
    points = [FreeCAD.Vector(x, y, 0.0) for x, y in coords]
    points.append(points[0])  # makePolygon は閉じたリストを要求する
    return Part.makePolygon(points)


def build_freecad_document(floors: list[FloorSlab], doc_name: str = "MVCE3"):
    """階のリストから FreeCAD ドキュメントを組み立てて返す（保存は呼び出し側）。"""
    FreeCAD, Part = _import_freecad()

    doc = FreeCAD.newDocument(doc_name)
    for floor in floors:
        for i, footprint in enumerate(floor.footprints):
            outer = _wire_from_ring(
                FreeCAD, Part, _ring_without_closing_point(footprint.exterior.coords))
            inner_wires = [
                _wire_from_ring(FreeCAD, Part, _ring_without_closing_point(ring.coords))
                for ring in footprint.interiors
            ]
            face = Part.Face([outer, *inner_wires])
            solid = face.extrude(FreeCAD.Vector(0, 0, floor.z_top - floor.z_bottom))
            solid.translate(FreeCAD.Vector(0, 0, floor.z_bottom))
            obj = doc.addObject("Part::Feature", f"floor_{floor.level + 1}_{i}")
            obj.Shape = solid
            obj.Label = floor.label_ja
    doc.recompute()
    return doc


def save_document(doc, path: str) -> None:
    """`.FCStd` / `.step` / `.stp` / `.ifc` の拡張子に応じて書き出す。"""
    lower = path.lower()
    if lower.endswith(".fcstd"):
        doc.saveAs(path)
        return
    if lower.endswith((".step", ".stp")):
        import Part  # type: ignore
        shapes = [obj.Shape for obj in doc.Objects if hasattr(obj, "Shape")]
        Part.export(shapes, path)
        return
    if lower.endswith(".ifc"):
        try:
            import importIFC  # type: ignore
        except ImportError as exc:
            raise Model3DBackendUnavailable(
                "IFC書き出しには FreeCAD の Import ワークベンチ（importIFC。"
                "通常はBIM/Archワークベンチと同梱）が要ります。"
            ) from exc
        importIFC.export([obj for obj in doc.Objects if hasattr(obj, "Shape")], path)
        return
    raise ValueError(
        f"未対応の拡張子です: {path}（.FCStd / .step / .ifc のいずれかにしてください）"
    )
