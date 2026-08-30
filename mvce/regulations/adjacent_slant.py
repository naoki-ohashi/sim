"""隣地斜線制限（法56条1項2号）と令135条の3の緩和.

    高さ制限 H = 立上り高さ + 勾配 × L
    L = 隣地境界線からの水平距離（＋後退緩和・公園等の緩和）

    立上り/勾配: 住居系 20m + 1.25 / その他 31m + 2.5

適用する緩和:

- **後退緩和（法56条1項2号）**: 建物を隣地境界線から A だけ後退させると、
  隣地境界線が A だけ外側にあるものとみなす。
- **令135条の3第1項1号（公園・広場・水面等）**: 敷地がこれらに接する場合、
  隣地境界線がその幅の**1/2**だけ外側にあるものとみなす。
  （道路斜線の令134条が「幅の全部」なのに対し、こちらは1/2である点に注意）
- **令135条の3第1項2号（高低差緩和）**: 敷地の地盤面が隣地より1m以上低い
  場合、地盤面が (高低差 - 1) / 2 だけ高い位置にあるものとみなす。

第一種・第二種低層住居専用地域と田園住居地域は、法55条の絶対高さ制限
（10mまたは12m）が先に効くため、隣地斜線の適用はありません。
"""
from __future__ import annotations

import math

from ..geometry import Point, point_line_distance
from ..site import Boundary, RelaxationKind, Site
from ..zoning import adjacent_slant_item, adjacent_slant_params

# 令135条の3第1項1号の緩和対象: 公園・広場・水面・線路敷
ADJACENT_RELAXATION_KINDS = {RelaxationKind.PARK, RelaxationKind.WATER, RelaxationKind.RAILWAY}


def _relaxation_extra(edge: Boundary) -> float:
    """公園・水面等の幅の 1/2（令135条の3第1項1号）。"""
    relax = edge.relaxation
    if relax.active and relax.kind in ADJACENT_RELAXATION_KINDS:
        return relax.width_m / 2.0
    return 0.0


def _level_relaxation(edge: Boundary) -> float:
    """令135条の3第1項2号: 地盤面が隣地より1m以上低い場合の緩和。"""
    h = edge.ground_level_diff_m
    return (h - 1.0) / 2.0 if h >= 1.0 else 0.0


def applies(site: Site) -> bool:
    """隣地斜線の適用がある用途地域か。

    適用の有無は法56条1項2号イ〜ニの列挙だけで決まるので、勾配の指定が
    無い無指定区域でもここは答えられます（`_params()` は答えられません）。
    """
    return adjacent_slant_item(site.zoning.zone_type) is not None


def edge_height_limit(site: Site, edge_index: int, point: Point) -> float:
    edge = site.edges[edge_index]
    params = adjacent_slant_params(
        site.zoning.zone_type,
        site.zoning.far_ratio,
        site.zoning.unspecified_adjacent_slant_slope,
        site.zoning.adjacent_slant_2_5_designated,
    )
    if params is None:
        return math.inf
    start_height, slope = params
    L = (point_line_distance(point, edge.p1, edge.p2)
         + edge.wall_setback_m + _relaxation_extra(edge))
    return start_height + slope * L + _level_relaxation(edge)


def height_limit_at(site: Site, point: Point) -> float:
    if not applies(site):
        return math.inf
    limits = [
        edge_height_limit(site, i, point)
        for i, e in enumerate(site.edges)
        if e.kind.value == "adjacent"
    ]
    return min(limits) if limits else math.inf


def required_setback_for_height(site: Site, edge_index: int, height_m: float) -> float:
    """高さ `height_m` を確保するために必要な、隣地境界線からの後退距離。"""
    edge = site.edges[edge_index]
    params = adjacent_slant_params(
        site.zoning.zone_type,
        site.zoning.far_ratio,
        site.zoning.unspecified_adjacent_slant_slope,
        site.zoning.adjacent_slant_2_5_designated,
    )
    if params is None or edge.kind.value != "adjacent" or height_m <= 0:
        return 0.0
    start_height, slope = params
    base = edge.wall_setback_m + _relaxation_extra(edge)
    h0 = start_height + slope * base + _level_relaxation(edge)
    if height_m <= h0:
        return 0.0
    return (height_m - _level_relaxation(edge) - start_height) / slope - base
