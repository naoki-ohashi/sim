"""2D site geometry utilities.

Coordinate convention used throughout this package: +X = true east,
+Y = true north, matching a plan drawing with north pointing up
(this matters for the north-side slant line and for solar/shadow
calculations, both of which are defined relative to true north).

Compass bearings (azimuth) are measured clockwise from north, 0-360 deg.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

Point = tuple[float, float]

BIG = 1.0e6  # far larger than any real site, used to build half-plane polygons


def polygon_signed_area(points: Sequence[Point]) -> float:
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def ensure_ccw(points: Sequence[Point]) -> list[Point]:
    """Return the ring in counter-clockwise order (math convention)."""
    pts = list(points)
    if polygon_signed_area(pts) < 0:
        pts.reverse()
    return pts


def edge_direction(p1: Point, p2: Point) -> tuple[float, float]:
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("degenerate edge with zero length")
    return dx / length, dy / length


def interior_normal(p1: Point, p2: Point) -> tuple[float, float]:
    """Unit normal pointing into the polygon, assuming CCW winding."""
    dx, dy = edge_direction(p1, p2)
    return (-dy, dx)


def point_line_distance(point: Point, p1: Point, p2: Point) -> float:
    """Unsigned perpendicular distance from `point` to the infinite line p1-p2."""
    dx, dy = edge_direction(p1, p2)
    px, py = point[0] - p1[0], point[1] - p1[1]
    # component of (point - p1) along the normal
    nx, ny = -dy, dx
    return abs(px * nx + py * ny)


def signed_distance_to_line(point: Point, p1: Point, p2: Point, normal: tuple[float, float]) -> float:
    """Signed distance from point to line p1-p2, positive on the `normal` side."""
    px, py = point[0] - p1[0], point[1] - p1[1]
    return px * normal[0] + py * normal[1]


def azimuth_deg(p_from: Point, p_to: Point) -> float:
    """Compass bearing from p_from to p_to, clockwise from north, in [0, 360)."""
    dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
    deg = math.degrees(math.atan2(dx, dy))
    return deg % 360.0


def _halfplane_polygon(p1: Point, p2: Point, normal: tuple[float, float], offset: float) -> Polygon:
    """A very large rectangle covering {x : normal . (x - (p1 + offset*normal)) >= 0}.

    Used to intersect a site polygon against a per-edge setback constraint
    (perpendicular distance from the edge's line >= `offset`).
    """
    dx, dy = edge_direction(p1, p2)
    nx, ny = normal
    sx, sy = p1[0] + offset * nx, p1[1] + offset * ny
    a = (sx - BIG * dx, sy - BIG * dy)
    b = (sx + BIG * dx, sy + BIG * dy)
    c = (b[0] + BIG * nx, b[1] + BIG * ny)
    e = (a[0] + BIG * nx, a[1] + BIG * ny)
    return Polygon([a, b, c, e])


def offset_polygon_by_edge_distances(points: Sequence[Point], distances: Sequence[float]) -> Polygon | None:
    """Buildable region after setting back each edge i by distances[i].

    Implemented as the intersection of per-edge half-planes (perpendicular
    distance from each edge's line >= distances[i]). This is the standard
    simplified approach for slant-line setback envelopes: distance is
    measured from the (infinite) boundary line, not just the segment.
    Edges with distances[i] <= 0 are ignored (no setback required there).

    Returns None if the constraints leave no buildable area.
    """
    pts = ensure_ccw(points)
    n = len(pts)
    region: Polygon | None = Polygon(pts)
    for i in range(n):
        d = distances[i]
        if d is None or d <= 0:
            continue
        p1, p2 = pts[i], pts[(i + 1) % n]
        normal = interior_normal(p1, p2)
        hp = _halfplane_polygon(p1, p2, normal, d)
        region = region.intersection(hp) if region is not None else None
        if region.is_empty:
            return None
    if region is None or region.is_empty:
        return None
    return orient(region, sign=1.0)


def polygon_area(points: Sequence[Point]) -> float:
    return abs(polygon_signed_area(points))
