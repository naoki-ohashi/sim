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

from shapely.geometry import LineString, Point as ShPoint, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from ..geometry import Point, offset_polygon_by_edge_distances
from ..massing import Block
from ..site import Site
from ..zoning import UndeterminedRegulation, road_slant_tier
from . import adjacent_slant, north_slant, road_slant
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


# === 適合建築物（令135条の6・7・8）====================================
#
# **規制ごとに別の適合建築物です。** 令135条の6は「道路高さ制限に適合する
# ものとして想定する建築物」、令135条の7は「隣地高さ制限に適合する…」、
# 令135条の8は「北側高さ制限に適合する…」で、それぞれ自分の制限だけを
# 満たす形です。3つを合成した1つの形ではありません。
#
# 従来は斜線制限すべてを合成した1つの形を、道路・隣地・北側のどの測定点でも
# 使っていました。合成した形は各規制単独より小さいので Pr が大きく出て、
# 判定は厳しい側でしたが条文どおりではありません。

REFERENCE_KINDS = ("road", "adjacent", "north")
DEFAULT_REFERENCE_LAYERS = 20

#: 適合建築物の高さの上限を二分探索するときの初期上限(m)
_SEARCH_CEILING_M = 400.0


def _required_setback(site: Site, edge_index: int, height_m: float, kind: str) -> float:
    """規制 `kind` **だけ**で見た、その辺に必要な後退距離。"""
    edge = site.edges[edge_index]
    if kind == "road":
        # 適用距離で頭打ちにしない素の距離。帯の中で斜線どおりの形を作るため
        return road_slant.slant_distance_for_height(site, edge_index, height_m) \
            if edge.is_road else 0.0
    if kind == "adjacent":
        return adjacent_slant.required_setback_for_height(site, edge_index, height_m) \
            if edge.kind.value == "adjacent" else 0.0
    if kind == "north":
        return north_slant.required_setback_for_height(site, edge_index, height_m) \
            if edge_index in north_slant.north_edges(site) else 0.0
    raise ValueError(f"kind は {REFERENCE_KINDS} のいずれかです: {kind!r}")


def applicable_region(site: Site, kind: str) -> BaseGeometry | None:
    """規制 `kind` が適用される範囲（令135条の6・7・8 の「…に限る」）。

    - 道路 … 別表第三（は）欄の適用距離までの帯（前面道路ごとの和集合）
    - 隣地・北側 … その規制の適用がある用途地域なら敷地全体、無ければ None

    条文は**適合建築物も計画建築物も**この範囲内の部分に限ると言っています。
    範囲が空なら両方とも空になり、天空率は 100% 対 100% で自動的に適合します
    （道路高さ制限がそもそも敷地に届いていないのだから、当然の結果です）。
    """
    if kind == "road":
        return _road_applicable_region(site)
    if kind == "adjacent":
        return Polygon(site.points) if adjacent_slant.applies(site) else None
    if kind == "north":
        return Polygon(site.points) if north_slant.applies(site) else None
    raise ValueError(f"kind は {REFERENCE_KINDS} のいずれかです: {kind!r}")


def clip_blocks(blocks: list[Block], region: BaseGeometry | None) -> list[Block]:
    """ブロックを適用範囲で切る。範囲が None なら空。"""
    if region is None:
        return []
    clipped: list[Block] = []
    for block in blocks:
        piece = block.footprint.intersection(region)
        if piece.is_empty:
            continue
        for poly in _polygons(piece):
            if poly.area > 1e-9:
                clipped.append(Block(footprint=poly, z_bottom=block.z_bottom,
                                     z_top=block.z_top))
    return clipped


