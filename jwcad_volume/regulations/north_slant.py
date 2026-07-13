"""北側斜線制限 (north-side slant-line restriction).

Building Standards Act Art. 56 para 1 item 3, Enforcement Order Art. 135-4
(setback relaxation). Only applies in the zones listed in
zoning.NORTH_SLANT_ZONES (1low/2low/denen: start 5m; 1mid/2mid: start 10m),
each with slope 1.25.

    H(L) = start_height + slope * L

where L = (perpendicular distance from the point to the north-side boundary
line) + setback_relaxation. Edges must be tagged kind="north" by the caller
for the boundary that actually faces true north.
"""
from __future__ import annotations

import math

from ..geometry import Point, point_line_distance
from ..site import Boundary, Site
from ..zoning import NORTH_SLANT_ZONES


def applies_to_zone(zone_type: str) -> bool:
    return zone_type in NORTH_SLANT_ZONES


def edge_height_limit(point: Point, edge: Boundary, zone_type: str) -> float:
    if edge.kind != "north":
        raise ValueError("edge_height_limit requires a 'north' boundary")
    if not applies_to_zone(zone_type):
        return math.inf
    start_height, slope = NORTH_SLANT_ZONES[zone_type]
    L = point_line_distance(point, edge.p1, edge.p2) + edge.setback_m
    return start_height + slope * L


def height_limit_at_point(point: Point, site: Site) -> float:
    if not applies_to_zone(site.zoning.zone_type):
        return math.inf
    north_edges = [e for e in site.edges if e.kind == "north"]
    if not north_edges:
        return math.inf
    return min(edge_height_limit(point, e, site.zoning.zone_type) for e in north_edges)
