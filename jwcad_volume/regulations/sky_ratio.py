"""天空率 (sky ratio) calculation.

Method: for each measurement point, scan azimuth in a full circle; for each
azimuth find the tallest silhouette angle among all building blocks the ray
passes through (a block's vertical face blocks the sky from the horizon up
to atan2(block.z_top - z0, r) at the block's nearest edge distance r along
that ray -- correct for stacked convex extrusions since a nearer block's
face always occludes the view up to its own top edge). The blocked-vs-open
sky area is then read off a projection of the sky hemisphere onto the
horizontal plane below the measurement point: elevation angle theta maps to
normalized radius rho(theta), and sky ratio = sum of open-sky sector areas
/ full-circle area.

Caveat: the projection formula and the measurement-point placement interval
are implemented here as a reasonable, internally-consistent approximation
for design-stage volume estimation (orthogonal projection rho = cos(theta),
points spaced along the literal baseline segment). This has NOT been
validated against a specific certified 天空率 calculation program and must
not be used as-is for building-permit submission -- see docs/disclaimer.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString
from shapely.geometry import Point as ShPoint
from shapely.ops import nearest_points

from ..geometry import Point, edge_direction, interior_normal
from ..massing import Block
from ..site import Boundary, Site
from .north_slant import applies_to_zone as north_applies
from .reference_building import reference_building_blocks

RAY_LENGTH = 1.0e5


def _ray_entry_distance(origin_xy: Point, azimuth_deg: float, footprint) -> float | None:
    az = math.radians(azimuth_deg)
    dx, dy = math.sin(az), math.cos(az)  # azimuth 0 = north = +Y, 90 = east = +X
    far = (origin_xy[0] + RAY_LENGTH * dx, origin_xy[1] + RAY_LENGTH * dy)
    ray = LineString([origin_xy, far])
    inter = ray.intersection(footprint)
    if inter.is_empty:
        return None
    origin = ShPoint(origin_xy)
    _, nearest = nearest_points(origin, inter)
    d = origin.distance(nearest)
    return d if d > 1e-9 else None


def silhouette_elevation_rad(point3: tuple[float, float, float], azimuth_deg: float, blocks: list[Block]) -> float:
    x, y, z0 = point3
    max_elev = 0.0
    for block in blocks:
        if block.z_top <= z0:
            continue
        r = _ray_entry_distance((x, y), azimuth_deg, block.footprint)
        if r is None:
            continue
        elev = math.atan2(block.z_top - z0, r)
        if elev > max_elev:
            max_elev = elev
    return max_elev


def projection_radius(elevation_rad: float, method: str = "orthographic") -> float:
    if method == "orthographic":
        return math.cos(elevation_rad)
    if method == "equidistant":
        return 1.0 - elevation_rad / (math.pi / 2)
    raise ValueError(f"unknown projection method: {method!r}")


def sky_ratio_percent(
    point3: tuple[float, float, float],
    blocks: list[Block],
    n_azimuth: int = 360,
    method: str = "orthographic",
) -> float:
    """天空率 (%) at a single measurement point, given the building's blocks."""
    dphi = 2 * math.pi / n_azimuth
    total = 0.0
    for i in range(n_azimuth):
        az_deg = i * 360.0 / n_azimuth
        elev = silhouette_elevation_rad(point3, az_deg, blocks)
        rho = projection_radius(elev, method)
        total += 0.5 * rho * rho * dphi
    return total / math.pi * 100.0


@dataclass
class MeasurementPoint:
    point: Point
    kind: str  # "road" | "adjacent" | "north"
    edge_index: int


# Nudge adjacent/north measurement points a hair outside the site boundary.
# A legally compliant reference/proposed building can have zero setback right
# up to the boundary line (e.g. an adjacent-slant wall up to 20m tall at
# distance 0), which makes a measurement point placed exactly on that line a
# numerically singular case (entry distance 0 -> undefined atan2 blowup, or a
# ray that merely grazes the footprint's edge with no real entry). Standing a
# fraction of a millimeter outside resolves this without affecting results at
# the tool's working precision.
MEASUREMENT_EPSILON_M = 1.0e-3


def _baseline_segment(edge: Boundary) -> tuple[Point, Point]:
    n_in = interior_normal(edge.p1, edge.p2)
    n_out = (-n_in[0], -n_in[1])
    shift = edge.road_width_m if edge.kind == "road" else 0.0
    shift += MEASUREMENT_EPSILON_M
    p1 = (edge.p1[0] + shift * n_out[0], edge.p1[1] + shift * n_out[1])
    p2 = (edge.p2[0] + shift * n_out[0], edge.p2[1] + shift * n_out[1])
    return p1, p2


def measurement_points(site: Site, interval_m: float = 2.0) -> list[MeasurementPoint]:
    """Measurement points along each regulated edge's baseline.

    Simplification: points are spaced along the literal edge segment (not
    the notification's exact corner/extension rules) -- adequate for
    design-stage comparison, not for final measurement-point certification.
    """
    points: list[MeasurementPoint] = []
    for idx, edge in enumerate(site.edges):
        if edge.kind == "north" and not north_applies(site.zoning.zone_type):
            continue
        if edge.kind not in ("road", "adjacent", "north"):
            continue
        p1, p2 = _baseline_segment(edge)
        dx, dy = edge_direction(p1, p2)
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        n = max(2, math.ceil(length / interval_m) + 1)
        for k in range(n):
            t = length * k / (n - 1)
            pt = (p1[0] + t * dx, p1[1] + t * dy)
            points.append(MeasurementPoint(point=pt, kind=edge.kind, edge_index=idx))
    return points


@dataclass
class SkyRatioCheck:
    point: Point
    kind: str
    edge_index: int
    ps: float
    pr: float

    @property
    def ok(self) -> bool:
        return self.ps >= self.pr

    @property
    def margin(self) -> float:
        return self.ps - self.pr


def check_sky_ratio(
    site: Site,
    proposed_blocks: list[Block],
    reference_blocks: list[Block] | None = None,
    interval_m: float = 2.0,
    n_azimuth: int = 360,
    measurement_height: float = 0.0,
) -> list[SkyRatioCheck]:
    """Ps vs Pr at every measurement point. All points must have ok=True for
    the proposed design to legally substitute sky-ratio compliance for the
    plain slant-line limit on that boundary."""
    if reference_blocks is None:
        reference_blocks = reference_building_blocks(site)
    results = []
    for mp in measurement_points(site, interval_m):
        point3 = (mp.point[0], mp.point[1], measurement_height)
        ps = sky_ratio_percent(point3, proposed_blocks, n_azimuth)
        pr = sky_ratio_percent(point3, reference_blocks, n_azimuth)
        results.append(SkyRatioCheck(point=mp.point, kind=mp.kind, edge_index=mp.edge_index, ps=ps, pr=pr))
    return results
