import pytest

from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]


def _square_site(**zoning_kwargs):
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6, **zoning_kwargs)
    edges = [
        Boundary((0, 0), (10, 0), kind="road", road_width_m=6.0),
        Boundary((10, 0), (10, 10), kind="adjacent"),
        Boundary((10, 10), (0, 10), kind="north"),
        Boundary((0, 10), (0, 0), kind="adjacent"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_site_area_and_caps():
    site = _square_site()
    assert site.area_m2 == pytest.approx(100.0)
    assert site.max_building_area_m2() == pytest.approx(60.0)
    assert site.max_total_floor_area_m2() == pytest.approx(200.0)


def test_site_rejects_cw_points():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    cw_points = list(reversed(SQUARE))
    edges = [Boundary(cw_points[i], cw_points[(i + 1) % 4], kind="none") for i in range(4)]
    with pytest.raises(ValueError, match="counter-clockwise"):
        Site(points=cw_points, edges=edges, zoning=zoning)


def test_site_rejects_mismatched_edges():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    edges = [Boundary((0, 0), (5, 0), kind="none")] * 4  # wrong endpoints
    with pytest.raises(ValueError, match="do not match"):
        Site(points=SQUARE, edges=edges, zoning=zoning)


def test_road_boundary_requires_width():
    with pytest.raises(ValueError, match="road_width_m"):
        Boundary((0, 0), (10, 0), kind="road", road_width_m=0.0)
