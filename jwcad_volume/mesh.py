"""積層ブロックの3D面生成と軸測投影.

`envelope.py` が出力する `list[Block]`（平面形状×高さ範囲の積み重ね）を、
3D表示・アイソメ作図の両方で使える「面(Face)」と「稜線(Edge3D)」に
変換します。ブラウザ表示(output/html3d.py)とJWWへのアイソメ作図
(output/isometric.py)が、ここを共通の土台として使います。

座標系は本パッケージ共通で +X=東 / +Y=真北 / +Z=上（単位m）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .massing import Block

Point3 = tuple[float, float, float]
Point2 = tuple[float, float]

# 連続するブロックの平面形状が「同じ」とみなす面積差の相対許容値
_SAME_FOOTPRINT_REL_TOL = 1e-6


@dataclass
class Face:
    """平面の多角形1枚。`vertices` は外周を一周する順。"""

    vertices: list[Point3]
    kind: str  # "wall"（側面） | "top"（上面） | "bottom"（底面）

    def normal(self) -> Point3:
        """Newellの方法による法線（頂点が同一平面上になくても安定）。"""
        nx = ny = nz = 0.0
        n = len(self.vertices)
        for i in range(n):
            x1, y1, z1 = self.vertices[i]
            x2, y2, z2 = self.vertices[(i + 1) % n]
            nx += (y1 - y2) * (z1 + z2)
            ny += (z1 - z2) * (x1 + x2)
            nz += (x1 - x2) * (y1 + y2)
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length < 1e-12:
            return (0.0, 0.0, 1.0)
        return (nx / length, ny / length, nz / length)


@dataclass
class Edge3D:
    """3Dの線分1本。アイソメ作図で線色を分けるため `kind` を持つ。"""

    p1: Point3
    p2: Point3
    kind: str  # "site" | "outline"（各段の輪郭） | "vertical"（垂直稜線）


def _ring(block: Block) -> list[Point2]:
    """ブロックの外周リング（始点の重複を除いた頂点列）。"""
    coords = [(float(x), float(y)) for x, y, *_ in block.footprint.exterior.coords]
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def merge_identical_footprints(blocks: list[Block]) -> list[Block]:
    """平面形状が同じまま連続するブロックを1つに統合する。

    エンベロープは計算の都合で細かく水平スライスされており、下の方は
    同じ平面形状が何段も続きます。そのまま描くと同じ輪郭線が重なって
    表示・作図が無用に重くなるため、ここでまとめます。
    """
    if not blocks:
        return []
    merged = [Block(footprint=blocks[0].footprint, z_bottom=blocks[0].z_bottom, z_top=blocks[0].z_top)]
    for b in blocks[1:]:
        last = merged[-1]
        same_area = abs(b.footprint.area - last.footprint.area) <= last.footprint.area * _SAME_FOOTPRINT_REL_TOL
        contiguous = abs(b.z_bottom - last.z_top) < 1e-9
        if same_area and contiguous and b.footprint.equals(last.footprint):
            merged[-1] = Block(footprint=last.footprint, z_bottom=last.z_bottom, z_top=b.z_top)
        else:
            merged.append(Block(footprint=b.footprint, z_bottom=b.z_bottom, z_top=b.z_top))
    return merged


def blocks_to_faces(blocks: list[Block], merge: bool = True) -> list[Face]:
    """積層ブロックを面の集合に変換する（側面・上面・底面）。"""
    src = merge_identical_footprints(blocks) if merge else list(blocks)
    faces: list[Face] = []
    for block in src:
        ring = _ring(block)
        if len(ring) < 3:
            continue
        zb, zt = block.z_bottom, block.z_top
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            faces.append(
                Face(
                    vertices=[(x1, y1, zb), (x2, y2, zb), (x2, y2, zt), (x1, y1, zt)],
                    kind="wall",
                )
            )
        faces.append(Face(vertices=[(x, y, zt) for x, y in ring], kind="top"))
        faces.append(Face(vertices=[(x, y, zb) for x, y in reversed(ring)], kind="bottom"))
    return faces


def blocks_to_edges(blocks: list[Block], merge: bool = True) -> list[Edge3D]:
    """積層ブロックを稜線の集合に変換する（各段の輪郭＋垂直稜線）。"""
    src = merge_identical_footprints(blocks) if merge else list(blocks)
    edges: list[Edge3D] = []
    for block in src:
        ring = _ring(block)
        if len(ring) < 3:
            continue
        zb, zt = block.z_bottom, block.z_top
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            edges.append(Edge3D((x1, y1, zt), (x2, y2, zt), "outline"))
            edges.append(Edge3D((x1, y1, zb), (x1, y1, zt), "vertical"))
    return edges


def site_edges(points: list[Point2]) -> list[Edge3D]:
    """敷地境界線（地盤面 z=0）の稜線。"""
    n = len(points)
    return [
        Edge3D((points[i][0], points[i][1], 0.0), (points[(i + 1) % n][0], points[(i + 1) % n][1], 0.0), "site")
        for i in range(n)
    ]


class Axonometric:
    """方位角・仰角を指定した平行投影（軸測投影）。

    `azimuth_deg` は視点の方位（真北から時計回り、本パッケージ共通の
    方位角の取り方）。225なら南西から見下ろす形になり、南面と西面が
    見えます。`elevation_deg` は見下ろす角度で、30前後が一般的な
    アイソメ/アクソメの見え方になります。
    """

    def __init__(self, azimuth_deg: float = 225.0, elevation_deg: float = 30.0) -> None:
        self.azimuth_deg = azimuth_deg
        self.elevation_deg = elevation_deg
        a = math.radians(azimuth_deg)
        e = math.radians(elevation_deg)
        self._ca, self._sa = math.cos(a), math.sin(a)
        self._ce, self._se = math.cos(e), math.sin(e)

    def _rotate_z(self, p: Point3) -> Point3:
        """視点方位が画面奥向きになるようZ軸まわりに回す。"""
        x, y, z = p
        return (x * self._ca - y * self._sa, x * self._sa + y * self._ca, z)

    def project(self, p: Point3) -> Point2:
        """3D座標を投影後の2D座標(m単位)に変換する。"""
        x, y, z = self._rotate_z(p)
        return (x, y * self._se + z * self._ce)

    def depth(self, p: Point3) -> float:
        """視点からの奥行き。大きいほど遠い（描画順の判定に使う）。"""
        _, y, z = self._rotate_z(p)
        return y * self._ce - z * self._se

    def project_edges(self, edges: list[Edge3D]) -> list[tuple[Point2, Point2, str]]:
        return [(self.project(e.p1), self.project(e.p2), e.kind) for e in edges]
