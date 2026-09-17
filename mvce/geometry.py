"""幾何ユーティリティ.

座標系: +X = 図面の右, +Y = 図面の上（単位m）。
**真北は +Y とは限りません**。敷地図は測量座標や任意の向きで作られるため、
真北の方向は `north.py` の `NorthReference` で別途指定します。斜線制限
（北側斜線）と日影計算はこの真北を基準に行います。
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

Point = tuple[float, float]

BIG = 1.0e6  # 実在する敷地より十分大きい値（半平面を多角形で表すのに使う）


def polygon_signed_area(points: Sequence[Point]) -> float:
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def polygon_area(points: Sequence[Point]) -> float:
    return abs(polygon_signed_area(points))


def ensure_ccw(points: Sequence[Point]) -> list[Point]:
    """反時計回り（数学の慣例）に揃える。"""
    pts = list(points)
    return pts if polygon_signed_area(pts) >= 0 else pts[::-1]


def dedupe_ring(points: Sequence[Point], tol: float = 1e-9) -> list[Point]:
    """重複した頂点と、閉じるための終点の重複を取り除く。"""
    out: list[Point] = []
    for p in points:
        if not out or abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append((float(p[0]), float(p[1])))
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) <= tol and abs(out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def edge_direction(p1: Point, p2: Point) -> Point:
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("長さ0の辺があります")
    return (dx / length, dy / length)


def interior_normal(p1: Point, p2: Point) -> Point:
    """反時計回りの多角形で、辺 p1->p2 の内側を向く単位法線。"""
    dx, dy = edge_direction(p1, p2)
    return (-dy, dx)


def outward_normal(p1: Point, p2: Point) -> Point:
    nx, ny = interior_normal(p1, p2)
    return (-nx, -ny)


def point_line_distance(point: Point, p1: Point, p2: Point) -> float:
    """点から直線 p1-p2 までの符号なし垂直距離（線分ではなく無限直線）。"""
    dx, dy = edge_direction(p1, p2)
    return abs((point[0] - p1[0]) * -dy + (point[1] - p1[1]) * dx)


def signed_distance_to_line(point: Point, p1: Point, p2: Point, normal: Point) -> float:
    """`normal` 側を正とする符号付き距離。"""
    return (point[0] - p1[0]) * normal[0] + (point[1] - p1[1]) * normal[1]


def offset_line(p1: Point, p2: Point, distance: float, normal: Point) -> tuple[Point, Point]:
    """直線を `normal` 方向へ `distance` だけ平行移動する。"""
    nx, ny = normal
    return ((p1[0] + distance * nx, p1[1] + distance * ny),
            (p2[0] + distance * nx, p2[1] + distance * ny))


def _halfplane_polygon(p1: Point, p2: Point, normal: Point, offset: float) -> Polygon:
    """半平面 {x : normal・(x - (p1 + offset*normal)) >= 0} を表す巨大な矩形。"""
    dx, dy = edge_direction(p1, p2)
    nx, ny = normal
    sx, sy = p1[0] + offset * nx, p1[1] + offset * ny
    a = (sx - BIG * dx, sy - BIG * dy)
    b = (sx + BIG * dx, sy + BIG * dy)
    c = (b[0] + BIG * nx, b[1] + BIG * ny)
    d = (a[0] + BIG * nx, a[1] + BIG * ny)
    return Polygon([a, b, c, d])


def offset_polygon_by_edge_distances(
    points: Sequence[Point], distances: Sequence[float]
) -> Polygon | None:
    """各辺 i を distances[i] だけ内側へ下げた領域。

    辺ごとの半平面の共通部分として求めます（距離は線分ではなく辺を含む
    無限直線から測ります）。斜線制限のセットバックはこの measure が正しく、
    建築確認の実務でもこの取り方をします。距離が0以下の辺は制約なしとして
    無視します。すべて満たす領域が無い場合は None。
    """
    pts = ensure_ccw(dedupe_ring(points))
    region: Polygon | None = Polygon(pts)
    for i, d in enumerate(distances):
        if d is None or d <= 0:
            continue
        p1, p2 = pts[i], pts[(i + 1) % len(pts)]
        region = region.intersection(_halfplane_polygon(p1, p2, interior_normal(p1, p2), d))
        if region.is_empty:
            return None
    if region is None or region.is_empty or region.area <= 1e-9:
        return None
    if region.geom_type != "Polygon":
        region = max(region.geoms, key=lambda g: g.area)
    return orient(region, sign=1.0)


def polygon_to_ring(poly: Polygon) -> list[Point]:
    return dedupe_ring([(float(x), float(y)) for x, y, *_ in poly.exterior.coords])


def bounds_of(points: Iterable[Point]) -> tuple[float, float, float, float]:
    pts = list(points)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)
