import math

import pytest

from jwcad_volume.regulations import adjacent_slant, north_slant, road_slant
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (20, 0), (20, 20), (0, 20)]


def _site(zone_type, far_ratio=2.0, coverage_ratio=0.6, road_width=6.0, setback=0.0):
    zoning = ZoningParams(zone_type=zone_type, far_ratio=far_ratio, coverage_ratio=coverage_ratio)
    edges = [
        Boundary((0, 0), (20, 0), kind="road", road_width_m=road_width, setback_m=setback),
        Boundary((20, 0), (20, 20), kind="adjacent", setback_m=setback),
        Boundary((20, 20), (0, 20), kind="north", setback_m=setback),
        Boundary((0, 20), (0, 0), kind="adjacent", setback_m=setback),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


# --- road slant line ---------------------------------------------------

def test_road_slant_residential_group_at_boundary():
    site = _site("1res", far_ratio=2.0, road_width=6.0)
    edge = site.edges[0]
    limit = road_slant.edge_height_limit((0, 0), edge, "1res", 2.0)
    assert limit == pytest.approx(1.25 * 6.0)


def test_road_slant_residential_group_within_applicable_distance():
    site = _site("1res", far_ratio=2.0, road_width=6.0)
    edge = site.edges[0]
    # 14m into the site -> L = 6 + 14 = 20 == applicable distance for FAR<=200%
    limit = road_slant.edge_height_limit((0, 14), edge, "1res", 2.0)
    assert limit == pytest.approx(1.25 * 20.0)


def test_road_slant_beyond_applicable_distance_is_unconstrained():
    site = _site("1res", far_ratio=2.0, road_width=6.0)
    edge = site.edges[0]
    limit = road_slant.edge_height_limit((0, 20), edge, "1res", 2.0)  # L = 26 > 20
    assert limit == math.inf


def test_road_slant_setback_relaxation_extends_applicable_range():
    site = _site("1res", far_ratio=2.0, road_width=6.0, setback=4.0)
    edge = site.edges[0]
    # L = s(=10) + road_width(6) + setback(4) = 20
    limit = road_slant.edge_height_limit((0, 10), edge, "1res", 2.0)
    assert limit == pytest.approx(1.25 * 20.0)


def test_road_slant_commercial_group_slope_1_5():
    site = _site("commercial", far_ratio=3.0, road_width=6.0)
    edge = site.edges[0]
    limit = road_slant.edge_height_limit((0, 0), edge, "commercial", 3.0)
    assert limit == pytest.approx(1.5 * 6.0)


def test_road_slant_no_road_edges_unconstrained():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    edges = [Boundary(SQUARE[i], SQUARE[(i + 1) % 4], kind="none") for i in range(4)]
    site = Site(points=SQUARE, edges=edges, zoning=zoning)
    assert road_slant.height_limit_at_point((10, 10), site) == math.inf


# --- adjacent slant line -------------------------------------------------

def test_adjacent_slant_residential_group():
    site = _site("1res")
    edge = site.edges[1]  # x=20 boundary
    assert adjacent_slant.edge_height_limit((20, 10), edge, "1res") == pytest.approx(20.0)
    assert adjacent_slant.edge_height_limit((12, 10), edge, "1res") == pytest.approx(20.0 + 1.25 * 8.0)


def test_adjacent_slant_other_group():
    site = _site("commercial")
    edge = site.edges[1]
    assert adjacent_slant.edge_height_limit((20, 10), edge, "commercial") == pytest.approx(31.0)
    assert adjacent_slant.edge_height_limit((16, 10), edge, "commercial") == pytest.approx(31.0 + 2.5 * 4.0)


def test_adjacent_slant_setback_relaxation():
    site = _site("1res", setback=3.0)
    edge = site.edges[1]
    # actual distance 0, + setback 3 -> L = 3
    assert adjacent_slant.edge_height_limit((20, 10), edge, "1res") == pytest.approx(20.0 + 1.25 * 3.0)


# --- north slant line -----------------------------------------------------

def test_north_slant_low_rise_zone():
    site = _site("1low")
    edge = site.edges[2]  # y=20 boundary
    assert north_slant.edge_height_limit((10, 20), edge, "1low") == pytest.approx(5.0)
    assert north_slant.edge_height_limit((10, 12), edge, "1low") == pytest.approx(5.0 + 1.25 * 8.0)


def test_north_slant_mid_rise_zone():
    site = _site("1mid")
    edge = site.edges[2]
    assert north_slant.edge_height_limit((10, 20), edge, "1mid") == pytest.approx(10.0)


def test_north_slant_not_applicable_zone():
    site = _site("1res")
    assert north_slant.height_limit_at_point((10, 15), site) == math.inf
    assert not north_slant.applies_to_zone("1res")


def test_north_slant_applicability():
    assert north_slant.applies_to_zone("1low")
    assert north_slant.applies_to_zone("2mid")
    assert not north_slant.applies_to_zone("commercial")
