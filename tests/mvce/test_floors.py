"""階別床（mvce/floors.py）のテスト。"""
import pytest

from mvce.floors import FloorSlab, floors_from_blocks, total_floor_area_m2
from mvce.massing import Block
from mvce.solvers.optimizer import OptimizeOptions, optimize
from mvce.site import Site
from mvce.zoning import ZoningParams
from shapely.geometry import Polygon

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(far=2.0, coverage=0.6, zone="1res", road_width=6.0):
    specs = [
        {"kind": "road", "road_width_m": road_width},
        {"kind": "adjacent"},
        {"kind": "adjacent"},
        {"kind": "adjacent"},
    ]
    return Site.from_rings(SQUARE, specs, ZoningParams(zone, far, coverage))


def _square(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_floors_from_blocks_groups_by_level():
    blocks = [
        Block(footprint=_square(0, 0, 10, 10), z_bottom=0.0, z_top=3.2),
        Block(footprint=_square(0, 0, 8, 8), z_bottom=3.2, z_top=6.4),
    ]
    floors = floors_from_blocks(blocks, floor_height_m=3.2)
    assert [f.level for f in floors] == [0, 1]
    assert floors[0].label_ja == "1階"
    assert floors[1].label_ja == "2階"
    assert floors[0].area_m2 == pytest.approx(100.0)
    assert floors[1].area_m2 == pytest.approx(64.0)


def test_floors_from_blocks_merges_multiple_footprints_on_same_level():
    blocks = [
        Block(footprint=_square(0, 0, 4, 4), z_bottom=0.0, z_top=3.2),
        Block(footprint=_square(10, 10, 14, 14), z_bottom=0.0, z_top=3.2),
    ]
    floors = floors_from_blocks(blocks, floor_height_m=3.2)
    assert len(floors) == 1
    assert len(floors[0].footprints) == 2
    assert floors[0].area_m2 == pytest.approx(32.0)


def test_floors_from_blocks_rejects_non_positive_floor_height():
    with pytest.raises(ValueError):
        floors_from_blocks([], floor_height_m=0.0)


def test_has_holes_detects_interior_rings():
    outer = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]],
    )
    floor = FloorSlab(level=0, z_bottom=0.0, z_top=3.0, footprints=[outer])
    assert floor.has_holes is True


def test_no_holes_when_footprints_are_solid():
    floor = FloorSlab(level=0, z_bottom=0.0, z_top=3.0, footprints=[_square(0, 0, 10, 10)])
    assert floor.has_holes is False


def test_total_floor_area_matches_optimize_result():
    """`floors_from_blocks` の合計は `OptimizeResult.total_floor_area_m2`
    （体積 ÷ 階高）と数学的に一致する（floors.py のdocstring参照）。"""
    result = optimize(_site(), None, OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))
    floors = floors_from_blocks(result.blocks, result.site.floor_height_m)
    assert total_floor_area_m2(floors) == pytest.approx(result.total_floor_area_m2, rel=1e-9)
