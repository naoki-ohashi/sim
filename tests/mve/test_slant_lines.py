"""斜線制限と法定緩和のテスト（法56条1項、令132・134・135の2〜4）。"""
import math

import pytest

from mve.north import NorthReference
from mve.regulations import adjacent_slant, north_slant, road_slant
from mve.site import Site
from mve.zoning import ZoningParams

# 南に道路、東西が隣地、北が隣地の 30m x 20m 敷地
SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(zone="1res", far=2.0, specs=None, north_angle=0.0, absolute_height=None):
    if specs is None:
        specs = [
            {"kind": "road", "road_width_m": 6.0},
            {"kind": "adjacent"},
            {"kind": "adjacent"},
            {"kind": "adjacent"},
        ]
    return Site.from_rings(
        SQUARE, specs,
        ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=0.6,
                     absolute_height_limit_m=absolute_height),
        north=NorthReference(north_angle_deg=north_angle),
    )


# === 道路斜線 =========================================================

def test_road_slant_at_boundary_uses_road_width():
    site = _site()
    # 道路境界線上: L = 6m、住居系なので勾配1.25 → 7.5m
    assert road_slant.height_limit_at(site, (15.0, 0.0)) == pytest.approx(7.5)


def test_road_slant_increases_with_distance():
    site = _site()
    # 10m 入った点: L = 6 + 10 = 16 → 20m
    assert road_slant.height_limit_at(site, (15.0, 10.0)) == pytest.approx(20.0)


def test_road_slant_beyond_applicable_distance_is_unlimited():
    site = _site(far=2.0)  # 適用距離20m
    # L = 6 + 15 = 21 > 20 → 制限なし
    assert road_slant.height_limit_at(site, (15.0, 15.0)) == math.inf


def test_road_slant_commercial_slope_is_1_5():
    site = _site(zone="commercial", far=4.0)
    assert road_slant.height_limit_at(site, (15.0, 0.0)) == pytest.approx(1.5 * 6.0)


