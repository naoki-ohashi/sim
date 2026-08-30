"""適合建築物（令135条の6・7・8）のテスト。

    令135条の6第1項1号（道路）
    当該建築物（道路高さ制限が適用される**範囲内の部分に限り**）（略）の
    天空率が、（略）**道路高さ制限に適合するものとして想定する建築物**
    （道路高さ制限が適用される範囲内の部分に限り、階段室等及び棟飾等を
    除く。）の（略）天空率以上であること。

固定するのは3つです。

1. **規制ごとに別の適合建築物**であること（合成した1つではない）
2. 道路は**適用距離までの帯**に限られること（切らないと Pr が極端に
   小さくなり何でも通る）
3. 階段状の近似が真の包絡形に**含まれる**こと（はみ出すと Pr が小さく
   出て、本来通らない計画が通る）
"""
import math

import pytest
from shapely.geometry import Polygon

from mvce.massing import Block
from mvce.regulations import adjacent_slant, north_slant, road_slant
from mvce.regulations.sky_ratio import (
    REFERENCE_KINDS,
    _reference_top_m,
    applicable_region,
    check,
    clip_blocks,
    reference_building,
    reference_buildings,
)
from mvce.site import Site
from mvce.zoning import UndeterminedRegulation, ZoningParams, road_slant_tier

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(zone="1mid", far=2.0, road=6.0, setback=0.0, specs=None, coverage=0.6):
    if specs is None:
        specs = [{"kind": "road", "road_width_m": road, "wall_setback_m": setback},
                 {"kind": "adjacent", "wall_setback_m": setback},
                 {"kind": "adjacent", "wall_setback_m": setback},
                 {"kind": "adjacent", "wall_setback_m": setback}]
    return Site.from_rings(SQUARE, specs,
                           ZoningParams(zone_type=zone, far_ratio=far,
                                        coverage_ratio=coverage))


def _limit_at(site, point, kind):
    if kind == "road":
        return road_slant.height_limit_at(site, point)
    if kind == "adjacent":
        return adjacent_slant.height_limit_at(site, point)
    return north_slant.height_limit_at(site, point)


# === 規制ごとに別の形 =================================================

def test_the_three_references_are_different():
    site = _site(zone="1mid", far=2.0)
    refs = reference_buildings(site)
    tops = {k: max((b.z_top for b in refs[k]), default=0.0) for k in REFERENCE_KINDS}
    assert len(set(round(v, 6) for v in tops.values())) == 3, tops


def test_each_reference_only_obeys_its_own_regulation():
    """隣地の適合建築物は道路斜線を超えてよい（道路の制限は見ない）。"""
    site = _site(zone="1mid", far=2.0, road=6.0)
    adjacent = reference_building(site, "adjacent")
    assert adjacent
    top = max(b.z_top for b in adjacent)
    # 隣地の頂部は 10 + 1.25×15 = 28.75 より高い（道路斜線の 25m を超える）
    assert top > 25.0


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="kind"):
        reference_building(_site(), "absolute")


# === 道路は適用距離の帯に限られる =====================================

def test_road_reference_stays_inside_the_applicable_distance():
    """令135条の6第1項1号「道路高さ制限が適用される範囲内の部分に限る」。"""
    site = _site(zone="1res", far=2.0, road=6.0)
    tier = road_slant_tier("1res", 2.0)
    depth = tier.applicable_distance_m - 6.0        # 20 − 6 = 14m
    for block in reference_building(site, "road"):
        ys = [y for _x, y in block.footprint.exterior.coords]
        assert max(ys) <= depth + 1e-6, f"帯（y≦{depth}）をはみ出しています"


def test_road_reference_top_is_the_slant_at_the_applicable_distance():
    """帯の一番奥での斜線の高さが頂部。1res・6m道路なら 1.25 × 20 = 25m。"""
    assert _reference_top_m(_site(zone="1res", far=2.0, road=6.0),
                            "road") == pytest.approx(25.0, abs=1e-3)


def test_road_reference_is_empty_when_the_applicable_distance_does_not_reach():
    """適用距離を道路幅員と後退距離で使い切ると、範囲が敷地に届かない。

    このとき道路高さ制限はどこにもかからないので、適合建築物も計画建築物も
    その規制については空。天空率は 100% 対 100% で自動的に適合します。
    """
    site = _site(zone="commercial", far=6.0, road=20.0, setback=5.0)
    assert applicable_region(site, "road") is None
    assert reference_building(site, "road") == []


