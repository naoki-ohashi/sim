"""建物外郭線とメッシュ（ボクセル最適化の下地）.

処理の順番は次の通りです。

    敷地図 → 壁面後退線 → 建物外郭線 → メッシュ

1. **壁面後退線**: 各境界線から `wall_setback_m` だけ内側に入った線。
   天空率の検討でも斜線制限の後退緩和でも使う、設計上の基準線です。
2. **建物外郭線**: 壁面後退線で囲まれた領域。ここが建物を置ける範囲に
   なります。
3. **メッシュ**: 外郭線をX方向・Y方向の幅で刻んだ格子。1マスが
   「X × Y × 階高」のボックス1個分の底面になります。

メッシュの向きは既定では図面座標のXY軸ですが、`angle_deg` を与えると
その角度に回した格子を作れます（道路に平行に割り付けたい場合など）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.affinity import rotate
from shapely.geometry import Polygon, box

from .geometry import Point, offset_polygon_by_edge_distances, polygon_to_ring
from .site import Site

MIN_CELL_SIZE_M = 0.5


@dataclass
class MeshCell:
    """メッシュの1マス。ボクセル1本分の柱の底面。"""

    index: int
    col: int
    row: int
    polygon: Polygon
    center: Point
    area_m2: float
    height_limit_m: float = math.inf   # 斜線制限などによる上限
    max_floors: int = 0                # 上限内に収まる階数

    @property
    def corners(self) -> list[Point]:
        return polygon_to_ring(self.polygon)


@dataclass
class BuildableArea:
    """建物を置ける範囲と、そこに張ったメッシュ。"""

    site: Site
    setback_ring: list[Point]          # 壁面後退線
    outline: Polygon                   # 建物外郭線
    cells: list[MeshCell] = field(default_factory=list)
    cell_size_x_m: float = 3.0
    cell_size_y_m: float = 3.0
    angle_deg: float = 0.0

    @property
    def outline_area_m2(self) -> float:
        return self.outline.area

    @property
    def cell_area_m2(self) -> float:
        return self.cell_size_x_m * self.cell_size_y_m


def wall_setback_ring(site: Site) -> list[Point] | None:
    """壁面後退線（各境界線から wall_setback_m 内側）。"""
    distances = [e.wall_setback_m for e in site.edges]
    if all(d <= 0 for d in distances):
        return list(site.points)
    poly = offset_polygon_by_edge_distances(site.points, distances)
    return polygon_to_ring(poly) if poly is not None else None


def building_outline(site: Site) -> Polygon | None:
    """建物外郭線（壁面後退線で囲まれた範囲）。"""
    ring = wall_setback_ring(site)
    if ring is None or len(ring) < 3:
        return None
    poly = Polygon(ring)
    return poly if poly.is_valid and poly.area > 1e-9 else None


def _largest_polygon(geom) -> Polygon | None:
    """交差結果から多角形を1つ取り出す（複数に割れたら最大のもの）。"""
    if geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return geom if geom.area > 1e-12 else None
    polygons = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    if not polygons:
        return None
    largest = max(polygons, key=lambda g: g.area)
    return largest if largest.area > 1e-12 else None


def build_mesh(
    site: Site,
    cell_size_x_m: float = 3.0,
    cell_size_y_m: float = 3.0,
    angle_deg: float = 0.0,
    coverage_threshold: float = 0.5,
) -> BuildableArea | None:
    """建物外郭線にメッシュを張る。

    `coverage_threshold` は「マスのうち外郭線に入っている面積の割合が
    これ以上ならそのマスを採用する」というしきい値です。既定0.5は、
    半分以上入っていれば使うという意味で、外形の凹凸を素直に拾います。
    """
    if cell_size_x_m < MIN_CELL_SIZE_M or cell_size_y_m < MIN_CELL_SIZE_M:
        raise ValueError(f"メッシュの幅は{MIN_CELL_SIZE_M}m以上にしてください")

    outline = building_outline(site)
    if outline is None:
        return None
    ring = wall_setback_ring(site) or list(site.points)

    # 回転メッシュは、外郭線を逆回転してから軸平行に刻み、最後に戻す
    pivot = outline.centroid
    work = rotate(outline, -angle_deg, origin=pivot) if angle_deg else outline
    minx, miny, maxx, maxy = work.bounds

    cells: list[MeshCell] = []
    n_cols = max(1, math.ceil((maxx - minx) / cell_size_x_m))
    n_rows = max(1, math.ceil((maxy - miny) / cell_size_y_m))
    index = 0
    for row in range(n_rows):
        for col in range(n_cols):
            x0 = minx + col * cell_size_x_m
            y0 = miny + row * cell_size_y_m
            cell_box = box(x0, y0, x0 + cell_size_x_m, y0 + cell_size_y_m)
            clipped = _largest_polygon(cell_box.intersection(work))
            if clipped is None or clipped.area < cell_box.area * coverage_threshold:
                continue
            # 外郭線からはみ出した部分は落とす。建物は建てられる範囲に収まる。
            actual = rotate(clipped, angle_deg, origin=pivot) if angle_deg else clipped
            centroid = actual.centroid
            cells.append(MeshCell(
                index=index, col=col, row=row, polygon=actual,
                center=(centroid.x, centroid.y), area_m2=actual.area,
            ))
            index += 1

    return BuildableArea(
        site=site, setback_ring=ring, outline=outline, cells=cells,
        cell_size_x_m=cell_size_x_m, cell_size_y_m=cell_size_y_m, angle_deg=angle_deg,
    )


def assign_height_limits(area: BuildableArea, use_sky_ratio: bool = False) -> None:
    """各マスに斜線制限による高さ上限と、そこに収まる階数を設定する。

    マスの中で最も厳しい点（4隅と中心を見る）を採用します。マス全体が
    制限を満たすようにするための安全側の取り方です。
    """
    from .regulations.height_field import height_limit_at

    floor_h = area.site.floor_height_m
    for cell in area.cells:
        probes = cell.corners + [cell.center]
        limit = min(height_limit_at(area.site, p, use_sky_ratio=use_sky_ratio) for p in probes)
        cell.height_limit_m = limit
        cell.max_floors = 0 if limit <= 0 else (
            10_000 if math.isinf(limit) else int(math.floor(limit / floor_h + 1e-9))
        )