def test_road_slant_wall_setback_relaxation():
    """令130条の12: 壁面後退した分だけ反対側境界線が外側にあるとみなす。"""
    specs = [
        {"kind": "road", "road_width_m": 6.0, "wall_setback_m": 4.0},
        {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    site = _site(specs=specs)
    # L = 0 + 6 + 4 = 10 → 12.5m（後退なしなら7.5m）
    assert road_slant.height_limit_at(site, (15.0, 0.0)) == pytest.approx(12.5)


def test_road_slant_park_relaxation_adds_full_width():
    """令134条: 道路の反対側の公園等の幅を全部加える。"""
    specs = [
        {"kind": "road", "road_width_m": 6.0,
         "relaxation": {"kind": "park", "width_m": 10.0}},
        {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    site = _site(specs=specs)
    # L = 0 + 6 + 10 = 16 → 20m
    assert road_slant.height_limit_at(site, (15.0, 0.0)) == pytest.approx(20.0)


def test_road_slant_level_difference_relaxation():
    """令135条の2: 地盤面が道路より1m以上低い場合 (h-1)/2 だけ緩和。"""
    specs = [
        {"kind": "road", "road_width_m": 6.0, "ground_level_diff_m": 3.0},
        {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    site = _site(specs=specs)
    # 7.5 + (3-1)/2 = 8.5
    assert road_slant.height_limit_at(site, (15.0, 0.0)) == pytest.approx(8.5)


def test_road_slant_level_difference_under_one_metre_has_no_effect():
    specs = [
        {"kind": "road", "road_width_m": 6.0, "ground_level_diff_m": 0.8},
        {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    assert road_slant.height_limit_at(_site(specs=specs), (15.0, 0.0)) == pytest.approx(7.5)


# === 令132条: 2以上の前面道路 =========================================

def _two_road_site():
    """南に4m道路、東に10m道路。"""
    specs = [
        {"kind": "road", "road_width_m": 4.0},   # 南
        {"kind": "road", "road_width_m": 10.0},  # 東
        {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    return _site(far=4.0, specs=specs)


def test_article_132_widens_narrow_road_near_the_wide_one():
    site = _two_road_site()
    # 東の10m道路(x=30)から5mの点 → 2A=20m以内かつ35m以内なので南の4m道路も
    # 10m幅とみなされる
    width, widened = road_slant.applied_width_at(site, (25.0, 2.0), site.edges[0])
    assert widened
    assert width == pytest.approx(10.0)


def test_article_132_does_not_widen_far_from_the_wide_road():
    site = _two_road_site()
    # 東の道路から28m（2A=20mを超える）、かつ南の4m道路の中心線から
    # 2+2=4m（10m以下）なので読み替えなし
    width, widened = road_slant.applied_width_at(site, (2.0, 2.0), site.edges[0])
    assert not widened
    assert width == pytest.approx(4.0)


def test_article_132_centreline_rule_widens_deep_in_the_site():
    site = _two_road_site()
    # 南の4m道路の中心線から 12+2 = 14m > 10m なので読み替えられる
    width, widened = road_slant.applied_width_at(site, (2.0, 12.0), site.edges[0])
    assert widened
    assert width == pytest.approx(10.0)


def test_article_132_raises_the_height_limit():
    site = _two_road_site()
    point = (25.0, 2.0)
    detail = road_slant.detail_at(site, point, 0)
    assert detail.widened_by_article_132
    # L = 2 + 10 = 12 → 15m（読み替えが無ければ L = 2+4 = 6 → 7.5m）
    assert detail.height_limit_m == pytest.approx(15.0)


def test_single_road_is_never_widened():
    site = _site()
    _, widened = road_slant.applied_width_at(site, (15.0, 10.0), site.edges[0])
    assert not widened


# === 隣地斜線 =========================================================

def test_adjacent_slant_residential_starts_at_20m():
    site = _site()
    assert adjacent_slant.height_limit_at(site, (30.0, 10.0)) == pytest.approx(20.0)
    assert adjacent_slant.height_limit_at(site, (26.0, 10.0)) == pytest.approx(20.0 + 1.25 * 4)


def test_adjacent_slant_other_group_starts_at_31m():
    site = _site(zone="commercial", far=4.0)
    assert adjacent_slant.height_limit_at(site, (30.0, 10.0)) == pytest.approx(31.0)


def test_adjacent_slant_not_applied_in_low_rise_zones():
    """低層住居専用は絶対高さ制限が先に効くので隣地斜線の適用がない。"""
    site = _site(zone="1low", far=0.8)
    assert not adjacent_slant.applies(site)
    assert adjacent_slant.height_limit_at(site, (30.0, 10.0)) == math.inf


def test_adjacent_slant_park_relaxation_is_half_width():
    """令135条の3: 隣地は幅の1/2（道路斜線の令134条は全部）。"""
    specs = [
        {"kind": "road", "road_width_m": 6.0},
        {"kind": "adjacent", "relaxation": {"kind": "park", "width_m": 8.0}},
        {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    site = _site(specs=specs)
    # L = 0 + 8/2 = 4 → 20 + 1.25*4 = 25
    assert adjacent_slant.edge_height_limit(site, 1, (30.0, 10.0)) == pytest.approx(25.0)


def test_adjacent_slant_setback_relaxation():
    specs = [
        {"kind": "road", "road_width_m": 6.0},
        {"kind": "adjacent", "wall_setback_m": 4.0},
        {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    site = _site(specs=specs)
    assert adjacent_slant.edge_height_limit(site, 1, (30.0, 10.0)) == pytest.approx(20.0 + 1.25 * 4)


# === 北側斜線 =========================================================

def test_north_slant_applies_only_in_designated_zones():
    assert north_slant.applies(_site(zone="1low", far=0.8))
    assert north_slant.applies(_site(zone="1mid", far=2.0))
    assert not north_slant.applies(_site(zone="1res"))
    assert not north_slant.applies(_site(zone="commercial", far=4.0))


def test_north_slant_low_rise_starts_at_5m():
    site = _site(zone="1low", far=0.8)
    # 北側境界線(y=20)上 → 5m
    assert north_slant.height_limit_at(site, (15.0, 20.0)) == pytest.approx(5.0)
    # 8m 南に離れる → 5 + 1.25*8 = 15
    assert north_slant.height_limit_at(site, (15.0, 12.0)) == pytest.approx(15.0)


def test_north_slant_mid_rise_starts_at_10m():
    site = _site(zone="1mid", far=2.0)
    assert north_slant.height_limit_at(site, (15.0, 20.0)) == pytest.approx(10.0)


def test_north_slant_has_no_setback_relaxation():
    """北側斜線には後退緩和が無い（他の斜線との決定的な違い）。"""
    specs = [
        {"kind": "road", "road_width_m": 6.0},
        {"kind": "adjacent"},
        {"kind": "adjacent", "wall_setback_m": 5.0},  # 北側に大きく後退
        {"kind": "adjacent"},
    ]
    site = _site(zone="1low", far=0.8, specs=specs)
    # 後退させても境界線上の制限は5mのまま
    assert north_slant.height_limit_at(site, (15.0, 20.0)) == pytest.approx(5.0)


def test_north_slant_park_relaxation_does_not_apply():
    """令135条の4の対象は水面・線路敷のみ。公園・広場は緩和されない。"""
    specs = [
        {"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
        {"kind": "adjacent", "relaxation": {"kind": "park", "width_m": 10.0}},
        {"kind": "adjacent"},
    ]
    site = _site(zone="1low", far=0.8, specs=specs)
    assert north_slant.height_limit_at(site, (15.0, 20.0)) == pytest.approx(5.0)


def test_north_slant_water_relaxation_is_half_width():
    specs = [
        {"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
        {"kind": "adjacent", "relaxation": {"kind": "water", "width_m": 8.0}},
        {"kind": "adjacent"},
    ]
    site = _site(zone="1low", far=0.8, specs=specs)
    # L = 0 + 8/2 = 4 → 5 + 1.25*4 = 10
    assert north_slant.height_limit_at(site, (15.0, 20.0)) == pytest.approx(10.0)


def test_north_slant_follows_true_north_not_plan_up():
    """真北が図面の上でない場合、北側と判定される辺が変わる。"""
    site_default = _site(zone="1low", far=0.8)
    assert north_slant.north_edges(site_default) == [2]  # y=20 の辺

    # 真北が図面の左（-X）を向く → x=0 の辺が北側になる
    site_rotated = _site(zone="1low", far=0.8, north_angle=90.0)
    assert north_slant.north_edges(site_rotated) == [3]


def test_north_slant_measures_distance_along_true_north():
    site = _site(zone="1low", far=0.8, north_angle=90.0)  # 真北 = -X
    # 北側境界は x=0。そこから東へ8m離れた点 → 5 + 1.25*8 = 15
    assert north_slant.height_limit_at(site, (8.0, 10.0)) == pytest.approx(15.0)
