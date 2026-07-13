"""隣地斜線制限 (adjacent-site slant-line restriction).

Building Standards Act Art. 56 para 1 item 2, Enforcement Order Art. 135-3
(setback relaxation).

    H(L) = start_height + slope * L

where L = (perpendicular distance from the point to the adjacent boundary
line) + setback_relaxation, and (start_height, slope) is (20m, 1.25) for
residential-group zones or (31m, 2.5) otherwise (zoning.ADJACENT_SLANT_BY_GROUP).

Note: 1low/2low/denen zones are subject to this item in the statute but in
practice never reach it because of their absolute height limit (10/12m);
callers that also apply `zoning.absolute_height_limit_m` get that for free.
"""
from __future__ import annotations

import math

from ..geometry import Point, point_line_distance
from ..site import Boundary, Site
from ..zoning import ADJACENT_SLANT_BY_GROUP, zone_group


def edge_height_limit(point: Point, edge: Boundary, zone_type: str) -> float:
    if edge.kind != "adjacent":
        raise ValueError("edge_height_limit requires an 'adjacent' boundary")
    start_height, slope = ADJACENT_SLANT_BY_GROUP[zone_group(zone_type)]
    L = point_line_distance(point, edge.p1, edge.p2) + edge.setback_m
    return start_height + slope * L


def height_limit_at_point(point: Point, site: Site) -> float:
    adjacent_edges = [e for e in site.edges if e.kind == "adjacent"]
    if not adjacent_edges:
        return math.inf
    return min(edge_height_limit(point, e, site.zoning.zone_type) for e in adjacent_edges)