def test_two_roads_are_refused():
    """令135条の6第3項・令135条の9第3項は区域ごとの比較を求めている。"""
    specs = [{"kind": "road", "road_width_m": 6.0},
             {"kind": "road", "road_width_m": 8.0},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    site = _site(specs=specs, far=4.0)
    with pytest.raises(UndeterminedRegulation, match="令135条の6第3項"):
        reference_building(site, "road")


def test_no_road_means_no_road_reference():
    specs = [{"kind": "adjacent"}] * 4
    assert reference_building(_site(specs=specs), "road") == []


# === 適用のない規制 ===================================================

def test_no_adjacent_reference_in_a_low_rise_zone():
    """低層住専は隣地斜線が無い（法55条の絶対高さで代わる）。"""
    site = Site.from_rings(
        SQUARE, [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
                 {"kind": "adjacent"}, {"kind": "adjacent"}],
        ZoningParams("1low", 0.8, 0.5, absolute_height_limit_m=10.0))
    assert applicable_region(site, "adjacent") is None
    assert reference_building(site, "adjacent") == []


def test_no_north_reference_in_a_commercial_zone():
    site = _site(zone="commercial", far=6.0)
    assert applicable_region(site, "north") is None
    assert reference_building(site, "north") == []


# === 階段状の近似の向き（危険側だった） ================================

@pytest.mark.parametrize("kind", ["road", "adjacent", "north"])
def test_the_stepped_reference_stays_inside_the_true_envelope(kind):
    """各ブロックの頂部が、その平面のどこでも真の制限を超えないこと。

    **これが逆になっていると危険側です。** 適合建築物が真の形より大きいと
    空を余計に塞ぎ、Pr が小さく出て `Ps ≧ Pr` の基準が下がります。
    2026-08-30 以前は層の**下端**の断面で作っていたので、この向きが
    逆でした。
    """
    site = _site(zone="1mid", far=2.0)
    blocks = reference_building(site, kind, n_layers=12)
    assert blocks, kind
    for block in blocks:
        probes = list(block.footprint.exterior.coords)
        probes.append(block.footprint.representative_point().coords[0])
        for point in probes:
            limit = _limit_at(site, (point[0], point[1]), kind)
            assert block.z_top <= limit + 1e-6, (
                f"{kind}: 高さ{block.z_top:.3f}m が {point} の制限 {limit:.3f}m を"
                "超えています（適合建築物が真の包絡形からはみ出している）"
            )


def test_more_layers_get_closer_to_the_envelope():
    """層を増やすほど体積が増える（下から真の形に近づく）。"""
    site = _site(zone="1mid", far=2.0)
    volumes = [
        sum(b.footprint.area * (b.z_top - b.z_bottom)
            for b in reference_building(site, "adjacent", n_layers=n))
        for n in (5, 10, 40)
    ]
    assert volumes[0] < volumes[1] < volumes[2]


def test_zero_layers_gives_nothing():
    assert reference_building(_site(), "adjacent", n_layers=0) == []


# === 計画建築物も範囲で切る ===========================================

def test_clip_blocks_cuts_to_the_region():
    block = Block(footprint=Polygon([(0, 0), (30, 0), (30, 20), (0, 20)]),
                  z_bottom=0.0, z_top=10.0)
    region = Polygon([(0, 0), (30, 0), (30, 5), (0, 5)])
    clipped = clip_blocks([block], region)
    assert len(clipped) == 1
    assert clipped[0].footprint.area == pytest.approx(150.0)
    assert clipped[0].z_top == pytest.approx(10.0)


def test_clip_blocks_with_no_region_gives_nothing():
    block = Block(footprint=Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                  z_bottom=0.0, z_top=1.0)
    assert clip_blocks([block], None) == []


def test_check_passes_vacuously_when_the_road_range_is_empty():
    """範囲が空なら計画建築物も切り落とされ、100% 対 100% で適合。

    切るのを計画建築物だけ忘れると、Ps < Pr = 100% で必ず落ちます。
    """
    site = _site(zone="commercial", far=6.0, road=20.0, setback=5.0)
    tall = [Block(footprint=Polygon([(5, 5), (25, 5), (25, 15), (5, 15)]),
                  z_bottom=0.0, z_top=60.0)]
    road_checks = [c for c in check(site, tall, n_azimuth=36) if c.kind == "road"]
    assert road_checks, "道路の算定位置は残る（範囲が空でも位置は境界線上にある）"
    for c in road_checks:
        assert c.ps == pytest.approx(100.0)
        assert c.pr == pytest.approx(100.0)
        assert c.ok


def test_check_uses_the_matching_reference_per_kind():
    site = _site(zone="1mid", far=2.0)
    tall = [Block(footprint=Polygon([(5, 5), (25, 5), (25, 15), (5, 15)]),
                  z_bottom=0.0, z_top=40.0)]
    checks = check(site, tall, n_azimuth=36)
    by_kind = {}
    for c in checks:
        by_kind.setdefault(c.kind, []).append(c.pr)
    assert set(by_kind) == {"road", "adjacent", "north"}
    # 種別ごとに違う適合建築物なので、Pr の水準も種別で違う
    means = {k: sum(v) / len(v) for k, v in by_kind.items()}
    assert len(set(round(v, 6) for v in means.values())) == 3, means


def test_a_building_inside_every_envelope_passes():
    """どの斜線も満たす低い建物は、すべての測定点で適合する。"""
    site = _site(zone="1mid", far=2.0)
    low = [Block(footprint=Polygon([(10, 8), (20, 8), (20, 12), (10, 12)]),
                 z_bottom=0.0, z_top=8.0)]
    assert all(c.ok for c in check(site, low, n_azimuth=36))
