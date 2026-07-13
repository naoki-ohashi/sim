import pytest

from jwcad_volume.massing import max_height as blocks_max_height
from jwcad_volume.regulations.reference_building import reference_building_blocks
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (30, 0), (30, 30), (0, 30)]


def _site():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    edges = [
        Boundary((0, 0), (30, 0), kind="road", road_width_m=6.0),
        Boundary((30, 0), (30, 30), kind="adjacent"),
        Boundary((30, 30), (0, 30), kind="none"),
        Boundary((0, 30), (0, 0), kind="none"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_reference_building_footprints_shrink_monotonically():
    site = _site()
    blocks = reference_building_blocks(site, n_layers=20)
    assert len(blocks) > 1
    areas = [b.footprint.area for b in blocks]
    assert all(a2 <= a1 + 1e-6 for a1, a2 in zip(areas, areas[1:]))


def test_reference_building_capped_by_absolute_height_limit():
    zoning = ZoningParams(
        zone_type="1low", far_ratio=0.8, coverage_ratio=0.5, absolute_height_limit_m=10.0
    )
    edges = [
        Boundary((0, 0), (30, 0), kind="road", road_width_m=6.0),
        Boundary((30, 0), (30, 30), kind="adjacent"),
        Boundary((30, 30), (0, 30), kind="north"),
        Boundary((0, 30), (0, 0), kind="adjacent"),
    ]
    site = Site(points=SQUARE, edges=edges, zoning=zoning)
    blocks = reference_building_blocks(site, n_layers=20)
    assert blocks_max_height(blocks) <= 10.0 + 1e-6


def test_reference_building_ground_layer_covers_near_full_site_minus_road_setback():
    site = _site()
    blocks = reference_building_blocks(site, n_layers=30)
    ground_block = blocks[0]
    # bottom layer requires almost no setback (h close to 0) so its footprint
    # should be very close to the full site area
    assert ground_block.footprint.area == pytest.approx(900.0, rel=0.02)
