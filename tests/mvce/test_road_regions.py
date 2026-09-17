"""令132条の区域区分（`regulations/road_regions.py`）のテスト。

固定するのは3つです。

1. 条文どおりの区域が出ること（1項・2項・3項）
2. **狭い道路側からは 2A の区域を作らない**こと（新JCBA方式の解説が
   わざわざ強調している間違い）
3. 多角形版と点ごと版が一致すること（斜線は点ごと版を使うので、
   ずれると天空率と斜線で答えが変わる）
"""
import random

import pytest
from shapely.geometry import Point as ShPoint

from mvce.regulations.road_regions import (
    CENTERLINE_M,
    MAX_DISTANCE_M,
    WIDTH_FACTOR,
    article_132_regions,
    centerline_reach_m,
    reach_m,
    region_at_point,
)
from mvce.site import Site
from mvce.zoning import UndeterminedRegulation, ZoningParams

RECT = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]   # 1200 m2


def _site(specs, points=RECT):
    return Site.from_rings(points, specs, ZoningParams("1res", 4.0, 0.6))


# === 条文の数値 =======================================================

def test_statutory_constants():
    assert WIDTH_FACTOR == 2.0
    assert MAX_DISTANCE_M == 35.0
    assert CENTERLINE_M == 10.0


@pytest.mark.parametrize("width,expected", [
    (8.0, 16.0),      # 2W
    (6.0, 12.0),
    (4.0, 8.0),       # ちょうど4mは 2W
    (3.0, 8.5),       # 4m未満は 10 − W/2（2W=6 より大きい）
    (2.0, 9.0),
    (20.0, 35.0),     # 2W=40 だが35mで頭打ち
])
def test_reach(width, expected):
    """令132条2項の到達範囲。4m未満は 10 − W/2、かつ35m以内。"""
    assert reach_m(width) == pytest.approx(expected)


@pytest.mark.parametrize("width,expected", [
    (8.0, 6.0), (6.0, 7.0), (4.0, 8.0), (3.0, 8.5), (24.0, 0.0),
])
def test_centerline_reach(width, expected):
    """「中心線から10m」を境界線からの距離に直すと 10 − W/2。"""
    assert centerline_reach_m(width) == pytest.approx(expected)


# === 区域が出ない場合 =================================================

def test_no_regions_with_one_road():
    specs = [{"kind": "road", "road_width_m": 6.0}] + [{"kind": "adjacent"}] * 3
    assert article_132_regions(_site(specs)) == []
    assert region_at_point(_site(specs), (20.0, 15.0)) is None


def test_no_regions_without_roads():
    assert article_132_regions(_site([{"kind": "adjacent"}] * 4)) == []


def test_too_many_roads_is_refused():
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0),
              (30.0, 20.0), (20.0, 20.0), (10.0, 20.0), (0.0, 20.0)]
    specs = [{"kind": "road", "road_width_m": 4.0 + i} for i in range(7)]
    specs.append({"kind": "adjacent"})
    with pytest.raises(UndeterminedRegulation, match="6本まで"):
        article_132_regions(_site(specs, points))


# === 2本の前面道路 ====================================================

def _two_road_site():
    """南=6m、東=10m（最大）。"""
    return _site([{"kind": "road", "road_width_m": 6.0},
                  {"kind": "road", "road_width_m": 10.0},
                  {"kind": "adjacent"}, {"kind": "adjacent"}])


def test_two_roads_have_no_paragraph_2_region():
    """2本のとき令132条2項の区域は空。

    1項の外に出るには「最大幅員から 2A 超」でなければならず、そのとき
    最大幅員の道路は到達範囲の外なので、2以上の道路が届くことはありません。
    """
    regions = article_132_regions(_two_road_site())
    assert regions
    assert not [r for r in regions if r.paragraph == 2]


def test_two_roads_paragraph_1_deems_the_max_width():
    regions = article_132_regions(_two_road_site())
    first = [r for r in regions if r.paragraph == 1]
    assert first
    for r in first:
        assert r.deemed_width_m == pytest.approx(10.0)
        assert set(r.road_indices) == {0, 1}


# === 3本の前面道路（解説の図と同じ構成）===============================

def _three_road_site():
    """南=C 4.5m、東=B 6m、北=A 8m（最大）。解説 PDF p.30〜32 の例。"""
    return _site([{"kind": "road", "road_width_m": 4.5},
                  {"kind": "road", "road_width_m": 6.0},
                  {"kind": "road", "road_width_m": 8.0},
                  {"kind": "adjacent"}])


def test_three_roads_produce_all_three_paragraphs():
    regions = article_132_regions(_three_road_site())
    assert {r.paragraph for r in regions} == {1, 2, 3}


def test_paragraph_1_deems_the_widest_width():
    regions = [r for r in article_132_regions(_three_road_site()) if r.paragraph == 1]
    assert regions
    for r in regions:
        assert r.deemed_width_m == pytest.approx(8.0)


def test_paragraph_2_deems_the_wider_of_the_reaching_roads():
    """令132条2項「幅員の小さい前面道路は、幅員の大きい前面道路と同じ幅員」。

    C(4.5m) と B(6m) が届く区域では、みなし幅員は 6m です。
    **4.5m にはなりません。**
    """
    regions = [r for r in article_132_regions(_three_road_site()) if r.paragraph == 2]
    assert regions
    for r in regions:
        assert len(r.road_indices) >= 2
        assert r.deemed_width_m == pytest.approx(
            max(_three_road_site().edges[i].road_width_m for i in r.road_indices))


