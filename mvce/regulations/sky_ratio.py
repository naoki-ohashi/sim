"""天空率（法56条7項、令135条の5〜11）.

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

**算定位置は令135条の9・10・11 に合わせました**（`sky_positions.py`）。
基準線・間隔・想定半球の中心の高さは条文どおりです。

**天空図の投影方法はまだ近似です。** 正射影（ρ = cos仰角）で方位を等分
サンプリングしており、告示が定める作図方法そのものではありません。また
令135条の5 の Ab は「建築物**及びその敷地の地盤**」ですが、地盤の投影は
まだ見ていません（平坦地では寄与しません）。Ps と Pr を同じ方法で比較して
いるので相対比較の一貫性はありますが、天空率の絶対値を認定ソフトの数値と
突き合わせる用途には使えません。確認申請には使用できません
（docs/mvce/disclaimer.md）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point as ShPoint
from shapely.ops import nearest_points

from ..geometry import Point
from ..massing import Block
from ..site import Site
from .height_field import buildable_ring_at_height, max_relevant_height
from .sky_positions import MeasurementPosition, all_positions

RAY_LENGTH = 1.0e5
# 測定点を境界線から極わずか外へ出す。境界線上ちょうどだと、後退0の壁面と
# 距離0になって仰角の計算が不安定になるため。
MEASUREMENT_EPSILON_M = 1.0e-3


@dataclass
class SkyRatioCheck:
    point: Point
    kind: str          # "road" | "adjacent" | "north"
    edge_index: int
    z_m: float         # 想定半球の中心の高さ（令135条の9〜11）
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


def measurement_points(
    site: Site, max_interval_m: float | None = None
) -> list[MeasurementPosition]:
    """算定位置（令135条の9・10・11）。詳細は `sky_positions.py`。

    **道路は前面道路の反対側の境界線上、隣地は境界線から16m（12.4m）外側、
    北側は真北方向に4m（8m）外側**で、間隔も規制ごとに違います。
    以前はすべて境界線上・2m間隔でしたが、条文と違っていました。

    `max_interval_m` は条文の間隔をさらに細かくしたいときだけ使います
    （粗くはできません）。
    """
    return all_positions(site, max_interval_m)


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
          max_interval_m: float | None = None, n_azimuth: int = 120,
          azimuth_offset_ratio: float = 0.0) -> list[SkyRatioCheck]:
    """すべての算定位置で Ps ≧ Pr を確認する。

    Ps と Pr は**同じ方位**でサンプリングします。比較の一貫性が保たれれば
    よいので、`azimuth_offset_ratio` はどちらにも同じ値が使われます。

    想定半球の中心の高さは位置ごとに違います（道路は路面の中心、隣地・
    北側は敷地の地盤面。いずれも令135条の9〜11 の高低差みなしを含む）。
    """
    if reference is None:
        reference = reference_building(site)
    results = []
    for position in measurement_points(site, max_interval_m):
        p3 = position.point3
        results.append(SkyRatioCheck(
            point=position.point, kind=position.kind,
            edge_index=position.edge_index, z_m=position.z_m,
            ps=sky_ratio_percent(p3, proposed, n_azimuth, azimuth_offset_ratio),
            pr=sky_ratio_percent(p3, reference, n_azimuth, azimuth_offset_ratio),
        ))
    return results


def all_ok(checks: list[SkyRatioCheck]) -> bool:
    return all(c.ok for c in checks)
