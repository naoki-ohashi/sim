import math

import pytest
from shapely.geometry import Point as ShPoint

from jwcad_volume.massing import Block
from jwcad_volume.regulations.sky_ratio import (
    check_sky_ratio,
    measurement_points,
    projection_radius,
    sky_ratio_percent,
    silhouette_elevation_rad,
)
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


def _ring_block(center, radius, height, width=0.5):
    footprint = ShPoint(center).buffer(radius + width, quad_segs=64).difference(
        ShPoint(center).buffer(radius - width, quad_segs=64)
    )
    return Block(footprint=footprint, z_bottom=0.0, z_top=height)


def test_projection_radius_orthographic_bounds():
    assert projection_radius(0.0) == pytest.approx(1.0)
    assert projection_radius(math.pi / 2) == pytest.approx(0.0, abs=1e-9)


def test_sky_ratio_open_sky_is_100_percent():
    assert sky_ratio_percent((15, 15, 0.0), [], n_azimuth=180) == pytest.approx(100.0)


def test_sky_ratio_uniform_ring_matches_analytic_orthographic_formula():
    center = (15, 15, 0.0)
    radius, height = 20.0, 10.0
    block = _ring_block((15, 15), radius, height)
    inner_radius = radius - 0.5  # ring's inner edge is what the ray actually reaches first
    elev = silhouette_elevation_rad(center, 37.0, [block])
    assert elev == pytest.approx(math.atan2(height, inner_radius), rel=1e-3)

    expected = math.cos(math.atan2(height, inner_radius)) ** 2 * 100.0
    got = sky_ratio_percent(center, [block], n_azimuth=720)
    assert got == pytest.approx(expected, rel=1e-3)


def test_sky_ratio_decreases_with_block_height():
    center = (15, 15, 0.0)
    low = _ring_block((15, 15), 20.0, 5.0)
    high = _ring_block((15, 15), 20.0, 20.0)
    r_low = sky_ratio_percent(center, [low], n_azimuth=360)
    r_high = sky_ratio_percent(center, [high], n_azimuth=360)
    assert r_high < r_low < 100.0


def test_measurement_points_road_baseline_is_offset_by_road_width():
    site = _site()
    pts = [mp for mp in measurement_points(site, interval_m=5.0) if mp.kind == "road"]
    ys = {round(p.point[1], 3) for p in pts}
    assert ys == {-6.001}  # road baseline = edge (y=0) shifted outward by 6m (+ a tiny epsilon)


def test_measurement_points_adjacent_baseline_is_the_edge_itself():
    site = _site()
    pts = [mp for mp in measurement_points(site, interval_m=5.0) if mp.kind == "adjacent"]
    xs = {round(p.point[0], 3) for p in pts}
    assert xs == {30.001}  # the edge itself, nudged a tiny epsilon outside the site


def test_check_sky_ratio_identical_building_passes_with_zero_margin():
    site = _site()
    ref = reference_building_blocks(site, n_layers=10)
    results = check_sky_ratio(site, proposed_blocks=ref, reference_blocks=ref, interval_m=5.0, n_azimuth=180)
    assert results
    assert all(r.ok for r in results)
    assert all(r.margin == pytest.approx(0.0, abs=1e-6) for r in results)


def test_check_sky_ratio_taller_uniform_building_fails():
    site = _site()
    ref = reference_building_blocks(site, n_layers=10)
    # a strictly taller version of every block occupying the same footprints
    taller = [Block(footprint=b.footprint, z_bottom=b.z_bottom, z_top=b.z_top + 5.0) for b in ref]
    results = check_sky_ratio(site, proposed_blocks=taller, reference_blocks=ref, interval_m=5.0, n_azimuth=180)
    assert any(not r.ok for r in results)


def test_check_sky_ratio_smaller_setback_building_passes():
    site = _site()
    ref = reference_building_blocks(site, n_layers=10)
    # shrink every footprint toward its centroid -> blocks strictly less sky
    shrunk = [Block(footprint=b.footprint.buffer(-1.0) if b.footprint.buffer(-1.0).area > 1 else b.footprint,
                     z_bottom=b.z_bottom, z_top=b.z_top) for b in ref]
    results = check_sky_ratio(site, proposed_blocks=shrunk, reference_blocks=ref, interval_m=5.0, n_azimuth=180)
    assert all(r.ok for r in results)
