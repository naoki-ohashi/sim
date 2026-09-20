"""天空率の算定位置（令135条の9・10・11、法56条7項各号）のテスト。

規制ごとに基準線も間隔も高さも違うので、取り違えを固定します。

| 規制 | 基準線 | 中心の高さ | 間隔 |
|---|---|---|---|
| 道路 | 前面道路の反対側の境界線 | 路面の中心 | 幅員の1/2 |
| 隣地 | 境界線から16m（1.25）/ 12.4m（2.5）外側 | 敷地の地盤面 | 8m / 6.2m |
| 北側 | 真北方向に4m（低層）/ 8m（中高層）外側 | 敷地の地盤面 | 1m / 2m |
"""
import math

import pytest

from mvce.north import NorthReference
from mvce.regulations.sky_positions import (
    ADJACENT_BASELINE_M,
    ADJACENT_INTERVAL_M,
    NORTH_BASELINE_M,
    NORTH_INTERVAL_M,
    adjacent_positions,
    all_positions,
    north_positions,
    road_positions,
)
from mvce.site import Site
from mvce.zoning import ZoningParams

# 南=道路、東・北・西=隣地。真北は図面の上。
SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(zone="1res", far=2.0, road=6.0, north_angle=0.0, specs=None,
          coverage=0.6, height=None):
    if specs is None:
        specs = [{"kind": "road", "road_width_m": road}, {"kind": "adjacent"},
                 {"kind": "adjacent"}, {"kind": "adjacent"}]
    return Site.from_rings(
        SQUARE, specs,
        ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=coverage,
                     absolute_height_limit_m=height),
        north=NorthReference(north_angle_deg=north_angle))


# === 条文の数値 =======================================================

def test_statutory_constants():
    """法56条7項2号・3号と令135条の10・11 の数値。"""
    assert ADJACENT_BASELINE_M == {1.25: 16.0, 2.5: 12.4}
    assert ADJACENT_INTERVAL_M == {1.25: 8.0, 2.5: 6.2}
    assert NORTH_BASELINE_M == {"1low": 4.0, "2low": 4.0, "denen": 4.0,
                                "1mid": 8.0, "2mid": 8.0}
    assert NORTH_INTERVAL_M == {"1low": 1.0, "2low": 1.0, "denen": 1.0,
                                "1mid": 2.0, "2mid": 2.0}


# === 道路（令135条の9）================================================

def test_road_positions_are_on_the_opposite_boundary():
    positions = road_positions(_site(road=6.0))
    assert positions
    for p in positions:
        assert p.kind == "road"
        assert p.point[1] == pytest.approx(-6.0)   # 南辺 y=0 の外側6m


def test_road_interval_is_half_the_width():
    """令135条の9第1項2号: 幅員の1/2以内。30mの辺・幅員6m → 3m間隔で11点。"""
    positions = road_positions(_site(road=6.0))
    assert len(positions) == 11
    xs = [p.point[0] for p in positions]
    assert xs[0] == pytest.approx(0.0)
    assert xs[-1] == pytest.approx(30.0)
    for a, b in zip(xs, xs[1:]):
        assert abs(b - a) == pytest.approx(3.0)


def test_wider_road_means_fewer_points():
    """幅員が広いほど間隔も広い。20m道路なら10m間隔で4点（30mの辺）。"""
    assert len(road_positions(_site(road=20.0))) == 4


def test_road_positions_include_both_ends_even_when_the_span_is_short():
    """1号の両端は常に置く。2号は「超えるとき」だけ。"""
    site = Site.from_rings(
        [(0.0, 0.0), (5.0, 0.0), (5.0, 20.0), (0.0, 20.0)],
        [{"kind": "road", "road_width_m": 20.0}, {"kind": "adjacent"},
         {"kind": "adjacent"}, {"kind": "adjacent"}],
        ZoningParams("1res", 2.0, 0.6))
    # 辺5m < 幅員の1/2 = 10m なので両端の2点だけ
    assert len(road_positions(site)) == 2