def _road_applicable_region(site: Site) -> BaseGeometry | None:
    """道路高さ制限が適用される範囲（令135条の6第1項1号の「範囲内の部分」）。

    別表第三（は）欄の適用距離までの帯です。ここを外すと道路高さ制限が
    かからないので、**適合建築物にも計画建築物にもその部分は含めません**。

    この帯を作らずに道路だけの適合建築物を組むと、適用距離の外側が
    「制限なし＝どこまでも高い」形になり、Pr が極端に小さく出て**何でも
    通ってしまいます**。切り落としは省略できません。

    **前面道路が2以上ある敷地では `UndeterminedRegulation` で止まります。**
    令135条の6第3項・令135条の9第3項が、その場合は令132条・令134条2項の
    **区域ごと**に適合建築物・算定位置・計画建築物を切り分けて比較しろと
    定めているためです。MVCE は区域分割ができないので、勝手に近似すると
    どちら向きにずれるか言えません（原則H）。
    """
    roads = [i for i, e in enumerate(site.edges) if e.is_road]
    if len(roads) >= 2:
        raise UndeterminedRegulation(
            f"前面道路が{len(roads)}本あります。令135条の6第3項・令135条の9第3項は、"
            "前面道路が2以上ある場合に令132条・令134条2項の区域ごとに"
            "適合建築物・算定位置・計画建築物を切り分けて比較することを"
            "求めています。MVCE は区域分割に対応していないため、天空率による"
            "道路高さ制限の適用除外（法56条7項1号）は判定できません。"
            "斜線制限のまま（use_sky_ratio: false）で計算してください。"
        )
    if not roads:
        return None

    i = roads[0]
    edge = site.edges[i]
    tier = road_slant_tier(site.zoning.zone_type, site.zoning.far_ratio,
                           site.zoning.unspecified_road_slant_slope)
    base = (edge.road_width_m + edge.wall_setback_m
            + road_slant._relaxation_extra(edge))
    depth = tier.applicable_distance_m - base
    if depth <= 0:
        return None          # 適用距離が敷地に届いていない
    inner = offset_polygon_by_edge_distances(
        site.points, [depth if j == i else 0.0 for j in range(len(site.edges))])
    site_poly = Polygon(site.points)
    band = site_poly if inner is None else site_poly.difference(inner)
    return None if band.is_empty else band


def reference_ring_at_height(site: Site, height_m: float, kind: str) -> BaseGeometry | None:
    """高さ `height_m` において規制 `kind` に適合する平面領域。"""
    distances = [
        _required_setback(site, i, height_m, kind) for i in range(len(site.edges))
    ]
    region = offset_polygon_by_edge_distances(site.points, distances)
    if region is None:
        return None
    applicable = applicable_region(site, kind)
    if applicable is None:
        return None
    region = region.intersection(applicable)
    if region.is_empty or region.area <= 1e-9:
        return None
    return region


def _reference_top_m(site: Site, kind: str) -> float:
    """その規制の適合建築物の頂部の高さ。

    「その高さで領域が残る最大の高さ」を二分探索します。各規制の制限は
    敷地の広がりで頭打ちになるので必ず有限です（隣地・北側は敷地内で最も
    遠い点、道路は適用距離で決まる）。
    """
    if reference_ring_at_height(site, 0.0, kind) is None:
        return 0.0
    lo, hi = 0.0, 1.0
    while hi < _SEARCH_CEILING_M and reference_ring_at_height(site, hi, kind) is not None:
        lo, hi = hi, hi * 2.0
    if hi >= _SEARCH_CEILING_M:
        return _SEARCH_CEILING_M
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if reference_ring_at_height(site, mid, kind) is not None:
            lo = mid
        else:
            hi = mid
    return lo


def reference_building(site: Site, kind: str,
                       n_layers: int = DEFAULT_REFERENCE_LAYERS) -> list[Block]:
    """規制 `kind` の適合建築物を階段状に近似する。

    **各層は「層の上端」の断面で作ります。** 斜線は上へ行くほど狭くなるので、
    上端の断面は層のどの高さの断面よりも小さく、階段状の立体は真の包絡形に
    **含まれます**。

    向きが大事です。層の**下端**の断面で作ると立体が真の形より**大きく**なり、
    適合建築物が空を余計に塞いで Pr が小さく出ます。Pr が小さいと
    `Ps ≧ Pr` の基準が下がるので、**本来通らない計画が通ってしまいます**。
    2026-08-30 以前の実装はこの向きでした。

    上端で作ると逆に Pr が大きめに出るので、判定は厳しい側になります。
    `n_layers` を増やすほど真の値に近づきます。
    """
    if kind not in REFERENCE_KINDS:
        raise ValueError(f"kind は {REFERENCE_KINDS} のいずれかです: {kind!r}")
    top = _reference_top_m(site, kind)
    if top <= 0 or n_layers <= 0:
        return []

    blocks: list[Block] = []
    previous = 0.0
    for k in range(n_layers):
        z_top = top * (k + 1) / n_layers
        region = reference_ring_at_height(site, z_top, kind)
        if region is not None:
            for poly in _polygons(region):
                if poly.area > 1e-6:
                    blocks.append(Block(footprint=poly, z_bottom=previous, z_top=z_top))
        previous = z_top
    return blocks


