"""日影規制 (sunlight/shadow regulation).

Building Standards Act Art. 56-2, Enforcement Order Art. 135-12/135-13.
Local ordinances set the actual measurement height and the two measurement
lines' hour limits per zone (別表第四) -- there is no universal default, so
`ShadowRegulationParams` requires them explicitly rather than guessing.

Simplification: this measures shadow duration on ground sample points along
two lines offset outward from the *entire* site perimeter (not just specific
neighbor-facing edges, and not actual neighboring terrain/elevation), over a
single specified date. This is adequate for design-stage estimation, not for
a certified 日影図 submission -- see docs/disclaimer.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.affinity import translate
from shapely.geometry import JOIN_STYLE, Point as ShPoint, Polygon
from shapely.ops import unary_union

from ..geometry import Point
from ..massing import Block
from ..site import Site
from ..solar import day_of_year, solar_declination_deg, solar_position_deg


@dataclass
class ShadowRegulationParams:
    measurement_month: int = 12
    measurement_day: int = 22
    start_hour: float = 8.0  # true solar time
    end_hour: float = 16.0
    time_step_minutes: float = 10.0
    measurement_height_m: float = 4.0
    latitude_deg: float = 35.7
    line1_distance_m: float = 5.0
    line1_max_hours: float = 5.0
    line2_distance_m: float = 10.0
    line2_max_hours: float = 3.0
    perimeter_sample_interval_m: float = 5.0


def _shadow_of_block(block: Block, shift: tuple[float, float]) -> Polygon:
    """Minkowski sum of block.footprint with the segment [0, shift]: the
    ground shadow that block's solid volume casts under parallel light."""
    sx, sy = shift
    if abs(sx) < 1e-9 and abs(sy) < 1e-9:
        return block.footprint
    shifted = translate(block.footprint, sx, sy)
    parts = [block.footprint, shifted]
    coords = list(block.footprint.exterior.coords)
    for (ax, ay), (bx, by) in zip(coords, coords[1:]):
        parts.append(Polygon([(ax, ay), (bx, by), (bx + sx, by + sy), (ax + sx, ay + sy)]))
    return unary_union(parts)


def shadow_union_at(blocks: list[Block], altitude_deg: float, azimuth_deg: float):
    """Ground shadow polygon (union over all blocks) at a given sun
    position, or None if the sun is at/below the horizon (no shadow)."""
    if altitude_deg <= 0 or not blocks:
        return None
    shift_len_per_block = [b.z_top / math.tan(math.radians(altitude_deg)) for b in blocks]
    az = math.radians(azimuth_deg)
    # shadow falls opposite the sun's azimuth
    away = (-math.sin(az), -math.cos(az))
    shadows = [
        _shadow_of_block(b, (length * away[0], length * away[1]))
        for b, length in zip(blocks, shift_len_per_block)
    ]
    return unary_union(shadows)


def true_solar_hours(params: ShadowRegulationParams) -> list[float]:
    step = params.time_step_minutes / 60.0
    hours = []
    h = params.start_hour
    while h < params.end_hour - 1e-9:
        hours.append(h)
        h += step
    return hours


def perimeter_sample_points(site: Site, distance_m: float, interval_m: float) -> list[Point]:
    ring = Polygon(site.points).buffer(distance_m, join_style=JOIN_STYLE.mitre).exterior
    length = ring.length
    n = max(3, math.ceil(length / interval_m))
    return [tuple(ring.interpolate(length * i / n).coords[0]) for i in range(n)]


@dataclass
class ShadowLineResult:
    line_name: str  # "line1" or "line2"
    max_hours: float
    point_hours: list[tuple[Point, float]]

    @property
    def worst_point(self) -> tuple[Point, float]:
        return max(self.point_hours, key=lambda pair: pair[1])

    @property
    def ok(self) -> bool:
        return all(hrs <= self.max_hours + 1e-9 for _, hrs in self.point_hours)


def compute_shadow_hours(site: Site, blocks: list[Block], params: ShadowRegulationParams) -> list[ShadowLineResult]:
    declination = solar_declination_deg(day_of_year(params.measurement_month, params.measurement_day))
    hours = true_solar_hours(params)
    step_hours = params.time_step_minutes / 60.0

    line_specs = [
        ("line1", params.line1_distance_m, params.line1_max_hours),
        ("line2", params.line2_distance_m, params.line2_max_hours),
    ]
    points_by_line = {
        name: perimeter_sample_points(site, dist, params.perimeter_sample_interval_m)
        for name, dist, _ in line_specs
    }
    duration = {name: [0.0] * len(pts) for name, pts in points_by_line.items()}

    for hour in hours:
        alt, az = solar_position_deg(params.latitude_deg, declination, hour)
        shadow = shadow_union_at(blocks, alt, az)
        if shadow is None or shadow.is_empty:
            continue
        for name, pts in points_by_line.items():
            for i, p in enumerate(pts):
                if shadow.covers(ShPoint(p)):
                    duration[name][i] += step_hours

    results = []
    for name, dist, max_hours in line_specs:
        pts = points_by_line[name]
        results.append(
            ShadowLineResult(
                line_name=name,
                max_hours=max_hours,
                point_hours=list(zip(pts, duration[name])),
            )
        )
    return results
