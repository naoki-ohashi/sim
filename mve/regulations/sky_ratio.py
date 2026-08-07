"""天空率（法56条7項、令135条の5〜9）.

斜線制限に適合しない建築物でも、天空率が「適合建築物」（斜線制限ぎりぎりの
建物）の天空率以上であれば建てられる、という代替規定です。

    Ps（計画建築物の天空率） ≧ Pr（適合建築物の天空率）

を、道路・隣地・北側それぞれの測定点すべてで満たす必要があります。

## 壁面後退距離との関係

壁面後退距離（`Boundary.wall_setback_m`）は2つの意味で効きます。

1. 適合建築物の形が変わる（後退緩和が働くので適合建築物が高くなる）
2. 計画建築物が境界線から離れるので、測定点から見た見かけの大きさが減る

そのため、後退距離を入れるほど天空率は有利になるのが普通です。MVEでは
後退距離を入力値として持ち、両方に反映します。

## 実装上の注意

天空図の投影方法と測定点の配置は、内部で一貫した近似（正射影・境界線上の
等間隔配置）を使っています。**告示が定める厳密な測定点設置規則には準拠して
いません。** Ps と Pr を同じ方法で比較しているので相対比較の一貫性はあり
ますが、天空率の絶対値を認定ソフトの数値と突き合わせる用途には使えません。
確認申請には使用できません（docs/mve/disclaimer.md）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point as ShPoint
from shapely.ops import nearest_points

from ..geometry import Point, edge_direction, interior_normal
from ..massing import Block
from ..site import Site
from .height_field import buildable_ring_at_height, max_relevant_height
from .north_slant import applies as north_applies, north_edges

RAY_LENGTH = 1.0e5
# 測定点を境界線から極わずか外へ出す。境界線上ちょうどだと、後退0の壁面と
# 距離0になって仰角の計算が不安定になるため。
MEASUREMENT_EPSILON_M = 1.0e-3


@dataclass
class SkyRatioCheck:
    point: Point
    kind: str          # "road" | "adjacent" | "north"
    edge_index: int
    ps: float
    pr: float

    @property
    def ok(self) -> bool:
        return self.ps >= self.pr - 1e-9

    @property
    def margin(self) -> float:
        return self.ps - self.pr


def _ray_entry_distance(origin: Point, azimuth_deg: float, footprint) -> float | None:
    """方位 `azimuth_deg` の半直線が平面形状に入るまでの距離（図面座標の方位）。"""
    rad = math.radians(azimuth_deg)
    far = (origin[0] + RAY_LENGTH * math.sin(rad), origin[1] + RAY_LENGTH * math.cos(rad))
    inter = LineString([origin, far]).intersection(footprint)
    if inter.is_empty:
        return None
    _, nearest = nearest_points(ShPoint(origin), inter)
    d = ShPoint(origin).distance(nearest)
    return d if d > 1e-9 else None


def silhouette_elevation_rad(point3: tuple[float, float, float], azimuth_deg: float,
                             blocks: list[Block]) -> float:
    x, y, z0 = point3
    highest = 0.0
    for block in blocks:
        if block.z_top <= z0:
            continue
        r = _ray_entry_distance((x, y), azimuth_deg, block.footprint)
        if r is None:
            continue
        elevation = math.atan2(block.z_top - z0, r)
        if elevation > highest:
            highest = elevation
    return highest


def sky_ratio_percent(point3: tuple[float, float, float], blocks: list[Block],
                      n_azimuth: int = 180) -> float:
    """天空率(%)。正射影（ρ = cos仰角）でサンプリングする。"""
    dphi = 2 * math.pi / n_azimuth
    total = 0.0
    for i in range(n_azimuth):
        elevation = silhouette_elevation_rad(point3, i * 360.0 / n_azimuth, blocks)
        rho = math.cos(elevation)
        total += 0.5 * rho * rho * dphi
    return total / math.pi * 100.0


def measurement_points(site: Site, interval_m: float = 2.0) -> list[tuple[Point, str, int]]:
    """各規制対象の境界線に沿った測定点（点, 種別, 辺インデックス）。

    道路は「道路の反対側の境界線」上、隣地・北側は境界線上に置きます。
    """
    result: list[tuple[Point, str, int]] = []
    north_set = set(north_edges(site)) if north_applies(site) else set()

    for idx, edge in enumerate(site.edges):
        if edge.kind.value == "none":
            continue
        if edge.is_road:
            kind = "road"
            shift = edge.road_width_m
        elif idx in north_set:
            kind = "north"
            shift = 0.0
        else:
            kind = "adjacent"
            shift = 0.0

        nx, ny = interior_normal(edge.p1, edge.p2)
        offset = shift + MEASUREMENT_EPSILON_M
        p1 = (edge.p1[0] - offset * nx, edge.p1[1] - offset * ny)
        p2 = (edge.p2[0] - offset * nx, edge.p2[1] - offset * ny)
        dx, dy = edge_direction(p1, p2)
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        count = max(2, math.ceil(length / interval_m) + 1)
        for k in range(count):
            t = length * k / (count - 1)
            result.append(((p1[0] + t * dx, p1[1] + t * dy), kind, idx))
    return result


def reference_building(site: Site, n_layers: int = 20) -> list[Block]:
    """適合建築物（斜線制限ぎりぎりの建物）を階段状に近似する。"""
    top = max_relevant_height(site)
    if top <= 0:
        return []
    blocks: list[Block] = []
    previous = 0.0
    for k in range(n_layers):
        z_top = top * (k + 1) / n_layers
        # 層の下端での制限で作る（層の途中より大きめ＝天空を塞ぐ側に安全）
        ring = buildable_ring_at_height(site, previous)
        if ring and len(ring) >= 3:
            from shapely.geometry import Polygon
            poly = Polygon(ring)
            if poly.area > 1e-6:
                blocks.append(Block(footprint=poly, z_bottom=previous, z_top=z_top))
        previous = z_top
    return blocks


def check(site: Site, proposed: list[Block], reference: list[Block] | None = None,
          interval_m: float = 2.0, n_azimuth: int = 120,
          measurement_height_m: float = 0.0) -> list[SkyRatioCheck]:
    """すべての測定点で Ps ≧ Pr を確認する。"""
    if reference is None:
        reference = reference_building(site)
    results = []
    for point, kind, edge_index in measurement_points(site, interval_m):
        p3 = (point[0], point[1], measurement_height_m)
        results.append(SkyRatioCheck(
            point=point, kind=kind, edge_index=edge_index,
            ps=sky_ratio_percent(p3, proposed, n_azimuth),
            pr=sky_ratio_percent(p3, reference, n_azimuth),
        ))
    return results


def all_ok(checks: list[SkyRatioCheck]) -> bool:
    return all(c.ok for c in checks)
