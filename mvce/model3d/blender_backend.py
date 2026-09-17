"""`blender` バックエンド — Blenderの `bpy` によるメッシュ化.

**`bpy` は通常のpipパッケージではありません。** Blender本体に同梱された
Pythonから実行するか、対応するBlenderバージョン・OS・Pythonバージョンの
組み合わせでのみ配布されている `bpy` ホイールを使う必要があります。

    blender --background --python <このバックエンドを呼ぶスクリプト>

`import bpy` が失敗したら `Model3DBackendUnavailable` を送出するだけで、
それ以外は何もしません（原則H）。

## 対応しているもの・対応していないもの

- 各階の外周（穴なし）を `solid.triangulate_simple_polygon` でファン状に
  三角形分割し、`bpy.data.meshes` として押し出す
- **内側の穴（中庭等）には対応していません。** Blenderのメッシュ面は穴を
  直接表現できず、ブーリアン演算で削るのが正攻法ですが、MVCE3では
  未実装です（`mesh` バックエンドと同じ制限）。穴があった床は
  `BlenderBuildResult.holes_ignored` に数えます
- `.blend` / `.glb` / `.gltf` / `.obj` への書き出し

## この環境での検証状況

このリポジトリの自動テスト環境には Blender（`bpy`）が入っていないため、
**このモジュールは `bpy` の公開APIの仕様に基づいて書いていますが、実際に
Blenderで実行して確認できていません。** テストで検証できるのは
「`bpy` が無いときに `Model3DBackendUnavailable` が正しく送出されること」
までです（`tests/mvce/test_model3d.py`）。特にOBJ書き出しのオペレーター名は
Blenderのバージョンで変わる（4.0で `wm.obj_export` に変更）ため、実行する
Blenderのバージョンで確認してください。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..floors import FloorSlab
from .errors import Model3DBackendUnavailable
from .solid import Point2, triangulate_simple_polygon


def _import_bpy():
    try:
        import bpy  # type: ignore
    except ImportError as exc:
        raise Model3DBackendUnavailable(
            "bpy（Blenderのpythonモジュール）が見つかりません。"
            "`blender --background --python <スクリプト>` の形でBlenderから"
            "実行するか、対応する `bpy` パッケージを導入してから実行して"
            "ください。詳細は mvce/model3d/blender_backend.py の docstring "
            "を参照してください。"
        ) from exc
    return bpy


@dataclass
class BlenderBuildResult:
    object_count: int
    holes_ignored: int


def _ring_of(polygon) -> list[Point2]:
    coords = list(polygon.exterior.coords)
    if coords and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def build_scene(floors: list[FloorSlab], collection_name: str = "MVCE3") -> BlenderBuildResult:
    """階のリストから Blender シーンにメッシュを組み立てる。"""
    bpy = _import_bpy()

    root = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(root)

    object_count = 0
    holes_ignored = 0
    for floor in floors:
        for i, footprint in enumerate(floor.footprints):
            if footprint.interiors:
                holes_ignored += 1
            ring = _ring_of(footprint)
            n = len(ring)
            if n < 3:
                continue
            tris = triangulate_simple_polygon(ring)

            verts = [(x, y, floor.z_bottom) for x, y in ring]
            verts += [(x, y, floor.z_top) for x, y in ring]

            faces: list[tuple[int, ...]] = []
            faces.extend((a, c, b) for a, b, c in tris)                  # 底面（下向き）
            faces.extend((a + n, b + n, c + n) for a, b, c in tris)      # 天端（上向き）
            for k in range(n):
                j = (k + 1) % n
                faces.append((k, j, j + n, k + n))                       # 側面

            mesh = bpy.data.meshes.new(f"{collection_name}_floor{floor.level + 1}_{i}")
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            obj = bpy.data.objects.new(f"{floor.label_ja}_{i}", mesh)
            root.objects.link(obj)
            object_count += 1

    return BlenderBuildResult(object_count, holes_ignored)


def save_scene(path: str) -> None:
    """`.blend` / `.glb` / `.gltf` / `.obj` の拡張子に応じて書き出す。"""
    bpy = _import_bpy()
    lower = path.lower()
    if lower.endswith(".blend"):
        bpy.ops.wm.save_as_mainfile(filepath=path)
    elif lower.endswith((".glb", ".gltf")):
        bpy.ops.export_scene.gltf(filepath=path)
    elif lower.endswith(".obj"):
        if hasattr(bpy.ops.wm, "obj_export"):   # Blender 4.0 以降
            bpy.ops.wm.obj_export(filepath=path)
        else:                                    # Blender 3.x 以前
            bpy.ops.export_scene.obj(filepath=path)
    else:
        raise ValueError(
            f"未対応の拡張子です: {path}"
            "（.blend / .glb / .gltf / .obj のいずれかにしてください）"
        )
