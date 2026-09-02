"""敷地が用途地域の2以上にわたる場合のテスト。

按分する側（法52条7項・法53条2項）と、按分**しない**側（法56条5項・
別表第三（い）欄・令135条の13）の区別を固定します。ここを取り違えると
全部間違うので、両方を明示的に押さえます。
"""
import pytest

from mvce.far import compute_far
from mvce.regulations.height_field import (
    breakdown_at,
    height_limit_at,
    max_relevant_height,
    required_setback_for_height,
)
from mvce.regulations.shadow import ShadowRegulationSpec, regulation_boundary
from mvce.site import Site
from mvce.zone_split import (
    ZonePart,
    ZoneSplit,
    far_limit_for,
    require_single_zone_type,
    weighted_coverage_limit,
    weighted_far_limit,
)
from mvce.zoning import UndeterminedRegulation, ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]   # 600 m2
SPECS = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
         {"kind": "adjacent"}, {"kind": "adjacent"}]


def _zoning(zone, far, coverage=0.6):
    return ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=coverage)


def _split(*parts):
    return ZoneSplit(tuple(ZonePart(_zoning(z, f, c), a, label=z)
                           for z, f, c, a in parts))


def _site(split=None, zone="1res", far=2.0, coverage=0.6, road_width=6.0):
    specs = [dict(s) for s in SPECS]
    specs[0]["road_width_m"] = road_width
    return Site.from_rings(SQUARE, specs, _zoning(zone, far, coverage),
                           zone_split=split)


# === 法52条7項（容積率の按分）========================================

def test_single_part_is_not_prorated():
    split = _split(("1res", 2.0, 0.6, 600.0))
    value, notes = weighted_far_limit(split, 12.0)
    assert value == pytest.approx(2.0)
    assert notes == []


def test_far_is_area_weighted():
    """1住居 200%（300m2）と近商 400%（300m2）。道路12m以上で2項は効かない。"""
    split = _split(("1res", 2.0, 0.6, 300.0), ("neighbor_commercial", 4.0, 0.8, 300.0))
    value, _ = weighted_far_limit(split, 12.0)
    assert value == pytest.approx(3.0)


def test_far_weighting_uses_the_road_coefficient_of_each_zone():
    """**係数が用途地域ごとに違う**のが法52条7項の肝。

    前面道路6m は敷地に1つだが、住居系は 4/10、近商は 6/10。
      1住居: min(200%, 6×0.4=240%) = 200%
      近商:  min(400%, 6×0.6=360%) = 360%
    面積が半々なら (200+360)/2 = 280%。
    """
    split = _split(("1res", 2.0, 0.6, 300.0), ("neighbor_commercial", 4.0, 0.8, 300.0))
    value, notes = weighted_far_limit(split, 6.0)
    assert far_limit_for(split.parts[0].zoning, 6.0) == pytest.approx(2.0)
    assert far_limit_for(split.parts[1].zoning, 6.0) == pytest.approx(3.6)
    assert value == pytest.approx(2.8)
    assert any("法52条7項" in n for n in notes)


def test_far_weighting_is_by_area_not_by_count():
    split = _split(("1res", 2.0, 0.6, 500.0), ("commercial", 6.0, 0.8, 100.0))
    value, _ = weighted_far_limit(split, 12.0)
    assert value == pytest.approx(2.0 * 500 / 600 + 6.0 * 100 / 600)


def test_far_limit_for_respects_the_12m_threshold():
    """条文は「十二メートル未満」。ちょうど12mは低減しない。"""
    z = _zoning("1res", 6.0)                                # 指定600%
    assert far_limit_for(z, 12.0) == pytest.approx(6.0)     # 12m以上は低減なし
    assert far_limit_for(z, 11.9) == pytest.approx(11.9 * 0.4)
    assert far_limit_for(z, 0.0) == pytest.approx(6.0)      # 前面道路なし


def test_far_limit_for_takes_the_smaller_of_the_two():
    """法52条2項は上限の1つ。指定容積率の方が小さければそちらが効く。"""
    assert far_limit_for(_zoning("1res", 2.0), 11.9) == pytest.approx(2.0)


# === 法53条2項（建蔽率の按分）========================================

def test_coverage_is_area_weighted():
    split = _split(("1res", 2.0, 0.6, 300.0), ("commercial", 6.0, 0.8, 300.0))
    value, notes = weighted_coverage_limit(split)
    assert value == pytest.approx(0.7)
    assert any("法53条2項" in n for n in notes)


def test_site_max_building_area_uses_the_weighted_coverage():
    split = _split(("1res", 2.0, 0.6, 300.0), ("commercial", 6.0, 0.8, 300.0))
    site = _site(split)
    assert site.coverage_ratio_limit() == pytest.approx(0.7)
    assert site.max_building_area_m2() == pytest.approx(600.0 * 0.7)


def test_single_zone_site_is_unchanged():
    site = _site()
    assert site.coverage_ratio_limit() == pytest.approx(0.6)
    assert site.max_building_area_m2() == pytest.approx(360.0)


# === compute_far との繋ぎ =============================================

