"""`mesh` バックエンド — 外部ツール不要のOBJ書き出し（既定バックエンド）.

FreeCAD・Blenderのどちらも要らず、このリポジトリの自動テストで実際に
書き出しまで検証できる唯一のバックエンドです（`model3d/__init__.py` 参照）。
各階の外周を押し出し、Wavefront OBJ形式で書き出します。

**中抜き（内側の穴）は外周のみを描画します。** `solid.py` の耳切り法が
穴に対応していないためです。穴があった階数は `MeshBuildResult.holes_ignored`
に数えます。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..floors import FloorSlab
from .solid import Point2, triangulate_simple_polygon


@dataclass
class MeshBuildResult:
    vertex_count: int
    triangle_count: int
    holes_ignored: int      # 中抜きのため外周のみで描画した床の数


def _ring_of(polygon) -> list[Point2]:
    coords = list(polygon.exterior.coords)
    if coords and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def build_obj(
    floors: list[FloorSlab], path: str, *, object_prefix: str = "floor",
) -> MeshBuildResult:
    """階のリストを押し出して Wavefront OBJ に書き出す。"""
    vertices: list[tuple[float, float, float]] = []
    lines: list[str] = []
    triangle_count = 0
    holes_ignored = 0

    def add_vertex(x: float, y: float, z: float) -> int:
        vertices.append((x, y, z))
        return len(vertices)  # OBJ の頂点インデックスは1始まり

    for floor in floors:
        lines.append(f"o {object_prefix}_{floor.level + 1}")
        for footprint in floor.footprints:
            if footprint.interiors:
                holes_ignored += 1
            ring = _ring_of(footprint)
            if len(ring) < 3:
                continue
            tris = triangulate_simple_polygon(ring)

            bottom_ids = [add_vertex(x, y, floor.z_bottom) for x, y in ring]
            top_ids = [add_vertex(x, y, floor.z_top) for x, y in ring]

            for a, b, c in tris:
                lines.append(f"f {bottom_ids[a]} {bottom_ids[c]} {bottom_ids[b]}")
                triangle_count += 1
            for a, b, c in tris:
                lines.append(f"f {top_ids[a]} {top_ids[b]} {top_ids[c]}")
                triangle_count += 1

            n = len(ring)
            for i in range(n):
                j = (i + 1) % n
                lines.append(f"f {bottom_ids[i]} {bottom_ids[j]} {top_ids[j]} {top_ids[i]}")
                triangle_count += 2  # 四角形1枚 = 三角形2枚として数える

    with open(path, "w", encoding="utf-8") as f:
        f.write("# MVCE3 model3d mesh backend (ear-clip fallback; no FreeCAD/Blender required)\n")
        for x, y, z in vertices:
            f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
        for line in lines:
            f.write(line + "\n")

    return MeshBuildResult(len(vertices), triangle_count, holes_ignored)
