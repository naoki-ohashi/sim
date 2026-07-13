"""Building mass representation: a stack of extruded footprint blocks.

A `Block` is a horizontal slab: a 2D footprint (shapely Polygon) extruded
from z_bottom to z_top. A building (proposed design or the slant-line
reference building) is represented as `list[Block]`, stacked bottom to top
with monotonically non-increasing footprint area (a "wedding cake" massing),
which is the standard shape both for slant-line envelopes and for realistic
sky-ratio-optimized designs.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon


@dataclass
class Block:
    footprint: Polygon
    z_bottom: float
    z_top: float

    def __post_init__(self) -> None:
        if self.z_top <= self.z_bottom:
            raise ValueError("z_top must be greater than z_bottom")
        if self.footprint.is_empty:
            raise ValueError("footprint must not be empty")

    @property
    def height(self) -> float:
        return self.z_top - self.z_bottom

    @property
    def volume(self) -> float:
        return self.footprint.area * self.height


def total_volume(blocks: list[Block]) -> float:
    return sum(b.volume for b in blocks)


def max_height(blocks: list[Block]) -> float:
    return max((b.z_top for b in blocks), default=0.0)


def total_floor_area(blocks: list[Block], floor_height_m: float) -> float:
    """Rough gross floor area estimate (a design-stage estimate, not an
    exact 容積率算定床面積 calculation which has its own exclusions).

    Equivalent to treating the stepped envelope as a continuous Riemann sum
    of floor_height_m-tall slabs and averaging: volume / floor_height_m.
    Counting whole floors per individual geometry layer instead (e.g. by
    reference_building_blocks' n_layers) would silently under-count whenever
    a layer is thinner than one floor, even though the whole stack spans
    several floors -- this sidesteps that by never depending on how finely
    the envelope happens to be layered.
    """
    return total_volume(blocks) / floor_height_m
