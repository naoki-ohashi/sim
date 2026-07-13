import pytest
from shapely.geometry import Polygon

from jwcad_volume.massing import Block, max_height, total_floor_area, total_volume

SQUARE = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])


def test_block_height_and_volume():
    b = Block(footprint=SQUARE, z_bottom=0.0, z_top=5.0)
    assert b.height == pytest.approx(5.0)
    assert b.volume == pytest.approx(500.0)


def test_block_rejects_non_positive_height():
    with pytest.raises(ValueError):
        Block(footprint=SQUARE, z_bottom=5.0, z_top=5.0)


def test_total_volume_and_max_height():
    blocks = [
        Block(footprint=SQUARE, z_bottom=0.0, z_top=10.0),
        Block(footprint=Polygon([(2, 2), (8, 2), (8, 8), (2, 8)]), z_bottom=10.0, z_top=15.0),
    ]
    assert total_volume(blocks) == pytest.approx(100 * 10 + 36 * 5)
    assert max_height(blocks) == pytest.approx(15.0)


def test_total_floor_area_estimate():
    blocks = [Block(footprint=SQUARE, z_bottom=0.0, z_top=9.6)]
    assert total_floor_area(blocks, floor_height_m=3.2) == pytest.approx(100 * 3)


def test_total_floor_area_does_not_undercount_many_thin_layers():
    # 20 layers of 0.48m each (total 9.6m = 3 floors of 3.2m), each layer far
    # thinner than one floor -- rounding block-by-block would give 0 floors
    # per layer and undercount the whole stack to zero.
    n_layers = 20
    layer_h = 9.6 / n_layers
    blocks = [Block(footprint=SQUARE, z_bottom=i * layer_h, z_top=(i + 1) * layer_h) for i in range(n_layers)]
    assert total_floor_area(blocks, floor_height_m=3.2) == pytest.approx(100 * 3)


def test_total_floor_area_empty_blocks():
    assert total_floor_area([], floor_height_m=3.2) == 0.0