def test_compute_far_prorates():
    split = _split(("1res", 2.0, 0.6, 300.0), ("neighbor_commercial", 4.0, 0.8, 300.0))
    result = compute_far(_site(split, zone="1res", road_width=6.0))
    assert result.effective_far == pytest.approx(2.8)
    assert any("法52条7項" in n for n in result.notes)
    assert any("按分しません" in n for n in result.notes)


def test_compute_far_split_reports_the_road_limitation():
    split = _split(("1res", 4.0, 0.6, 300.0), ("commercial", 8.0, 0.8, 300.0))
    result = compute_far(_site(split, zone="1res", road_width=6.0))
    # 1住居: min(400%, 240%) = 240% / 商業: min(800%, 360%) = 360%
    assert result.effective_far == pytest.approx(3.0)
    assert result.limited_by_road
    assert result.designated_far == pytest.approx(6.0)   # 1項だけの按分


def test_specified_road_addition_reaches_the_prorated_far():
    """法52条9項の読み替えは「第二項から第七項まで」。7項にも及ぶ。"""
    specs = [dict(s) for s in SPECS]
    specs[0]["road_width_m"] = 6.0
    specs[0]["specified_road"] = {"width_m": 16.0, "distance_m": 35.0}
    split = _split(("1res", 4.0, 0.6, 300.0), ("commercial", 8.0, 0.8, 300.0))
    site = Site.from_rings(SQUARE, specs, _zoning("1res", 4.0), zone_split=split)
    result = compute_far(site)
    # 幅員 6 + 3 = 9m。1住居 min(400%, 360%)=360% / 商業 min(800%, 540%)=540%
    assert result.max_road_width_m == pytest.approx(9.0)
    assert result.effective_far == pytest.approx(4.5)


# === 按分しない側 =====================================================

def test_slant_refuses_when_zones_differ():
    split = _split(("1res", 2.0, 0.6, 300.0), ("commercial", 6.0, 0.8, 300.0))
    site = _site(split)
    with pytest.raises(UndeterminedRegulation, match="部分ごと"):
        breakdown_at(site, (15.0, 10.0))
    with pytest.raises(UndeterminedRegulation):
        height_limit_at(site, (15.0, 10.0))
    with pytest.raises(UndeterminedRegulation):
        required_setback_for_height(site, 0, 12.0)
    with pytest.raises(UndeterminedRegulation):
        max_relevant_height(site)


def test_shadow_refuses_when_zones_differ():
    split = _split(("1res", 2.0, 0.6, 300.0), ("commercial", 6.0, 0.8, 300.0))
    spec = ShadowRegulationSpec(measurement_height_m=4.0, line_5m_max_hours=5.0,
                                line_10m_max_hours=3.0)
    with pytest.raises(UndeterminedRegulation, match="日影"):
        regulation_boundary(_site(split), spec)


def test_same_zone_type_twice_does_not_block_the_slant():
    """用途地域が同じで容積率だけ違う区分（高度利用地区等）なら斜線は判定できる。"""
    split = _split(("1res", 2.0, 0.6, 300.0), ("1res", 4.0, 0.6, 300.0))
    site = _site(split)
    assert breakdown_at(site, (15.0, 10.0)).limit_m > 0


def test_guard_is_a_no_op_without_a_split():
    require_single_zone_type(None, "斜線制限")
    require_single_zone_type(_split(("1res", 2.0, 0.6, 600.0)), "斜線制限")


def test_guard_message_names_the_zones():
    split = _split(("1res", 2.0, 0.6, 300.0), ("commercial", 6.0, 0.8, 300.0))
    with pytest.raises(UndeterminedRegulation) as e:
        require_single_zone_type(split, "斜線制限（法56条）")
    assert "1res" in str(e.value) and "commercial" in str(e.value)
    assert "法56条5項" in str(e.value)


# === 入力の検証 =======================================================

def test_areas_must_sum_to_the_site_area():
    split = _split(("1res", 2.0, 0.6, 300.0), ("commercial", 6.0, 0.8, 200.0))
    with pytest.raises(ValueError, match="一致しません"):
        _site(split)


def test_site_zoning_must_be_one_of_the_parts():
    split = _split(("1res", 2.0, 0.6, 300.0), ("commercial", 6.0, 0.8, 300.0))
    with pytest.raises(ValueError, match="どの区域にもありません"):
        _site(split, zone="industrial")


def test_zero_area_part_is_rejected():
    with pytest.raises(ValueError, match="正の値"):
        ZonePart(_zoning("1res", 2.0), 0.0)


def test_empty_split_is_rejected():
    with pytest.raises(ValueError, match="区分が1つもありません"):
        ZoneSplit(())


def test_fractions_sum_to_one():
    split = _split(("1res", 2.0, 0.6, 200.0), ("commercial", 6.0, 0.8, 400.0))
    assert sum(split.fractions()) == pytest.approx(1.0)
    assert split.largest().zoning.zone_type == "commercial"


def test_distinct_zone_types_keeps_order_and_dedupes():
    split = _split(("commercial", 6.0, 0.8, 200.0), ("1res", 2.0, 0.6, 200.0),
                   ("commercial", 8.0, 0.8, 200.0))
    assert split.distinct_zone_types == ("commercial", "1res")
