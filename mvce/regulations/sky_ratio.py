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
from ..zoning import UndeterminedRegulation
from . import adjacent_slant, north_slant, road_slant
from .road_regions import RoadRegion, applicable_distance_band, sky_regions
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
    #: 令132条の区域の番号（道路で前面道路が2以上のときだけ）
    region_index: int | None = None

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
    site: Site, max_interval_m: float | None = None,
    regions: list[RoadRegion] | None = None,
) -> list[MeasurementPosition]:
    """算定位置（令135条の9・10・11）。詳細は `sky_positions.py`。

    **道路は前面道路の反対側の境界線上、隣地は境界線から16m（12.4m）外側、
    北側は真北方向に4m（8m）外側**で、間隔も規制ごとに違います。
    以前はすべて境界線上・2m間隔でしたが、条文と違っていました。

    `max_interval_m` は条文の間隔をさらに細かくしたいときだけ使います
    （粗くはできません）。

    前面道路が2以上ある敷地では、道路の位置は令132条の**区域ごと**です
    （令135条の9第3項）。`regions` を省略すると区域を作り直します。
    """
    if regions is None:
        regions = road_sky_regions(site)
    return all_positions(site, max_interval_m, regions)


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


def _required_setback(site: Site, edge_index: int, height_m: float, kind: str,
                      region: RoadRegion | None = None) -> float:
    """規制 `kind` **だけ**で見た、その辺に必要な後退距離。

    `region` を渡すと令132条の区域として扱います。その区域の前面道路でない
    辺は制限を与えません（2項「これらの前面道路のみを前面道路とし」・
    3項「その接する前面道路のみを前面道路とする」）。区域の前面道路には
    みなし幅員を使います。
    """
    edge = site.edges[edge_index]
    if kind == "road":
        if not edge.is_road:
            return 0.0
        width_m = None
        if region is not None:
            if edge_index not in region.road_indices:
                return 0.0
            width_m = region.deemed_width_m
        # 適用距離で頭打ちにしない素の距離。帯の中で斜線どおりの形を作るため
        return road_slant.slant_distance_for_height(site, edge_index, height_m,
                                                    width_m=width_m)
    if kind == "adjacent":
        return adjacent_slant.required_setback_for_height(site, edge_index, height_m) \
            if edge.kind.value == "adjacent" else 0.0
    if kind == "north":
        return north_slant.required_setback_for_height(site, edge_index, height_m) \
            if edge_index in north_slant.north_edges(site) else 0.0
    raise ValueError(f"kind は {REFERENCE_KINDS} のいずれかです: {kind!r}")


def applicable_region(site: Site, kind: str,
                      region: RoadRegion | None = None) -> BaseGeometry | None:
    """規制 `kind` が適用される範囲（令135条の6・7・8 の「…に限る」）。

    - 道路 … 別表第三（は）欄の適用距離までの帯（前面道路ごとの和集合）
    - 隣地・北側 … その規制の適用がある用途地域なら敷地全体、無ければ None

    条文は**適合建築物も計画建築物も**この範囲内の部分に限ると言っています。
    範囲が空なら両方とも空になり、天空率は 100% 対 100% で自動的に適合します
    （道路高さ制限がそもそも敷地に届いていないのだから、当然の結果です）。

    `region` は令132条の区域です（令135条の6第3項）。道路のときだけ効きます。
    """
    if kind == "road":
        return _road_applicable_region(site, region)
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


def road_sky_regions(site: Site) -> list[RoadRegion]:
    """道路の天空率を評価する単位（令132条の区域）。前面道路が1本以下なら空。

    実体は `road_regions.sky_regions()` です。令134条2項を選んだ敷地は
    そちらで `UndeterminedRegulation` になります。
    """
    return sky_regions(site)


def _road_applicable_region(site: Site,
                            region: RoadRegion | None = None) -> BaseGeometry | None:
    """道路高さ制限が適用される範囲（令135条の6第1項1号の「範囲内の部分」）。

    別表第三（は）欄の適用距離までの帯です。ここを外すと道路高さ制限が
    かからないので、**適合建築物にも計画建築物にもその部分は含めません**。

    この帯を作らずに道路だけの適合建築物を組むと、適用距離の外側が
    「制限なし＝どこまでも高い」形になり、Pr が極端に小さく出て**何でも
    通ってしまいます**。切り落としは省略できません。

    `region` を渡すと、その区域の前面道路だけを、みなし幅員で見た帯の
    和集合を取り、さらに区域そのもので切ります（令135条の6第3項）。
    """
    roads = [i for i, e in enumerate(site.edges) if e.is_road]
    if not roads:
        return None
    if region is None and len(roads) >= 2:
        raise UndeterminedRegulation(
            f"前面道路が{len(roads)}本あります。令135条の6第3項は区域ごとの"
            "比較を求めているので、区域を指定せずに道路の適用範囲は決まりません。"
            "`road_sky_regions(site)` の区域を渡してください。"
        )

    if region is None:
        bands = [applicable_distance_band(site, roads[0])]
    else:
        bands = [applicable_distance_band(site, i, region.deemed_width_m)
                 for i in region.road_indices]
    bands = [b for b in bands if b is not None]
    if not bands:
        return None          # 適用距離が敷地に届いていない
    band: BaseGeometry = unary_union(bands)
    if region is not None:
        band = band.intersection(region.polygon)
    if band.is_empty or band.area <= 1e-9:
        return None
    return band


