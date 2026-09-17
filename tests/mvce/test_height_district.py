"""高度地区（法58条）のテスト。

    第五十八条　高度地区内においては、建築物の高さは、高度地区に関する
    都市計画において定められた内容に適合するものでなければならない。

**法本体は数値を一切定めていません。** なので固定するのは値ではなく、
値の受け取り方と効かせ方です。とくに:

- 天空率（法56条7項）では**外れない**こと（適用除外は法56条1項1〜3号のみ）
- 令135条の4の緩和が**自動では効かない**こと（法56条1項3号の規定なので）
- 段の指定に隙間や重なりがあれば黙って進めず弾くこと
"""
import math

import pytest

from mvce.regulations.height_district import (
    HeightDistrict,
    HeightDistrictTier,
    compliance_notes,
    height_limit_at,
    required_setback_for_height,
)
from mvce.regulations.height_field import breakdown_at
from mvce.regulations.height_field import height_limit_at as field_limit_at
from mvce.site import Site
from mvce.zoning import ZoningParams

# 南に道路、北は隣地。真北は図面の上（north_angle_deg=0）。
SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
SPECS = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
         {"kind": "adjacent"}, {"kind": "adjacent"}]


def _site(district=None, zone="1res", abs_height=None):
    return Site.from_rings(
        SQUARE, SPECS,
        ZoningParams(zone_type=zone, far_ratio=4.0, coverage_ratio=0.6,
                     absolute_height_limit_m=abs_height),
        height_district=district)


def _single_tier(start=5.0, slope=0.6, **kw):
    kw.setdefault("include_road_width", False)
    return HeightDistrict(
        north_tiers=(HeightDistrictTier(start_height_m=start, slope=slope),), **kw)


# === 段の指定の検証 ===================================================

def test_tiers_must_start_at_zero():
    with pytest.raises(ValueError, match="距離0から"):
        HeightDistrict(
            north_tiers=(HeightDistrictTier(5.0, 0.6, from_distance_m=2.0),),
            include_road_width=False)


def test_tiers_must_not_have_a_gap():
    with pytest.raises(ValueError, match="繋がっていません"):
        HeightDistrict(
            north_tiers=(
                HeightDistrictTier(5.0, 0.6, 0.0, 8.0),
                HeightDistrictTier(10.0, 1.25, 10.0, None),
            ),
            include_road_width=False)


def test_tiers_must_not_overlap():
    with pytest.raises(ValueError, match="繋がっていません"):
        HeightDistrict(
            north_tiers=(
                HeightDistrictTier(5.0, 0.6, 0.0, 10.0),
                HeightDistrictTier(10.0, 1.25, 8.0, None),
            ),
            include_road_width=False)


def test_last_tier_must_be_open_ended():
    with pytest.raises(ValueError, match="以遠すべて"):
        HeightDistrict(
            north_tiers=(HeightDistrictTier(5.0, 0.6, 0.0, 20.0),),
            include_road_width=False)


def test_two_tiers_are_accepted():
    d = HeightDistrict(
        north_tiers=(
            HeightDistrictTier(5.0, 0.6, 0.0, 8.0),
            HeightDistrictTier(10.0, 1.25, 8.0, None),
        ),
        include_road_width=False)
    assert d.has_north_slant
    assert d.tier_at(4.0).slope == pytest.approx(0.6)
    assert d.tier_at(8.0).slope == pytest.approx(1.25)


def test_include_road_width_has_no_default():
    """北側が前面道路のときの起点は都市計画の定め方による。既定値を置かない。"""
    with pytest.raises(ValueError, match="include_road_width"):
        HeightDistrict(north_tiers=(HeightDistrictTier(5.0, 0.6),))


def test_min_above_max_is_rejected():
    with pytest.raises(ValueError, match="min_height_m"):
        HeightDistrict(max_height_m=10.0, min_height_m=20.0)


