"""法52条2項（前面道路幅員による容積率制限）のテスト。"""
import pytest

from mvce.far import compute_far
from mvce.site import Site
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(zone="1res", far=4.0, road_widths=(6.0,)):
    specs = []
    for i in range(4):
        if i < len(road_widths) and road_widths[i] is not None:
            specs.append({"kind": "road", "road_width_m": road_widths[i]})
        else:
            specs.append({"kind": "adjacent"})
    return Site.from_rings(
        SQUARE, specs, ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=0.6))


def test_residential_coefficient_is_four_tenths():
    # 6m × 0.4 = 240% < 指定400% なので道路幅員が効く
    result = compute_far(_site(zone="1res", far=4.0, road_widths=(6.0,)))
    assert result.coefficient == pytest.approx(0.4)
    assert result.road_far == pytest.approx(2.4)
    assert result.effective_far == pytest.approx(2.4)
    assert result.limited_by_road


def test_commercial_coefficient_is_six_tenths():
    # 6m × 0.6 = 360% < 指定600%
    result = compute_far(_site(zone="commercial", far=6.0, road_widths=(6.0,)))
    assert result.coefficient == pytest.approx(0.6)
    assert result.road_far == pytest.approx(3.6)
    assert result.effective_far == pytest.approx(3.6)


def test_designated_far_wins_when_smaller():
    # 8m × 0.4 = 320% だが指定が200%なので指定が優先
    result = compute_far(_site(zone="1res", far=2.0, road_widths=(8.0,)))
    assert result.road_far == pytest.approx(3.2)
    assert result.effective_far == pytest.approx(2.0)
    assert not result.limited_by_road


def test_no_reduction_at_twelve_metres_or_wider():
    result = compute_far(_site(zone="1res", far=4.0, road_widths=(12.0,)))
    assert result.road_far is None
    assert result.effective_far == pytest.approx(4.0)
    assert any("12m以上" in n for n in result.notes)


def test_widest_road_is_used_when_several():
    # 4m と 10m の2本 → 10m で判定 (10*0.4 = 400%)
    site = _site(zone="1res", far=6.0, road_widths=(4.0, 10.0))
    result = compute_far(site)
    assert result.max_road_width_m == pytest.approx(10.0)
    assert result.road_far == pytest.approx(4.0)
    assert any("2本" in n for n in result.notes)


def test_site_max_total_floor_area_uses_effective_far():
    site = _site(zone="1res", far=4.0, road_widths=(6.0,))
    # 600 m2 × 240% = 1440 m2（指定400%なら2400 m2だが道路で制限される）
    assert site.max_total_floor_area_m2() == pytest.approx(1440.0)


def test_no_road_falls_back_to_designated_with_warning():
    site = _site(zone="1res", far=4.0, road_widths=(None,))
    result = compute_far(site)
    assert result.effective_far == pytest.approx(4.0)
    assert any("前面道路が設定されていません" in n for n in result.notes)
