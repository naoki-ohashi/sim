import pytest

from jwcad_volume.envelope import compute_max_envelope
from jwcad_volume.regulations.shadow import ShadowRegulationParams
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (30, 0), (30, 30), (0, 30)]

FAST_KW = dict(n_layers=6, interval_m=10.0, n_azimuth=40, search_iterations=10)
FAST_SHADOW = dict(time_step_minutes=60.0, perimeter_sample_interval_m=10.0)


def _site():
    zoning = ZoningParams(zone_type="1res", far_ratio=1000.0, coverage_ratio=1.0)
    edges = [
        Boundary((0, 0), (30, 0), kind="road", road_width_m=6.0),
        Boundary((30, 0), (30, 30), kind="adjacent"),
        Boundary((30, 30), (0, 30), kind="none"),
        Boundary((0, 30), (0, 0), kind="none"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_no_shadow_params_skips_shadow_check():
    site = _site()
    result = compute_max_envelope(site, use_sky_ratio=False, **FAST_KW)
    assert result.shadow_checks is None
    assert result.shadow_height_scale == pytest.approx(1.0)


def test_lenient_shadow_params_do_not_shrink_building():
    site = _site()
    params = ShadowRegulationParams(line1_max_hours=8.0, line2_max_hours=8.0, **FAST_SHADOW)
    result = compute_max_envelope(site, use_sky_ratio=False, shadow_params=params, **FAST_KW)
    assert result.shadow_height_scale == pytest.approx(1.0)
    assert all(c.ok for c in result.shadow_checks)


def test_strict_shadow_params_shrink_building_until_compliant():
    site = _site()
    lenient = compute_max_envelope(site, use_sky_ratio=False, **FAST_KW)
    strict_params = ShadowRegulationParams(line1_max_hours=0.5, line2_max_hours=0.5, **FAST_SHADOW)
    result = compute_max_envelope(site, use_sky_ratio=False, shadow_params=strict_params, **FAST_KW)
    assert result.shadow_height_scale < 1.0
    assert all(c.ok for c in result.shadow_checks)
    assert result.volume_m3 < lenient.volume_m3
    assert all(c.ok for c in result.sky_ratio_checks)