def reference_ring_at_height(site: Site, height_m: float, kind: str,
                             region: RoadRegion | None = None) -> BaseGeometry | None:
    """高さ `height_m` において規制 `kind` に適合する平面領域。"""
    distances = [
        _required_setback(site, i, height_m, kind, region)
        for i in range(len(site.edges))
    ]
    ring = offset_polygon_by_edge_distances(site.points, distances)
    if ring is None:
        return None
    applicable = applicable_region(site, kind, region)
    if applicable is None:
        return None
    ring = ring.intersection(applicable)
    if ring.is_empty or ring.area <= 1e-9:
        return None
    return ring


def _reference_top_m(site: Site, kind: str,
                     region: RoadRegion | None = None) -> float:
    """その規制の適合建築物の頂部の高さ。

    「その高さで領域が残る最大の高さ」を二分探索します。各規制の制限は
    敷地の広がりで頭打ちになるので必ず有限です（隣地・北側は敷地内で最も
    遠い点、道路は適用距離で決まる）。
    """
    if reference_ring_at_height(site, 0.0, kind, region) is None:
        return 0.0
    lo, hi = 0.0, 1.0
    while hi < _SEARCH_CEILING_M \
            and reference_ring_at_height(site, hi, kind, region) is not None:
        lo, hi = hi, hi * 2.0
    if hi >= _SEARCH_CEILING_M:
        return _SEARCH_CEILING_M
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if reference_ring_at_height(site, mid, kind, region) is not None:
            lo = mid
        else:
            hi = mid
    return lo


def reference_building(site: Site, kind: str,
                       n_layers: int = DEFAULT_REFERENCE_LAYERS,
                       region: RoadRegion | None = None) -> list[Block]:
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
    top = _reference_top_m(site, kind, region)
    if top <= 0 or n_layers <= 0:
        return []

    blocks: list[Block] = []
    previous = 0.0
    for k in range(n_layers):
        z_top = top * (k + 1) / n_layers
        ring = reference_ring_at_height(site, z_top, kind, region)
        if ring is not None:
            for poly in _polygons(ring):
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


def reference_buildings(
    site: Site, n_layers: int = DEFAULT_REFERENCE_LAYERS,
    regions: list[RoadRegion] | None = None,
) -> dict[str, list[Block]]:
    """測定点のグループごとの適合建築物。

    キーは `MeasurementPosition.group_key` と同じで、隣地・北側は
    `"adjacent"` / `"north"`、道路は前面道路が1本以下なら `"road"`、
    2以上なら令132条の区域ごとに `"road#0"`, `"road#1"`, … です
    （令135条の6第3項）。
    """
    if regions is None:
        regions = road_sky_regions(site)
    out: dict[str, list[Block]] = {}
    if regions:
        for k, region in enumerate(regions):
            out[f"road#{k}"] = reference_building(site, "road", n_layers, region)
    else:
        out["road"] = reference_building(site, "road", n_layers)
    for kind in ("adjacent", "north"):
        out[kind] = reference_building(site, kind, n_layers)
    return out


def applicable_regions(
    site: Site, regions: list[RoadRegion] | None = None,
) -> dict[str, BaseGeometry | None]:
    """`reference_buildings()` と同じキーでの適用範囲。

    計画建築物を切るのに使います（令135条の6第1項1号の「…が適用される
    範囲内の部分に限る」、第3項で「区域ごとの部分」）。
    """
    if regions is None:
        regions = road_sky_regions(site)
    out: dict[str, BaseGeometry | None] = {}
    if regions:
        for k, region in enumerate(regions):
            out[f"road#{k}"] = applicable_region(site, "road", region)
    else:
        out["road"] = applicable_region(site, "road")
    for kind in ("adjacent", "north"):
        out[kind] = applicable_region(site, kind)
    return out


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

    **前面道路が2以上ある敷地では、道路は令132条の区域ごとに比べます**
    （令135条の6第3項・令135条の9第3項）。区域ごとに、その区域の前面道路を
    みなし幅員で見た適合建築物・算定位置・計画建築物の3つを揃えます。
    `references` を自前で渡すときは `reference_buildings()` と同じキー
    （`"road#0"` など）にしてください。
    """
    regions = road_sky_regions(site)
    if references is None:
        references = reference_buildings(site, regions=regions)
    # 計画建築物も規制ごとの適用範囲で切る（令135条の6第1項1号の
    # 「…が適用される範囲内の部分に限る」）。切らずに丸ごと比べると、
    # 適合建築物の側だけが切られていて比較になりません。
    clipped = {
        key: clip_blocks(proposed, geometry)
        for key, geometry in applicable_regions(site, regions).items()
    }
    results = []
    for position in measurement_points(site, max_interval_m, regions):
        p3 = position.point3
        key = position.group_key
        results.append(SkyRatioCheck(
            point=position.point, kind=position.kind,
            edge_index=position.edge_index, z_m=position.z_m,
            ps=sky_ratio_percent(p3, clipped.get(key, []), n_azimuth,
                                 azimuth_offset_ratio),
            pr=sky_ratio_percent(p3, references.get(key, []), n_azimuth,
                                 azimuth_offset_ratio),
            region_index=position.region_index,
        ))
    return results


def all_ok(checks: list[SkyRatioCheck]) -> bool:
    return all(c.ok for c in checks)
