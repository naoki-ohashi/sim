"""天空率（法56条7項、令135条の5〜11）.

斜線制限に適合しない建築物でも、天空率が「適合建築物」（斜線制限ぎりぎりの
建物）の天空率以上であれば建てられる、という代替規定です。

    Ps（計画建築物の天空率） ≧ Pr（適合建築物の天空率）

を、道路・隣地・北側それぞれの測定点すべてで満たす必要があります。

## 適合建築物は道路・隣地・北側で別々（令135条の5〜7）

令135条の5（道路高さ制限）・135条の6（隣地高さ制限）・135条の7（北側高さ
制限）は、それぞれ独立に「その高さ制限**だけ**に適合する建築物」を適合
建築物として定義しています。**3つの高さ制限すべての共通部分ではありません**
——道路用の適合建築物は隣地斜線・北側斜線を考慮せず、隣地用・北側用も同様に
他の2つを考慮しません。天空率は、道路の測定点では道路用の適合建築物と、
隣地の測定点では隣地用の適合建築物と、北側の測定点では北側用の適合建築物と、
それぞれ比較します（`reference_buildings` / `check`）。

令135条の8〜11は測定位置に関する規定です。本実装は測定位置を境界線上の
等間隔サンプリングで近似しており（下記「実装上の注意」参照）、告示が定める
厳密な測定点設置位置には準拠していません。

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

from shapely.geometry import LineString, Point as ShPoint, Polygon
from shapely.ops import nearest_points

from ..geometry import Point, edge_direction, interior_normal, offset_polygon_by_edge_distances, polygon_to_ring
from ..massing import Block
from ..site import Site
from . import adjacent_slant, north_slant, road_slant
from .height_field import buildable_ring_at_height, max_relevant_height
from .north_slant import applies as north_applies, north_edges

#: 天空率の区分。道路・隣地・北側それぞれで適合建築物が別々になる（令135条の5〜7）。
SKY_RATIO_KINDS = ("road", "adjacent", "north")

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


def azimuths_deg(n_azimuth: int, offset_ratio: float = 0.0) -> list[float]:
    """サンプリングする方位の一覧。

    `offset_ratio` は刻み幅に対するずらし量です。0.5 にすると、方位が
    0/90/180/270度ちょうどにならないため、**軸に平行なメッシュの面に沿って
    走る光線**という縮退がなくなります。この縮退があると、境界線上の測定点で
    「面をかすめただけ」の光線が当たり判定になり、天空率が跳ねます。
    """
    step = 360.0 / n_azimuth
    return [(i + offset_ratio) * step for i in range(n_azimuth)]


def sky_ratio_percent(point3: tuple[float, float, float], blocks: list[Block],
                      n_azimuth: int = 180, azimuth_offset_ratio: float = 0.0) -> float:
    """天空率(%)。正射影（ρ = cos仰角）でサンプリングする。"""
    dphi = 2 * math.pi / n_azimuth
    total = 0.0
    for azimuth in azimuths_deg(n_azimuth, azimuth_offset_ratio):
        elevation = silhouette_elevation_rad(point3, azimuth, blocks)
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
    """3つの高さ制限すべてに適合する建築物（斜線制限ぎりぎりの建物）を階段状に近似する。

    3D表示用の「斜線制限のエンベロープ」（`io/viewer3d.py`）はこの統合形状を
    使います。Ps/Pr の適合判定そのものには使いません — 判定には道路・隣地・
    北側それぞれ独立の適合建築物（`reference_building_for_kind`）を使います
    （令135条の5〜7）。
    """
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
            poly = Polygon(ring)
            if poly.area > 1e-6:
                blocks.append(Block(footprint=poly, z_bottom=previous, z_top=z_top))
        previous = z_top
    return blocks


def _required_setback_for_kind(site: Site, edge_index: int, height_m: float, kind: str) -> float:
    """`kind`（road/adjacent/north）**だけ**の高さ制限で見た、必要な後退距離。

    令135条の5〜7: 道路・隣地・北側それぞれの適合建築物は、その区分の高さ
    制限だけに従います。他の2区分の辺は、この区分では無制限（後退不要）
    として扱います。
    """
    edge = site.edges[edge_index]
    if kind == "road":
        if not edge.is_road:
            return 0.0
        return road_slant.required_setback_for_height(site, edge_index, height_m)
    if kind == "adjacent":
        if edge.kind.value != "adjacent":
            return 0.0
        return adjacent_slant.required_setback_for_height(site, edge_index, height_m)
    if kind == "north":
        if edge_index not in north_slant.north_edges(site):
            return 0.0
        return north_slant.required_setback_for_height(site, edge_index, height_m)
    raise ValueError(f"unknown sky-ratio kind: {kind!r}")


def buildable_ring_at_height_for_kind(site: Site, height_m: float, kind: str) -> list[Point] | None:
    """高さ `height_m` において `kind` の高さ制限**だけ**を満たす平面領域。"""
    distances = [
        _required_setback_for_kind(site, i, height_m, kind)
        for i in range(len(site.edges))
    ]
    poly = offset_polygon_by_edge_distances(site.points, distances)
    return polygon_to_ring(poly) if poly is not None else None


def _max_height_for_kind(site: Site, kind: str) -> float:
    """`kind` だけの高さ制限で見た、検討する高さの上限（有限値）。

    他の区分に制約されないぶん、`height_field.max_relevant_height`
    （3区分＋絶対高さの共通部分）より高くなることがあります。
    """
    if site.zoning.absolute_height_limit_m is not None:
        return site.zoning.absolute_height_limit_m
    height_fn = {
        "road": road_slant.height_limit_at,
        "adjacent": adjacent_slant.height_limit_at,
        "north": north_slant.height_limit_at,
    }[kind]
    cx = sum(p[0] for p in site.points) / len(site.points)
    cy = sum(p[1] for p in site.points) / len(site.points)
    values = [height_fn(site, p) for p in list(site.points) + [(cx, cy)]]
    finite = [v for v in values if math.isfinite(v)]
    return max(finite) * 1.5 if finite else 120.0


def reference_building_for_kind(site: Site, kind: str, n_layers: int = 20) -> list[Block]:
    """`kind`（road/adjacent/north）の高さ制限だけに適合する適合建築物（令135条の5〜7）。"""
    top = _max_height_for_kind(site, kind)
    if top <= 0:
        return []
    blocks: list[Block] = []
    previous = 0.0
    for k in range(n_layers):
        z_top = top * (k + 1) / n_layers
        ring = buildable_ring_at_height_for_kind(site, previous, kind)
        if ring and len(ring) >= 3:
            poly = Polygon(ring)
            if poly.area > 1e-6:
                blocks.append(Block(footprint=poly, z_bottom=previous, z_top=z_top))
        previous = z_top
    return blocks


def reference_buildings(site: Site, n_layers: int = 20) -> dict[str, list[Block]]:
    """道路・隣地・北側、それぞれ独立の適合建築物（令135条の5〜7）。

    `check` と `sky_index.build_sky_index` は、測定点の区分（`kind`）に
    応じてこの辞書から対応する適合建築物を選び、Ps と比較します。
    """
    return {kind: reference_building_for_kind(site, kind, n_layers) for kind in SKY_RATIO_KINDS}


def check(site: Site, proposed: list[Block], reference: dict[str, list[Block]] | None = None,
          interval_m: float = 2.0, n_azimuth: int = 120,
          measurement_height_m: float = 0.0,
          azimuth_offset_ratio: float = 0.0) -> list[SkyRatioCheck]:
    """すべての測定点で Ps ≧ Pr を確認する。

    道路の測定点は道路用の適合建築物、隣地の測定点は隣地用、北側の測定点は
    北側用と比較します（令135条の5〜7、`reference_buildings`）。Ps と Pr は
    **同じ方位**でサンプリングします。比較の一貫性が保たれればよいので、
    `azimuth_offset_ratio` はどちらにも同じ値が使われます。
    """
    if reference is None:
        reference = reference_buildings(site)
    results = []
    for point, kind, edge_index in measurement_points(site, interval_m):
        p3 = (point[0], point[1], measurement_height_m)
        ref_blocks = reference.get(kind, [])
        results.append(SkyRatioCheck(
            point=point, kind=kind, edge_index=edge_index,
            ps=sky_ratio_percent(p3, proposed, n_azimuth, azimuth_offset_ratio),
            pr=sky_ratio_percent(p3, ref_blocks, n_azimuth, azimuth_offset_ratio),
        ))
    return results


def all_ok(checks: list[SkyRatioCheck]) -> bool:
    return all(c.ok for c in checks)