def slant_envelope(site: Site, n_layers: int = DEFAULT_REFERENCE_LAYERS) -> list[Block]:
    """斜線制限**すべて**を合成した包絡形。**適合建築物ではありません。**

    道路・隣地・北側・絶対高さ・高度地区の一番厳しいものを取った形で、
    3D ビューアで「斜線制限で建てられる最大」を見せるために使います。
    令135条の6・7・8 の適合建築物は規制ごとに別なので、天空率の判定には
    `reference_building(site, kind)` を使ってください。
    """
    from .height_field import buildable_ring_at_height, max_relevant_height

    top = max_relevant_height(site)
    if top <= 0 or n_layers <= 0:
        return []
    blocks: list[Block] = []
    previous = 0.0
    for k in range(n_layers):
        z_top = top * (k + 1) / n_layers
        ring = buildable_ring_at_height(site, z_top)
        if ring and len(ring) >= 3:
            poly = Polygon(ring)
            if poly.area > 1e-6:
                blocks.append(Block(footprint=poly, z_bottom=previous, z_top=z_top))
        previous = z_top
    return blocks


def reference_buildings(site: Site,
                        n_layers: int = DEFAULT_REFERENCE_LAYERS) -> dict[str, list[Block]]:
    """道路・隣地・北側それぞれの適合建築物。"""
    return {kind: reference_building(site, kind, n_layers) for kind in REFERENCE_KINDS}


def _polygons(geometry: BaseGeometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [g for g in getattr(geometry, "geoms", []) if g.geom_type == "Polygon"]


def check(site: Site, proposed: list[Block],
          references: dict[str, list[Block]] | None = None,
          max_interval_m: float | None = None, n_azimuth: int = 120,
          azimuth_offset_ratio: float = 0.0) -> list[SkyRatioCheck]:
    """すべての算定位置で Ps ≧ Pr を確認する。

    **測定点の種別ごとに違う適合建築物と比べます**（令135条の6・7・8）。
    道路の測定点は道路高さ制限適合建築物と、隣地の測定点は隣地高さ制限
    適合建築物と、北側の測定点は北側高さ制限適合建築物と比べます。

    Ps と Pr は**同じ方位**でサンプリングします。比較の一貫性が保たれれば
    よいので、`azimuth_offset_ratio` はどちらにも同じ値が使われます。

    想定半球の中心の高さは位置ごとに違います（道路は路面の中心、隣地・
    北側は敷地の地盤面。いずれも令135条の9〜11 の高低差みなしを含む）。
    """
    if references is None:
        references = reference_buildings(site)
    # 計画建築物も規制ごとの適用範囲で切る（令135条の6第1項1号の
    # 「…が適用される範囲内の部分に限る」）。切らずに丸ごと比べると、
    # 適合建築物の側だけが切られていて比較になりません。
    clipped = {
        kind: clip_blocks(proposed, applicable_region(site, kind))
        for kind in REFERENCE_KINDS
    }
    results = []
    for position in measurement_points(site, max_interval_m):
        p3 = position.point3
        results.append(SkyRatioCheck(
            point=position.point, kind=position.kind,
            edge_index=position.edge_index, z_m=position.z_m,
            ps=sky_ratio_percent(p3, clipped[position.kind], n_azimuth,
                                 azimuth_offset_ratio),
            pr=sky_ratio_percent(p3, references.get(position.kind, []), n_azimuth,
                                 azimuth_offset_ratio),
        ))
    return results


def all_ok(checks: list[SkyRatioCheck]) -> bool:
    return all(c.ok for c in checks)