def test_paragraph_3_uses_only_its_own_road():
    site = _three_road_site()
    regions = [r for r in article_132_regions(site) if r.paragraph == 3]
    assert regions
    for r in regions:
        assert len(r.road_indices) == 1
        i = r.road_indices[0]
        assert r.deemed_width_m == pytest.approx(site.edges[i].road_width_m)


def test_the_regions_tile_the_site_without_overlapping():
    site = _three_road_site()
    regions = article_132_regions(site)
    total = sum(r.polygon.area for r in regions)
    assert total == pytest.approx(40.0 * 30.0, rel=1e-6)
    for a, b in ((x, y) for i, x in enumerate(regions) for y in regions[i + 1:]):
        assert a.polygon.intersection(b.polygon).area == pytest.approx(0.0, abs=1e-9)


# === 狭い道路側からは区分しない =======================================

def _wide_and_narrow_site():
    """南=A 20m（最大）、東=C 4m。敷地は 40m×30m。

    A の 2A は 40m だが 35m で頭打ち。敷地の奥行は 30m なので、
    **敷地全体が A の 2A かつ 35m の区域に入ります**。
    """
    return _site([{"kind": "road", "road_width_m": 20.0},
                  {"kind": "road", "road_width_m": 4.0},
                  {"kind": "adjacent"}, {"kind": "adjacent"}])


def test_the_narrow_road_never_creates_a_2a_region():
    """新JCBA方式の解説の「狭い道路側からの２Ａ処理は、行わない」。

    2A かつ 35m の区域を生むのは**最大幅員の道路だけ**です。狭い道路 C の
    2C（= 8m）の線で 1項の区域が切られることはありません。切られていたら、
    敷地の東端 8m の帯が 1項でない区域になってしまいます。
    """
    regions = article_132_regions(_wide_and_narrow_site())
    assert [r.paragraph for r in regions] == [1]
    assert regions[0].deemed_width_m == pytest.approx(20.0)
    assert regions[0].polygon.area == pytest.approx(40.0 * 30.0, rel=1e-9)


def test_a_point_next_to_the_narrow_road_still_gets_the_max_width():
    """狭い道路のすぐ内側でも、1項の区域なら最大幅員でみなす。"""
    at = region_at_point(_wide_and_narrow_site(), (39.5, 15.0))
    assert at.paragraph == 1
    assert at.deemed_width_m == pytest.approx(20.0)


def test_paragraph_1_is_the_union_not_the_intersection():
    """1項は「2A かつ 35m の区域**及び**中心線10m超の区域」。和集合です。

    交わりだと解釈すると、最大幅員の 2A を越えた奥が 1項から落ちます。
    南=A 8m（2A=16m）、東=C 6m の敷地で、奥行 30m のうち y>16 の帯は
    2A の外ですが、C の中心線10m（境界線から7m）を越えていれば 1項です。
    """
    site = _site([{"kind": "road", "road_width_m": 8.0},
                  {"kind": "road", "road_width_m": 6.0},
                  {"kind": "adjacent"}, {"kind": "adjacent"}])
    deep = region_at_point(site, (20.0, 25.0))     # 2Aの外、Cの中心線10m超
    assert deep.paragraph == 1
    assert deep.deemed_width_m == pytest.approx(8.0)


# === 多角形版と点ごと版の一致 =========================================

@pytest.mark.parametrize("specs", [
    [{"kind": "road", "road_width_m": 4.5}, {"kind": "road", "road_width_m": 6.0},
     {"kind": "road", "road_width_m": 8.0}, {"kind": "adjacent"}],
    [{"kind": "road", "road_width_m": 6.0}, {"kind": "road", "road_width_m": 10.0},
     {"kind": "adjacent"}, {"kind": "adjacent"}],
    [{"kind": "road", "road_width_m": 3.0}, {"kind": "road", "road_width_m": 4.0},
     {"kind": "road", "road_width_m": 5.0}, {"kind": "road", "road_width_m": 12.0}],
])
def test_polygon_and_pointwise_agree(specs):
    """斜線は点ごと版、天空率は多角形版を使うので、ずれると答えが食い違う。"""
    site = _site(specs)
    regions = article_132_regions(site)
    random.seed(20260830)
    checked = 0
    for _ in range(600):
        p = (random.uniform(0.3, 39.7), random.uniform(0.3, 29.7))
        hit = [r for r in regions if r.polygon.covers(ShPoint(p))]
        if not hit:
            continue
        at = region_at_point(site, p)
        assert at is not None, p
        assert at.paragraph == hit[0].paragraph, p
        assert at.deemed_width_m == pytest.approx(hit[0].deemed_width_m), p
        assert set(at.road_indices) == set(hit[0].road_indices), p
        checked += 1
    assert checked > 400, f"検証できた点が少なすぎます: {checked}"


# === 斜線との繋ぎ =====================================================

def test_three_roads_no_longer_refuse():
    """食い違い W の解消。以前は UndeterminedRegulation で止めていた。"""
    from mvce.regulations import road_slant

    assert road_slant.height_limit_at(_three_road_site(), (20.0, 15.0)) < float("inf")


def test_the_deemed_width_reaches_the_slant():
    """狭い道路のすぐ内側でも、1項の区域なら最大幅員で斜線が緩む。"""
    from mvce.regulations import road_slant

    narrow_only = _site([{"kind": "road", "road_width_m": 4.0}] + [{"kind": "adjacent"}] * 3)
    with_wide = _site([{"kind": "road", "road_width_m": 4.0},
                       {"kind": "road", "road_width_m": 20.0},
                       {"kind": "adjacent"}, {"kind": "adjacent"}])
    point = (20.0, 3.0)
    assert (road_slant.height_limit_at(with_wide, point)
            > road_slant.height_limit_at(narrow_only, point))
