"""北側斜線制限（法56条1項3号）と令135条の4の緩和.

    高さ制限 H = 立上り高さ + 1.25 × L
    L = 真北方向の隣地境界線（または北側前面道路の反対側境界線）からの
        真北方向の水平距離

    立上り: 低層住居専用・田園住居 5m / 中高層住居専用 10m

北側斜線には他の斜線と決定的に違う点が2つあります。

1. **後退緩和がありません。** 建物を境界線から下げても制限は緩みません。
2. **距離を「真北方向」に測ります。** 他の斜線が境界線からの垂直距離を
   使うのに対し、北側斜線は真北方向の距離です。そのため北側境界線が真北に
   対して斜めでも、真北方向の成分で判定します。

**令135条の4第1項1号の緩和対象は「水面・線路敷その他これらに類するもの」
だけで、公園・広場は含まれません。** 隣地斜線（令135条の3）が公園・広場も
対象にするのと異なるので、混同しないよう別の集合として定義しています。
"""
from __future__ import annotations

import math

from ..geometry import Point, outward_normal
from ..site import Boundary, RelaxationKind, Site
from ..zoning import north_slant_params

# 令135条の4第1項1号: 水面・線路敷のみ（公園・広場は対象外）
NORTH_RELAXATION_KINDS = {RelaxationKind.WATER, RelaxationKind.RAILWAY}


def _relaxation_extra(edge: Boundary) -> float:
    relax = edge.relaxation
    if relax.active and relax.kind in NORTH_RELAXATION_KINDS:
        return relax.width_m / 2.0
    return 0.0


def _level_relaxation(edge: Boundary) -> float:
    """令135条の4第1項2号: 地盤面が北側隣地より1m以上低い場合。"""
    h = edge.ground_level_diff_m
    return (h - 1.0) / 2.0 if h >= 1.0 else 0.0


def applies(site: Site) -> bool:
    return north_slant_params(site.zoning.zone_type) is not None


def north_edges(site: Site) -> list[int]:
    """真北側を向いている辺のインデックス。

    北側斜線の基準となる「北側の隣地境界線／前面道路の反対側境界線」を、
    辺の外向き法線が真北成分を持つかどうかで判定します。
    """
    result = []
    for i, edge in enumerate(site.edges):
        if edge.kind.value == "none":
            continue
        try:
            outward = outward_normal(edge.p1, edge.p2)
        except ValueError:
            continue
        if site.north.faces_north(edge.p1, edge.p2, outward):
            result.append(i)
    return result


def _north_distance(site: Site, edge: Boundary, point: Point) -> float:
    """点から辺までの、真北方向に測った距離（真北成分）。"""
    nx, ny = site.north.north_vector
    # 辺上の一点から点へのベクトルの、真北方向成分（北向きが正）
    along_north = (point[0] - edge.p1[0]) * nx + (point[1] - edge.p1[1]) * ny
    # 敷地は境界線の南側にあるので、境界線までの距離は -along_north
    return max(0.0, -along_north)


def edge_height_limit(site: Site, edge_index: int, point: Point) -> float:
    params = north_slant_params(site.zoning.zone_type)
    if params is None:
        return math.inf
    start_height, slope = params
    edge = site.edges[edge_index]

    L = _north_distance(site, edge, point) + _relaxation_extra(edge)
    # 北側前面道路の場合は、道路の反対側の境界線が起点になる
    if edge.is_road:
        L += edge.road_width_m
    # 後退緩和は北側斜線には無い（wall_setback_m は意図的に使わない）
    return start_height + slope * L + _level_relaxation(edge)


def height_limit_at(site: Site, point: Point) -> float:
    if not applies(site):
        return math.inf
    limits = [edge_height_limit(site, i, point) for i in north_edges(site)]
    return min(limits) if limits else math.inf


def required_setback_for_height(site: Site, edge_index: int, height_m: float) -> float:
    """高さ `height_m` を確保するために必要な、北側境界線からの真北方向の距離。"""
    params = north_slant_params(site.zoning.zone_type)
    if params is None or height_m <= 0:
        return 0.0
    edge = site.edges[edge_index]
    start_height, slope = params
    base = _relaxation_extra(edge) + (edge.road_width_m if edge.is_road else 0.0)
    h0 = start_height + slope * base + _level_relaxation(edge)
    if height_m <= h0:
        return 0.0
    return (height_m - _level_relaxation(edge) - start_height) / slope - base