def test_road_position_height_is_the_road_surface_centre():
    """令135条の9第1項: 路面の中心の高さ。"""
    specs = [{"kind": "road", "road_width_m": 6.0, "ground_level_diff_m": 1.5},
             {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"}]
    # 路面が敷地より1.5m高い。敷地は低いので第4項の緩和は無い
    assert road_positions(_site(specs=specs))[0].z_m == pytest.approx(1.5)


def test_road_position_height_applies_article_135_9_paragraph_4():
    """第4項: 敷地の地盤面が路面中心より1m以上高いとき (高低差−1)/2 だけ高くみなす。

    路面が敷地より3m低い（敷地が3m高い）→ 路面 −3m、みなしは
    −3 + (3−1)/2 = −2m。
    """
    specs = [{"kind": "road", "road_width_m": 6.0, "ground_level_diff_m": -3.0},
             {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"}]
    assert road_positions(_site(specs=specs))[0].z_m == pytest.approx(-2.0)


def test_road_level_difference_under_1m_gets_no_relaxation():
    specs = [{"kind": "road", "road_width_m": 6.0, "ground_level_diff_m": -0.9},
             {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"}]
    assert road_positions(_site(specs=specs))[0].z_m == pytest.approx(-0.9)


# === 隣地（令135条の10）===============================================

def test_adjacent_baseline_is_16m_out_for_slope_1_25():
    """1住居は勾配1.25。基準線は隣地境界線から16m外側（法56条7項2号）。"""
    positions = adjacent_positions(_site(zone="1res"))
    east = [p for p in positions if p.edge_index == 1]
    assert east
    for p in east:
        assert p.point[0] == pytest.approx(30.0 + 16.0)


def test_adjacent_baseline_is_12_4m_out_for_slope_2_5():
    positions = adjacent_positions(_site(zone="commercial", far=6.0))
    east = [p for p in positions if p.edge_index == 1]
    for p in east:
        assert p.point[0] == pytest.approx(30.0 + 12.4)


def test_adjacent_interval_is_8m_for_slope_1_25():
    """令135条の10第1項2号: 1.25 は8m以内。20mの東辺 → 8m超なので3区間4点。"""
    east = [p for p in adjacent_positions(_site(zone="1res")) if p.edge_index == 1]
    assert len(east) == 4
    ys = sorted(p.point[1] for p in east)
    for a, b in zip(ys, ys[1:]):
        assert abs(b - a) == pytest.approx(20.0 / 3.0)
        assert abs(b - a) <= 8.0 + 1e-9


def test_adjacent_interval_is_6_2m_for_slope_2_5():
    east = [p for p in adjacent_positions(_site(zone="commercial", far=6.0))
            if p.edge_index == 1]
    ys = sorted(p.point[1] for p in east)
    for a, b in zip(ys, ys[1:]):
        assert abs(b - a) <= 6.2 + 1e-9


def test_no_adjacent_positions_where_the_adjacent_slant_does_not_apply():
    """低層住専は隣地斜線が無い（絶対高さ制限で代わる）。"""
    assert adjacent_positions(_site(zone="1low", far=0.8, height=10.0)) == []


def test_adjacent_position_height_applies_article_135_10_paragraph_4():
    """第4項: 敷地が隣地より1m以上低いとき (高低差−1)/2 だけ高くみなす。"""
    specs = [{"kind": "road", "road_width_m": 6.0},
             {"kind": "adjacent", "ground_level_diff_m": 3.0},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    east = [p for p in adjacent_positions(_site(specs=specs)) if p.edge_index == 1]
    assert east[0].z_m == pytest.approx(1.0)      # (3−1)/2


def test_adjacent_position_height_is_zero_without_a_level_difference():
    east = [p for p in adjacent_positions(_site()) if p.edge_index == 1]
    assert east[0].z_m == pytest.approx(0.0)


# === 北側（令135条の11）===============================================

def test_north_baseline_is_4m_north_for_low_rise():
    """低層住専は真北方向に4m（法56条7項3号）。北辺 y=20 → y=24。"""
    positions = north_positions(_site(zone="1low", far=0.8, height=10.0))
    assert positions
    for p in positions:
        assert p.point[1] == pytest.approx(24.0)


def test_north_baseline_is_8m_north_for_mid_rise():
    positions = north_positions(_site(zone="1mid", far=2.0))
    for p in positions:
        assert p.point[1] == pytest.approx(28.0)


def test_north_interval_is_1m_for_low_rise():
    """令135条の11第1項2号: 低層住専は1m以内。30mの北辺 → 31点。

    以前は2m間隔だったので、条文より粗く（危険側）でした。
    """
    positions = north_positions(_site(zone="1low", far=0.8, height=10.0))
    assert len(positions) == 31
    xs = sorted(p.point[0] for p in positions)
    for a, b in zip(xs, xs[1:]):
        assert abs(b - a) == pytest.approx(1.0)


def test_north_interval_is_2m_for_mid_rise():
    positions = north_positions(_site(zone="1mid", far=2.0))
    assert len(positions) == 16
    xs = sorted(p.point[0] for p in positions)
    for a, b in zip(xs, xs[1:]):
        assert abs(b - a) == pytest.approx(2.0)


def test_no_north_positions_where_the_north_slant_does_not_apply():
    assert north_positions(_site(zone="commercial", far=6.0)) == []


def test_north_offset_follows_true_north_not_the_perpendicular():
    """令135条の11第1項1号は「真北方向の」。垂線ではありません。

    真北を反時計回りに30度振ると、北辺 y=20 の位置は真北ベクトル
    (-sin30, cos30) の方向へ4mずれます。
    """
    site = _site(zone="1low", far=0.8, height=10.0, north_angle=30.0)
    nx, ny = site.north.north_vector
    positions = north_positions(site)
    # 真北を向く辺の1つを取り、その端点からのずれを見る
    edge = site.edges[positions[0].edge_index]
    moved = (positions[0].point[0] - edge.p1[0], positions[0].point[1] - edge.p1[1])
    # ずれの向きが真北ベクトルと平行で、長さが4m
    assert math.hypot(*moved) == pytest.approx(4.0)
    assert moved[0] == pytest.approx(4.0 * nx)
    assert moved[1] == pytest.approx(4.0 * ny)


def test_north_road_baseline_starts_from_the_opposite_side():
    """北側が前面道路なら、法56条1項3号は反対側の境界線から測る。

    北辺 y=20 が幅員6mの道路 → 基準線は y = 20 + 6 + 4 = 30。
    """
    specs = [{"kind": "adjacent"}, {"kind": "adjacent"},
             {"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"}]
    positions = north_positions(
        _site(zone="1low", far=0.8, height=10.0, specs=specs))
    for p in positions:
        assert p.point[1] == pytest.approx(30.0)


def test_north_position_height_applies_article_135_11_paragraph_4():
    specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
             {"kind": "adjacent", "ground_level_diff_m": 5.0}, {"kind": "adjacent"}]
    positions = north_positions(
        _site(zone="1low", far=0.8, height=10.0, specs=specs))
    north = [p for p in positions if p.edge_index == 2]
    assert north[0].z_m == pytest.approx(2.0)     # (5−1)/2


# === 間隔の上書き =====================================================

def test_user_interval_can_only_tighten():
    """条文より細かくはできるが、粗くはできない。"""
    statutory = len(road_positions(_site(road=6.0)))            # 3m間隔
    finer = len(road_positions(_site(road=6.0), max_interval_m=1.0))
    coarser = len(road_positions(_site(road=6.0), max_interval_m=10.0))
    assert finer > statutory
    assert coarser == statutory


def test_zero_or_negative_override_is_ignored():
    statutory = len(road_positions(_site(road=6.0)))
    assert len(road_positions(_site(road=6.0), max_interval_m=0.0)) == statutory
    assert len(road_positions(_site(road=6.0), max_interval_m=-1.0)) == statutory


# === まとめ ===========================================================

def test_all_positions_is_the_union():
    site = _site(zone="1mid", far=2.0)
    total = all_positions(site)
    assert len(total) == (len(road_positions(site)) + len(adjacent_positions(site))
                          + len(north_positions(site)))
    assert {p.kind for p in total} == {"road", "adjacent", "north"}


def test_a_north_facing_road_gets_both_road_and_north_positions():
    """道路高さ制限と北側高さ制限は両方かかる。重複ではありません。"""
    specs = [{"kind": "adjacent"}, {"kind": "adjacent"},
             {"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"}]
    site = _site(zone="1mid", far=2.0, specs=specs)
    kinds = {p.kind for p in all_positions(site) if p.edge_index == 2}
    assert kinds == {"road", "north"}


def test_point3_bundles_the_height():
    p = road_positions(_site())[0]
    assert p.point3 == (p.point[0], p.point[1], p.z_m)
