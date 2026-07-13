import math

import pytest
from shapely.geometry import Point as ShPoint, Polygon

from jwcad_volume.massing import Block
from jwcad_volume.regulations.shadow import (
    ShadowRegulationParams,
    compute_shadow_hours,
    perimeter_sample_points,
    shadow_union_at,
    true_solar_hours,
)
from jwcad_volume.site import Boundary, Site
from jwcad_volume.solar import day_of_year, solar_declination_deg, solar_position_deg
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (20, 0), (20, 20), (0, 20)]
TOKYO_LAT = 35.7


def _site():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    edges = [Boundary(SQUARE[i], SQUARE[(i + 1) % 4], kind="none") for i in range(4)]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_true_solar_hours_step_count():
    p = ShadowRegulationParams(start_hour=8.0, end_hour=16.0, time_step_minutes=60.0)
    assert true_solar_hours(p) == pytest.approx([8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0])


def test_shadow_union_none_when_sun_below_horizon():
    block = Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=10.0)
    assert shadow_union_at([block], -5.0, 180.0) is None


def test_shadow_falls_north_at_winter_solstice_noon_tokyo():
    block = Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=20.0)
    delta = solar_declination_deg(day_of_year(12, 22))
    alt, az = solar_position_deg(TOKYO_LAT, delta, 12.0)
    shadow = shadow_union_at([block], alt, az)
    expected_reach = 20.0 / math.tan(math.radians(alt))

    assert shadow.covers(ShPoint(10, 20 + expected_reach - 1))
    assert not shadow.covers(ShPoint(10, 20 + expected_reach + 5))
    # south side (opposite the shadow direction) must stay clear
    assert not shadow.covers(ShPoint(10, -3))


def test_perimeter_sample_points_are_offset_outward():
    site = _site()
    pts = perimeter_sample_points(site, 5.0, interval_m=5.0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert min(xs) == pytest.approx(-5.0, abs=0.1)
    assert min(ys) == pytest.approx(-5.0, abs=0.1)
    assert max(xs) == pytest.approx(25.0, abs=0.1)
    assert max(ys) == pytest.approx(25.0, abs=0.1)


def test_compute_shadow_hours_negligible_height_never_violates():
    # Even at winter solstice the sun stays low all day at this latitude (max
    # altitude ~31 deg), so a *real* low-rise building can still cast a
    # shadow past 5m most of the day -- this only isolates that the
    # mechanics report near-zero hours for a practically flat obstruction.
    site = _site()
    block = Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=0.1)
    params = ShadowRegulationParams(time_step_minutes=30.0)
    results = compute_shadow_hours(site, [block], params)
    assert all(r.ok for r in results)


def test_compute_shadow_hours_tall_building_shadows_north_line_more_than_south():
    site = _site()
    block = Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=40.0)
    params = ShadowRegulationParams(time_step_minutes=15.0, line1_max_hours=0.1, line2_max_hours=0.1)
    results = compute_shadow_hours(site, [block], params)
    line1 = next(r for r in results if r.line_name == "line1")
    north_hours = [h for (x, y), h in line1.point_hours if y > 20]
    south_hours = [h for (x, y), h in line1.point_hours if y < 0]
    assert max(north_hours) > max(south_hours)
    assert not line1.ok  # a 40m tower easily exceeds a 0.1h allowance