# === 高さ制限 =========================================================

def test_north_slant_uses_true_north_distance():
    """北側境界線は y=20 の辺。点 (15, 10) は真北方向に10m 手前。"""
    site = _site(_single_tier(start=5.0, slope=0.6))
    assert height_limit_at(site, (15.0, 10.0)) == pytest.approx(5.0 + 0.6 * 10.0)
    assert height_limit_at(site, (15.0, 20.0)) == pytest.approx(5.0)


def test_two_tiers_switch_at_the_boundary():
    d = HeightDistrict(
        north_tiers=(
            HeightDistrictTier(5.0, 0.6, 0.0, 8.0),
            HeightDistrictTier(10.0, 1.25, 8.0, None),
        ),
        include_road_width=False)
    site = _site(d)
    assert height_limit_at(site, (15.0, 20.0 - 7.9)) == pytest.approx(5.0 + 0.6 * 7.9)
    assert height_limit_at(site, (15.0, 20.0 - 8.1)) == pytest.approx(10.0 + 1.25 * 8.1)


def test_max_height_alone():
    site = _site(HeightDistrict(max_height_m=20.0))
    assert height_limit_at(site, (15.0, 10.0)) == pytest.approx(20.0)


def test_max_height_and_slant_take_the_stricter():
    site = _site(_single_tier(start=5.0, slope=0.6, max_height_m=8.0))
    # 斜線は 5 + 0.6×10 = 11m だが最高限度8m
    assert height_limit_at(site, (15.0, 10.0)) == pytest.approx(8.0)


def test_no_district_is_infinite():
    assert math.isinf(height_limit_at(_site(), (15.0, 10.0)))


def test_setback_relaxation_is_opt_in():
    """令135条の4の後退緩和は法58条には及ばない。都市計画が定めたときだけ。"""
    plain = _single_tier(start=5.0, slope=0.6)
    relaxed = _single_tier(start=5.0, slope=0.6, setback_relaxation_m=3.0)
    p = (15.0, 10.0)
    assert height_limit_at(_site(plain), p) == pytest.approx(11.0)
    assert height_limit_at(_site(relaxed), p) == pytest.approx(5.0 + 0.6 * 13.0)


def test_road_width_is_added_only_when_declared():
    """北側が道路の敷地。include_road_width で起点が変わる。"""
    specs = [{"kind": "adjacent"}, {"kind": "adjacent"},
             {"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"}]
    zoning = ZoningParams("1res", 4.0, 0.6)
    for include, expected in ((False, 5.0 + 0.6 * 10.0), (True, 5.0 + 0.6 * 16.0)):
        d = HeightDistrict(
            north_tiers=(HeightDistrictTier(5.0, 0.6),), include_road_width=include)
        site = Site.from_rings(SQUARE, specs, zoning, height_district=d)
        assert height_limit_at(site, (15.0, 10.0)) == pytest.approx(expected)


# === 天空率では外れない（食い違い G）=================================

def test_sky_ratio_does_not_remove_the_height_district():
    """法56条7項の適用除外は法56条1項1号〜3号だけ。法58条は入っていない。"""
    site = _site(_single_tier(start=5.0, slope=0.6))
    point = (15.0, 10.0)
    assert field_limit_at(site, point, use_sky_ratio=True) == pytest.approx(11.0)


def test_sky_ratio_still_removes_the_slants():
    """比較のため: 高度地区が無ければ天空率で斜線は外れる。"""
    site = _site(None, abs_height=None)
    assert math.isinf(field_limit_at(site, (15.0, 10.0), use_sky_ratio=True))


def test_sky_ratio_takes_the_stricter_of_absolute_and_district():
    site = _site(_single_tier(start=5.0, slope=0.6), abs_height=10.0)
    assert field_limit_at(site, (15.0, 10.0), use_sky_ratio=True) == pytest.approx(10.0)


# === height_field への組み込み ========================================

