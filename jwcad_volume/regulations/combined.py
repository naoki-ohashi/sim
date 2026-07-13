"""Combine road/adjacent/north slant-line limits, and invert height -> required setback.

`required_setback_for_height` is the key primitive that lets us turn a
target height `h` back into a per-edge setback distance, which is exactly
the input `offset_polygon_by_edge_distances` expects. That means "the
slant-line-only reference building's footprint at height h" is just:

    offset_polygon_by_edge_distances(
        site.points, [required_setback_for_height(e, h, site) for e in site.edges]
    )
"""
from __future__ import annotations

import math

from ..geometry import Point
from ..site import Boundary, Site
from ..zoning import ADJACENT_SLANT_BY_GROUP, NORTH_SLANT_ZONES, road_slant_params, zone_group
from . import adjacent_slant, north_slant, road_slant


def height_limit_at_point(site: Site, point: Point) -> float:
    """Combined slant-line + absolute-height-limit ceiling at `point` (may be math.inf)."""
    h = min(
        road_slant.height_limit_at_point(point, site),
        adjacent_slant.height_limit_at_point(point, site),
        north_slant.height_limit_at_point(point, site),
    )
    if site.zoning.absolute_height_limit_m is not None:
        h = min(h, site.zoning.absolute_height_limit_m)
    return h


def required_setback_for_height(edge: Boundary, h: float, site: Site, slope_multiplier: float = 1.0) -> float:
    """Perpendicular distance `s` from `edge`'s own line (into the site)
    needed so the slant-line height limit at that distance is >= h. Returns
    0.0 when no setback is needed (h already satisfied at the boundary
    itself, or `edge` carries no applicable regulation).

    With `slope_multiplier` == 1.0 this is exactly the statutory height
    limit inverted. For envelope.py's sky-ratio search, `slope_multiplier`
    != 1.0 generates a taller "boosted" family: height at s=0 (H0) is always
    pinned to the true legal value (unaffected by the multiplier -- a real
    design has no room to gain anything right at the boundary anyway), and
    only the *growth rate* beyond s=0 is scaled by the multiplier. This
    matters for the road case in particular, whose height formula has no
    fixed intercept (H = slope * L with L measured from the road's opposite
    boundary, so L=0 does not correspond to s=0): naively multiplying the
    slope there would still inflate height right at the site's own road
    frontage and immediately fail sky-ratio at the nearest measurement
    points, instead of trading distance for height further back.
    """
    if h <= 0:
        return 0.0
    if edge.kind == "road":
        tier = road_slant_params(site.zoning.zone_type, site.zoning.far_ratio)
        L0 = edge.road_width_m + edge.setback_m
        H0 = tier.slope * L0
        s_max = max(0.0, tier.applicable_distance_m - L0)
        if h <= H0:
            return 0.0
        s_needed = (h - H0) / (tier.slope * slope_multiplier)
        return min(s_needed, s_max)
    if edge.kind == "adjacent":
        start_height, slope = ADJACENT_SLANT_BY_GROUP[zone_group(site.zoning.zone_type)]
        H0 = start_height + slope * edge.setback_m
        if h <= H0:
            return 0.0
        return (h - H0) / (slope * slope_multiplier)
    if edge.kind == "north":
        if site.zoning.zone_type not in NORTH_SLANT_ZONES:
            return 0.0
        start_height, slope = NORTH_SLANT_ZONES[site.zoning.zone_type]
        H0 = start_height + slope * edge.setback_m
        if h <= H0:
            return 0.0
        return (h - H0) / (slope * slope_multiplier)
    return 0.0


def estimate_max_relevant_height(site: Site) -> float:
    """A finite upper bound for generating the reference building, based on
    sampling the height field at the site's vertices and centroid."""
    candidates: list[Point] = list(site.points)
    cx = sum(p[0] for p in site.points) / len(site.points)
    cy = sum(p[1] for p in site.points) / len(site.points)
    candidates.append((cx, cy))
    finite_vals = [v for v in (height_limit_at_point(site, p) for p in candidates) if math.isfinite(v)]
    if site.zoning.absolute_height_limit_m is not None:
        return site.zoning.absolute_height_limit_m
    if not finite_vals:
        return 100.0  # arbitrary finite fallback when the site has no regulated edges at all
    return max(finite_vals) * 1.3
