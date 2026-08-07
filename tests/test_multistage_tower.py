"""タワーの多段セットバック探索のテスト。"""
import pytest

from jwcad_volume.envelope import search_sky_ratio_tower
from jwcad_volume.massing import total_volume
from jwcad_volume.regulations.reference_building import reference_building_blocks
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (30, 0), (30, 30), (0, 30)]
SEARCH = dict(interval_m=10.0, n_azimuth=30, measurement_height=0.0, iterations=8)


def _site():
    # 容積率・建蔽率を実質無制限にして、天空率だけが効く条件にする
    zoning = ZoningParams(zone_type="1res", far_ratio=1000.0, coverage_ratio=1.0)
    edges = [
        Boundary((0, 0), (30, 0), kind="road", road_width_m=6.0),
        Boundary((30, 0), (30, 30), kind="adjacent"),
        Boundary((30, 30), (0, 30), kind="none"),
        Boundary((0, 30), (0, 0), kind="none"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def _baseline(site):
    return reference_building_blocks(site, n_layers=8)


def test_multistage_is_never_worse_than_single_stage():
    """各段の候補にセットバック0を含むので、多段化で解が悪化することはない。"""
    site = _site()
    base = _baseline(site)
    single = search_sky_ratio_tower(site, base, stage_insets_m=(0.0,), max_stages=1, **SEARCH)
    multi = search_sky_ratio_tower(site, base, stage_insets_m=(0.0, 3.0, 6.0), max_stages=2, **SEARCH)
    assert multi.volume_m3 >= single.volume_m3 - 1e-6


def test_multistage_beats_single_stage_on_this_site():
    site = _site()
    base = _baseline(site)
    single = search_sky_ratio_tower(site, base, stage_insets_m=(0.0,), max_stages=1, **SEARCH)
    multi = search_sky_ratio_tower(site, base, stage_insets_m=(0.0, 3.0, 6.0), max_stages=2, **SEARCH)
    assert multi.volume_m3 > single.volume_m3
    assert len(multi.stages) >= 2


def test_stages_step_inward_and_stack_without_gaps():
    site = _site()
    tower = search_sky_ratio_tower(
        _site(), _baseline(site), stage_insets_m=(0.0, 3.0, 6.0), max_stages=3, **SEARCH
    )
    assert tower.stages
    for lower, upper in zip(tower.stages, tower.stages[1:]):
        assert upper.inset_m >= lower.inset_m          # 上へ行くほど内側
        assert upper.footprint_area_m2 <= lower.footprint_area_m2 + 1e-6
        assert upper.z_bottom == pytest.approx(lower.z_top)  # 段の間に隙間がない
    assert tower.stages[0].z_bottom == pytest.approx(tower.split_height_m)


def test_extra_height_is_the_sum_of_stage_heights():
    site = _site()
    tower = search_sky_ratio_tower(site, _baseline(site), **SEARCH)
    assert tower.extra_height_m == pytest.approx(sum(s.height_m for s in tower.stages))


def test_tower_footprint_area_reports_the_lowest_stage():
    site = _site()
    tower = search_sky_ratio_tower(site, _baseline(site), **SEARCH)
    assert tower.tower_footprint_area_m2 == pytest.approx(tower.stages[0].footprint_area_m2)


def test_max_stages_is_respected():
    site = _site()
    tower = search_sky_ratio_tower(
        site, _baseline(site), stage_insets_m=(0.0, 2.0, 4.0), max_stages=1, **SEARCH
    )
    assert len(tower.stages) <= 1


def test_result_still_beats_or_matches_the_plain_baseline():
    site = _site()
    base = _baseline(site)
    tower = search_sky_ratio_tower(site, base, **SEARCH)
    assert tower.volume_m3 >= total_volume(base) - 1e-6


def test_empty_baseline_returns_empty_tower():
    tower = search_sky_ratio_tower(_site(), [], **SEARCH)
    assert tower.stages == []
    assert tower.blocks == []
    assert tower.extra_height_m == 0.0
    assert tower.tower_footprint_area_m2 == 0.0
