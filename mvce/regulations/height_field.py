"""各点の高さ制限をまとめる（斜線制限＋絶対高さ制限）.

道路斜線・隣地斜線・北側斜線・法55条の絶対高さ制限のうち、最も厳しいものが
その点の高さ制限になります。天空率（法56条7項）を使う場合は斜線制限を
置き換えられますが、絶対高さ制限は天空率では外せないため常に効きます。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import Point, offset_polygon_by_edge_distances, polygon_to_ring
from ..site import Site
from ..zone_split import require_single_zone_type
from . import adjacent_slant, height_district, north_slant, road_slant


@dataclass
class HeightBreakdown:
    """その点の高さ制限の内訳（どの規制が効いているか）。"""

    road_m: float
    adjacent_m: float
    north_m: float
    absolute_m: float
    height_district_m: float
    limit_m: float
    # "road" | "adjacent" | "north" | "absolute" | "height_district" | "none"
    governing: str


def breakdown_at(site: Site, point: Point) -> HeightBreakdown:
    require_single_zone_type(site.zone_split, "斜線制限（法56条）")
    road = road_slant.height_limit_at(site, point)
    adjacent = adjacent_slant.height_limit_at(site, point)
    north = north_slant.height_limit_at(site, point)
    absolute = (site.zoning.absolute_height_limit_m
                if site.zoning.absolute_height_limit_m is not None else math.inf)
    district = height_district.height_limit_at(site, point)

    candidates = {"road": road, "adjacent": adjacent, "north": north,
                  "absolute": absolute, "height_district": district}
    governing = min(candidates, key=lambda k: candidates[k])
    limit = candidates[governing]
    if math.isinf(limit):
        governing = "none"
    return HeightBreakdown(road, adjacent, north, absolute, district, limit, governing)


def height_limit_at(site: Site, point: Point, use_sky_ratio: bool = False) -> float:
    """点の高さ制限。

    `use_sky_ratio=True` のときは斜線制限を外し、絶対高さ制限だけを見ます
    （天空率で斜線制限に代えて適合させる前提。天空率そのものの判定は
    `sky_ratio.py` で別途行います）。
    """
    if use_sky_ratio:
        require_single_zone_type(site.zone_split, "絶対高さ制限（法55条）")
        absolute = (site.zoning.absolute_height_limit_m
                    if site.zoning.absolute_height_limit_m is not None else math.inf)
        # 法56条7項が適用除外にするのは法56条1項1号〜3号だけ。法55条の
        # 絶対高さ制限も法58条の高度地区も天空率では外れない。
        return min(absolute, height_district.height_limit_at(site, point))
    return breakdown_at(site, point).limit_m


def required_setback_for_height(site: Site, edge_index: int, height_m: float) -> float:
    """辺 `edge_index` について、高さ `height_m` に必要な後退距離。"""
    require_single_zone_type(site.zone_split, "斜線制限（法56条）")
    edge = site.edges[edge_index]
    # 高度地区（法58条）は北側境界線について効く。天空率でも外れない。
    district_needed = 0.0
    if edge_index in north_slant.north_edges(site):
        district_needed = height_district.required_setback_for_height(
            site, edge_index, height_m)

    if edge.is_road:
        return max(district_needed,
                   road_slant.required_setback_for_height(site, edge_index, height_m))
    if edge.kind.value == "adjacent":
        needed = adjacent_slant.required_setback_for_height(site, edge_index, height_m)
        if edge_index in north_slant.north_edges(site):
            needed = max(needed, north_slant.required_setback_for_height(site, edge_index, height_m))
        return max(needed, district_needed)
    return district_needed


def buildable_ring_at_height(site: Site, height_m: float) -> list[Point] | None:
    """高さ `height_m` において斜線制限を満たす平面領域。

    各辺に必要な後退距離を求め、その半平面の共通部分を取ります。
    領域が残らない場合は None。
    """
    distances = [
        required_setback_for_height(site, i, height_m) for i in range(len(site.edges))
    ]
    poly = offset_polygon_by_edge_distances(site.points, distances)
    return polygon_to_ring(poly) if poly is not None else None


def max_relevant_height(site: Site) -> float:
    """検討する高さの上限（有限値）。

    絶対高さ制限があればそれ、無ければ敷地の各頂点と重心での斜線制限の
    最大値に余裕を見た値を使います。
    """
    require_single_zone_type(site.zone_split, "絶対高さ制限（法55条）")
    district = site.height_district
    if district is not None and district.max_height_m is not None:
        if site.zoning.absolute_height_limit_m is not None:
            return min(site.zoning.absolute_height_limit_m, district.max_height_m)
        return district.max_height_m
    if site.zoning.absolute_height_limit_m is not None:
        return site.zoning.absolute_height_limit_m
    cx = sum(p[0] for p in site.points) / len(site.points)
    cy = sum(p[1] for p in site.points) / len(site.points)
    values = [
        breakdown_at(site, p).limit_m for p in list(site.points) + [(cx, cy)]
    ]
    finite = [v for v in values if math.isfinite(v)]
    return max(finite) * 1.5 if finite else 120.0
