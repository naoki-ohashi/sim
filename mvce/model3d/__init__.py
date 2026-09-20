"""MVCE3 3Dモデル化（`docs/mvce/mvce3_design_spec.md` 4章）.

`OptimizeResult`（最大ボリューム計算の結果 — `solvers/optimizer.optimize()`
の戻り値）から、階ごとの立体モデルを組み立てて書き出します。3通りの
バックエンドがあり、`build_model3d(..., backend=)` で選びます。

| backend | 実体 | 中抜き（穴） | 追加インストール | この環境での検証 |
|---|---|---|---|---|
| `mesh`（既定） | 自前の耳切り法によるOBJ書き出し | 非対応（外周のみ） | 不要 | **書き出しまで自動テスト済み** |
| `freecad` | FreeCADの `Part` モジュール | **対応** | FreeCAD本体 | 未検証（API仕様どおりに実装） |
| `blender` | Blenderの `bpy` | 非対応（外周のみ） | Blender本体（または対応する`bpy`パッケージ） | 未検証（API仕様どおりに実装） |

**既定が `mesh` である理由**: FreeCAD・Blenderはpipパッケージではなく
別途インストールが要るアプリケーションで、このリポジトリの実行・テスト
環境にはどちらも入っていません。`mesh` だけがこのリポジトリの自動テストで
実際に書き出しまで検証できます。FreeCAD/Blenderのバックエンドはそれぞれの
公開Python APIの仕様どおりに書いていますが、**この環境で実行して確認は
できていません**（原則F・正直に書く。`freecad_backend.py` /
`blender_backend.py` の docstring 参照）。利用者の側でFreeCAD/Blenderが
使える環境なら、そちらのバックエンドを明示的に選んでください。
"""
from __future__ import annotations

from ..floors import FloorSlab, floors_from_blocks
from ..solvers.optimizer import OptimizeResult
from .errors import Model3DBackendUnavailable

BACKENDS = ("mesh", "freecad", "blender")


def build_model3d(result: OptimizeResult, path: str, backend: str = "mesh") -> dict:
    """`OptimizeResult` から3Dモデルを組み立て、`path` に書き出す。

    戻り値は `{"backend": ..., "floor_count": ..., ...}`（バックエンドごとに
    追加の統計を含みます）。`backend="freecad"` / `"blender"` で該当ツールが
    実行環境に無い場合は `Model3DBackendUnavailable` を送出します
    （黙って `mesh` にフォールバックすることはしません）。
    """
    if backend not in BACKENDS:
        raise ValueError(
            f"backend は {'/'.join(BACKENDS)} のいずれかにしてください: {backend!r}"
        )

    floors = floors_from_blocks(result.blocks, result.site.floor_height_m)

    if backend == "mesh":
        from .mesh_backend import build_obj
        stats = build_obj(floors, path)
        return {
            "backend": "mesh",
            "floor_count": len(floors),
            "vertex_count": stats.vertex_count,
            "triangle_count": stats.triangle_count,
            "holes_ignored": stats.holes_ignored,
        }

    if backend == "freecad":
        from .freecad_backend import build_freecad_document, save_document
        doc = build_freecad_document(floors)
        save_document(doc, path)
        return {"backend": "freecad", "floor_count": len(floors)}

    from .blender_backend import build_scene, save_scene
    stats = build_scene(floors)
    save_scene(path)
    return {
        "backend": "blender",
        "floor_count": len(floors),
        "object_count": stats.object_count,
        "holes_ignored": stats.holes_ignored,
    }


__all__ = ["build_model3d", "BACKENDS", "Model3DBackendUnavailable", "FloorSlab"]