def test_breakdown_reports_the_height_district():
    site = _site(_single_tier(start=5.0, slope=0.2))   # 5 + 0.2×10 = 7m
    b = breakdown_at(site, (15.0, 10.0))
    assert b.height_district_m == pytest.approx(7.0)
    assert b.limit_m == pytest.approx(7.0)
    assert b.governing == "height_district"


def test_breakdown_without_a_district():
    b = breakdown_at(_site(), (15.0, 10.0))
    assert math.isinf(b.height_district_m)
    assert b.governing != "height_district"


# === 必要な後退距離 ===================================================

def test_required_setback_single_tier():
    site = _site(_single_tier(start=5.0, slope=0.6))
    # 高さ11m には L = (11−5)/0.6 = 10m
    assert required_setback_for_height(site, 2, 11.0) == pytest.approx(10.0)
    assert required_setback_for_height(site, 2, 5.0) == pytest.approx(0.0)


def test_required_setback_subtracts_the_declared_relaxation():
    site = _site(_single_tier(start=5.0, slope=0.6, setback_relaxation_m=4.0))
    assert required_setback_for_height(site, 2, 11.0) == pytest.approx(6.0)


def test_required_setback_is_infinite_above_the_max_height():
    site = _site(_single_tier(start=5.0, slope=0.6, max_height_m=9.0))
    assert math.isinf(required_setback_for_height(site, 2, 12.0))


def test_required_setback_with_a_flat_tier():
    """slope=0 の段は水平な上限。その高さまでならその段の始点で足りる。"""
    d = HeightDistrict(
        north_tiers=(
            HeightDistrictTier(10.0, 0.0, 0.0, 5.0),
            HeightDistrictTier(10.0, 1.0, 5.0, None),
        ),
        include_road_width=False)
    site = _site(d)
    assert required_setback_for_height(site, 2, 10.0) == pytest.approx(0.0)
    # 2段目は H = 10 + 1.0×L（L≥5）。H=20 なら L=10 で、2段目の範囲内。
    assert required_setback_for_height(site, 2, 20.0) == pytest.approx(10.0)
    # H=12 なら L=2 だが2段目は L≥5 から。範囲に収まらないので L=5 まで下がる
    assert required_setback_for_height(site, 2, 12.0) == pytest.approx(5.0)


# === 注記 =============================================================

def test_notes_say_the_sky_ratio_does_not_help():
    notes = compliance_notes(_site(_single_tier()), 10.0)
    assert any("天空率" in n and "緩和されません" in n for n in notes)


def test_notes_flag_a_building_below_the_minimum_height():
    d = HeightDistrict(min_height_m=12.0, name="第○種高度地区")
    notes = compliance_notes(_site(d), 9.0)
    assert any("最低限度" in n and "下回っています" in n for n in notes)


def test_notes_do_not_flag_when_the_minimum_is_met():
    d = HeightDistrict(min_height_m=12.0)
    assert not any("下回っています" in n for n in compliance_notes(_site(d), 12.0))


def test_no_notes_without_a_district():
    assert compliance_notes(_site(), 10.0) == []


def test_describe_ja_lists_the_content():
    d = _single_tier(start=5.0, slope=0.6, name="第一種高度地区", max_height_m=20.0)
    text = d.describe_ja()
    assert "第一種高度地区" in text and "20.0m" in text and "0.60" in text


# === 最適化ループ =====================================================

def test_optimizer_respects_the_height_district():
    from mvce.solvers.optimizer import OptimizeOptions, optimize

    options = OptimizeOptions(cell_size_x_m=5.0, cell_size_y_m=5.0)
    plain = optimize(_site(), None, options)
    limited = optimize(_site(_single_tier(start=5.0, slope=0.3)), None, options)
    assert limited.max_height_m < plain.max_height_m
    assert any("高度地区（法58条）" in n for n in limited.summary_lines_ja())
