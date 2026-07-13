import pytest

from jwcad_volume.regulations.combined import required_setback_for_height
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (20, 0), (20, 20), (0, 20)]


def _site(zone_type="1res", far_ratio=2.0):
    zoning = ZoningParams(zone_type=zone_type, far_ratio=far_ratio, coverage_ratio=0.6)
    edges = [
        Boundary((0, 0), (20, 0), kind="road", road_width_m=6.0),
        Boundary((20, 0), (20, 20), kind="adjacent"),
        Boundary((20, 20), (0, 20), kind="north"),
        Boundary((0, 20), (0, 0), kind="adjacent"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_road_setback_matches_forward_formula():
    site = _site()
    edge = site.edges[0]  # road, width 6, slope 1.25, applicable_distance 20
    # H0 = 1.25*6 = 7.5; below H0 no setback needed
    assert required_setback_for_height(edge, 5.0, site) == pytest.approx(0.0)
    # at H0 exactly, still no setback
    assert required_setback_for_height(edge, 7.5, site) == pytest.approx(0.0)
    # above H0: s = (h-H0)/slope
    s = required_setback_for_height(edge, 20.0, site)
    assert s == pytest.approx((20.0 - 7.5) / 1.25)


def test_road_setback_capped_at_applicable_distance():
    site = _site()
    edge = site.edges[0]
    s = required_setback_for_height(edge, 1000.0, site)
    assert s == pytest.approx(20.0 - 6.0)  # applicable_distance - road_width


def test_adjacent_setback_below_start_height_is_zero():
    site = _site()
    edge = site.edges[1]
    assert required_setback_for_height(edge, 20.0, site) == pytest.approx(0.0)
    assert required_setback_for_height(edge, 25.0, site) == pytest.approx(5.0 / 1.25)


def test_north_setback_zero_when_zone_not_applicable():
    site = _site(zone_type="1res")
    edge = site.edges[2]
    assert required_setback_for_height(edge, 100.0, site) == pytest.approx(0.0)


def test_slope_multiplier_leaves_h0_unchanged_but_reduces_setback_above_it():
    site = _site()
    edge = site.edges[1]  # adjacent, start=20, slope=1.25
    # at h == H0, setback is 0 regardless of multiplier
    assert required_setback_for_height(edge, 20.0, site, slope_multiplier=3.0) == pytest.approx(0.0)
    # above H0, a bigger multiplier needs less setback for the same height
    s1 = required_setback_for_height(edge, 30.0, site, slope_multiplier=1.0)
    s2 = required_setback_for_height(edge, 30.0, site, slope_multiplier=2.0)
    assert s2 < s1
    assert s2 == pytest.approx(s1 / 2.0)
