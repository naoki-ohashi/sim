"""算定用の適合建築物 (slant-line-only reference building) as stacked Blocks.

For 天空率 comparison, the "reference building" is the hypothetical mass
that exactly fills the site up to the slant-line height-limit surface
(no 建蔽率 footprint restriction: the standard applies the full site plan
as the baseline envelope for this specific comparison). Ps (proposed) must
give a sky ratio >= Pr (this reference) at every measurement point.
"""
from __future__ import annotations

from ..geometry import offset_polygon_by_edge_distances
from ..massing import Block
from ..site import Site
from .combined import estimate_max_relevant_height, required_setback_for_height


def blocks_at_thresholds(
    site: Site, layer_tops: list[float], slope_multiplier: float = 1.0
) -> list[Block]:
    """Build stacked Blocks whose layer boundaries are exactly `layer_tops`
    (each must be > 0 and strictly increasing). Exposed separately from
    `reference_building_blocks` so envelope.py's sky-ratio search can reuse
    the *exact* height thresholds of an existing baseline when building a
    boosted candidate -- picking new, independently-spaced thresholds would
    otherwise shift even the untouched low layers by a discretization
    artifact unrelated to the actual boost.
    """
    blocks: list[Block] = []
    prev_h = 0.0
    for h in layer_tops:
        # use the setback required at the *bottom* of this layer (prev_h): a
        # larger, more conservative footprint than the true continuous
        # envelope would have partway up the layer, so this discretization
        # never underestimates how much sky the reference building blocks.
        distances = [required_setback_for_height(e, prev_h, site, slope_multiplier) for e in site.edges]
        poly = offset_polygon_by_edge_distances(site.points, distances)
        if poly is not None and poly.area > 1e-6:
            blocks.append(Block(footprint=poly, z_bottom=prev_h, z_top=h))
        prev_h = h
    return blocks


def reference_building_blocks(
    site: Site, n_layers: int = 30, max_height: float | None = None, slope_multiplier: float = 1.0
) -> list[Block]:
    if max_height is None:
        max_height = estimate_max_relevant_height(site) * slope_multiplier
    if max_height <= 0:
        return []
    layer_tops = [max_height * (k + 1) / n_layers for k in range(n_layers)]
    return blocks_at_thresholds(site, layer_tops, slope_multiplier)
