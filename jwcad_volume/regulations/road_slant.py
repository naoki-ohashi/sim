"""道路斜線制限 (road slant-line restriction).

Building Standards Act Art. 56 para 1 item 1, Enforcement Order Art. 130-11
(applicable distance / slope table) and Art. 130-12 (setback relaxation).

Height limit at a point, measured from the road's *opposite* boundary line:

    H(L) = slope * L   for L <= applicable_distance, else unconstrained

where L = (perpendicular distance from the point to the road's near boundary
line) + road_width + setback_relaxation.
"""
from __future__ import annotations

import math

from ..geometry import Point, point_line_distance
from ..site import Boundary, Site
from ..zoning import road_slant_params


def distance_from_opposite_boundary(point: Point, edge: Boundary) -> float:
    if edge.kind != "road":
        raise ValueError("distance_from_opposite_boundary requires a 'road' boundary")
    s = point_line_distance(point, edge.p1, edge.p2)
    return s + edge.road_width_m + edge.setback_m


def edge_height_limit(point: Point, edge: Boundary, zone_type: str, far_ratio: float) -> float:
    """Road slant-line height limit imposed by a single road edge (math.inf if unconstrained)."""
    tier = road_slant_params(zone_type, far_ratio)
    L = distance_from_opposite_boundary(point, edge)
    if L > tier.applicable_distance_m:
        return math.inf
    return tier.slope * L


def height_limit_at_point(point: Point, site: Site) -> float:
    """Combined road slant-line height limit at `point` (math.inf if the site has no road edges)."""
    road_edges = [e for e in site.edges if e.kind == "road"]
    if not road_edges:
        return math.inf
    return min(
        edge_height_limit(point, e, site.zoning.zone_type, site.zoning.far_ratio) for e in road_edges
    )
