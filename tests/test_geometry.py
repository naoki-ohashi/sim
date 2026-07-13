import math

import pytest
from shapely.geometry import Polygon

from jwcad_volume.geometry import (
    azimuth_deg,
    ensure_ccw,
    interior_normal,
    offset_polygon_by_edge_distances,
    point_line_distance,
    polygon_area,
)

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_polygon_area():
    assert polygon_area(SQUARE) == pytest.approx(100.0)


def test_ensure_ccw_reverses_cw():
    cw = list(reversed(SQUARE))
    assert ensure_ccw(cw) == SQUARE


def test_interior_normal_bottom_edge_points_up():
    n = interior_normal((0, 0), (10, 0))
    assert n == pytest.approx((0.0, 1.0))


def test_point_line_distance():
    assert point_line_distance((5, 3), (0, 0), (10, 0)) == pytest.approx(3.0)
    assert point_line_distance((-5, 3), (0, 0), (10, 0)) == pytest.approx(3.0)


def test_azimuth_deg_cardinal_directions():
    origin = (0, 0)
    assert azimuth_deg(origin, (0, 10)) == pytest.approx(0.0)  # north
    assert azimuth_deg(origin, (10, 0)) == pytest.approx(90.0)  # east
    assert azimuth_deg(origin, (0, -10)) == pytest.approx(180.0)  # south
    assert azimuth_deg(origin, (-10, 0)) == pytest.approx(270.0)  # west


def test_offset_polygon_uniform_setback_shrinks_square():
    region = offset_polygon_by_edge_distances(SQUARE, [2, 2, 2, 2])
    assert region is not None
    assert region.area == pytest.approx(6 * 6)
    minx, miny, maxx, maxy = region.bounds
    assert (minx, miny, maxx, maxy) == pytest.approx((2, 2, 8, 8))


def test_offset_polygon_asymmetric_setback():
    # only set back the bottom edge (index 0: (0,0)-(10,0)) by 4
    region = offset_polygon_by_edge_distances(SQUARE, [4, 0, 0, 0])
    assert region is not None
    minx, miny, maxx, maxy = region.bounds
    assert (minx, miny, maxx, maxy) == pytest.approx((0, 4, 10, 10))
    assert region.area == pytest.approx(10 * 6)


def test_offset_polygon_too_large_setback_returns_none():
    region = offset_polygon_by_edge_distances(SQUARE, [20, 20, 20, 20])
    assert region is None
