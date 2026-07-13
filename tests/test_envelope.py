import pytest

from jwcad_volume.envelope import compute_max_envelope
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (30, 0), (30, 30), (0, 30)]

FAST_KW = dict(n_layers=12, interval_m=10.0, n_azimuth=60, search_iterations=14)


def _site(coverage_ratio=1.0, far_ratio=1000.0):
    zoning = ZoningParams(zone_type="1res", far_ratio=far_ratio, coverage_ratio=coverage_ratio)
    edges = [
        Boundary((0, 0), (30, 0), kind="road", road_width_m=6.0),
        Boundary((30, 0), (30, 30), kind="adjacent"),
        Boundary((30, 30), (0, 30), kind="none"),
        Boundary((0, 30), (0, 0), kind="none"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_no_sky_ratio_no_caps_matches_baseline():
    site = _site()
    result = compute_max_envelope(site, use_sky_ratio=False, **FAST_KW)
    assert result.tower.extra_height_m == pytest.approx(0.0)
    assert not result.coverage_cap_applied
    assert not result.far_cap_applied
    assert result.volume_m3 == pytest.approx(sum(b.volume for b in result.baseline_blocks))


def test_sky_ratio_tower_increases_volume_over_baseline():
    site = _site()
    result = compute_max_envelope(site, use_sky_ratio=True, **FAST_KW)
    baseline_volume = sum(b.volume for b in result.baseline_blocks)
    assert result.tower.extra_height_m > 0.0
    assert sum(b.volume for b in result.boosted_blocks) > baseline_volume
    assert all(c.ok for c in result.sky_ratio_checks)


def test_coverage_cap_limits_footprint():
    site = _site(coverage_ratio=0.3)  # 30% of 900 m2 = 270 m2
    result = compute_max_envelope(site, use_sky_ratio=False, **FAST_KW)
    assert result.coverage_cap_applied
    assert result.footprint_area_m2 <= 270.0 + 1.0


def test_far_cap_limits_total_floor_area():
    site = _site(far_ratio=0.5)  # 50% of 900 m2 = 450 m2
    result = compute_max_envelope(site, use_sky_ratio=False, **FAST_KW)
    assert result.far_cap_applied
    assert result.total_floor_area_m2 <= 450.0 + 1e-6


def test_final_blocks_always_pass_sky_ratio_check():
    site = _site(coverage_ratio=0.4, far_ratio=1.5)
    result = compute_max_envelope(site, use_sky_ratio=True, **FAST_KW)
    assert result.blocks
    assert all(c.ok for c in result.sky_ratio_checks)


def test_empty_site_regulation_returns_empty_result():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6, absolute_height_limit_m=0.0)
    edges = [Boundary(SQUARE[i], SQUARE[(i + 1) % 4], kind="none") for i in range(4)]
    site = Site(points=SQUARE, edges=edges, zoning=zoning)
    result = compute_max_envelope(site, **FAST_KW)
    assert result.blocks == []
    assert result.volume_m3 == 0.0
