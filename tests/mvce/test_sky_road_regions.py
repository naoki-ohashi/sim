"""前面道路が2以上ある敷地の天空率（令135条の6第3項・令135条の9第3項）.

    令135条の6第3項
    当該建築物の前面道路が二以上ある場合における第一項第一号の規定の適用に
    ついては、同号中「限る。）」とあるのは「限る。）の**第百三十二条又は
    第百三十四条第二項に規定する区域ごとの部分**」と、「という。）の」と
    あるのは「という。）の第百三十二条又は第百三十四条第二項に規定する
    区域ごとの部分の」とする。

    令135条の9第3項
    当該建築物の前面道路が二以上ある場合における第一項の規定の適用に
    ついては、同項第一号中「限る。）」とあるのは、「限る。）の第百三十二条
    又は第百三十四条第二項に規定する**区域ごと**」とする。

つまり区域ごとに、**適合建築物・算定位置・計画建築物の3つ**を切り分けて
比べます。3つのうち1つでも切り忘れると比較が成り立ちません。

固定するのはこれです。

1. 角地が `UndeterminedRegulation` で止まらず、区域ごとに比較すること
2. 区域ごとの適合建築物が、**点ごとに独立実装した令132条の道路斜線**
   （`road_slant.height_limit_at`）と一致すること
3. 算定位置がその区域の前面道路だけに、その区域が面している範囲に出ること
4. 間隔は**実幅員**の1/2（みなし幅員で割ると粗くなり危険側）
5. 令134条2項を選んだ敷地は止まること（区域を多角形で作れないため）
"""
import numpy as np
import pytest
from shapely.geometry import Point as ShPoint, Polygon

from mvce.massing import Block
from mvce.mesh import assign_height_limits, build_mesh
from mvce.index.sky_index import AZIMUTH_OFFSET_RATIO, build_sky_index
from mvce.regulations import road_slant
from mvce.regulations.sky_ratio import (
    all_ok,
    applicable_regions,
    check,
    measurement_points,
    reference_buildings,
    reference_ring_at_height,
    road_sky_regions,
)
from mvce.regulations.sky_positions import road_positions
from mvce.site import Site
from mvce.solvers.optimizer import _floors_to_blocks
from mvce.zoning import UndeterminedRegulation, ZoningParams

N_AZIMUTH = 36

#: 30m × 50m。辺0 = 南（y=0）、辺1 = 東（x=30）、辺2 = 北、辺3 = 西
DEEP = [(0.0, 0.0), (30.0, 0.0), (30.0, 50.0), (0.0, 50.0)]
#: 30m × 20m。1項の区域が敷地を覆いきる浅い角地
SHALLOW = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _corner(ring=DEEP, a=8.0, b=6.0, zone="commercial", far=6.0, **edge_kwargs):
    """辺0 に幅員 `a`、辺1 に幅員 `b` の道路がある角地。"""
    specs = [{"kind": "road", "road_width_m": a},
             {"kind": "road", "road_width_m": b},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    specs[0].update(edge_kwargs.pop("edge0", {}))
    specs[1].update(edge_kwargs.pop("edge1", {}))
    return Site.from_rings(
        ring, specs,
        ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=0.8),
        **edge_kwargs)


# === 1. 角地が止まらなくなった ========================================

def test_a_corner_site_is_no_longer_refused():
    """区域を通すまでは `UndeterminedRegulation` でした。"""
    site = _corner()
    regions = road_sky_regions(site)
    assert len(regions) >= 2
    assert {r.paragraph for r in regions} == {1, 3}
    assert all_ok(check(site, [], n_azimuth=N_AZIMUTH))


def test_the_groups_line_up_across_positions_references_and_clipping():
    """算定位置・適合建築物・適用範囲が同じキーで揃っていること。

    どれか1つでもキーがずれると、その測定点は空の適合建築物と比べられて
    **何でも通ってしまいます**。揃っていることを固定します。
    """
    site = _corner()
    regions = road_sky_regions(site)
    keys = {p.group_key for p in measurement_points(site, regions=regions)}
    assert keys <= set(reference_buildings(site, regions=regions))
    assert keys <= set(applicable_regions(site, regions))
    assert any(k.startswith("road#") for k in keys)


def test_a_shallow_corner_site_has_a_single_region():
    """1項の 2A(16m) が敷地の奥行(20m)を覆えば区域は1つ。"""
    site = _corner(ring=SHALLOW, a=12.0, b=4.0)
    regions = road_sky_regions(site)
    assert len(regions) == 1
    assert regions[0].paragraph == 1
    assert regions[0].road_indices == (0, 1)
    assert regions[0].deemed_width_m == pytest.approx(12.0)


# === 2. 適合建築物が点ごとの道路斜線と一致する ========================

def _reference_height_at(site, region, point, ceiling=80.0):
    """区域の適合建築物の、その点における高さ。範囲外なら None。"""
    sp = ShPoint(point)
    ground = reference_ring_at_height(site, 0.0, "road", region)
    if ground is None or not ground.covers(sp):
        return None
    lo, hi = 0.0, ceiling
    for _ in range(40):
        mid = (lo + hi) / 2.0
        ring = reference_ring_at_height(site, mid, "road", region)
        if ring is not None and ring.covers(sp):
            lo = mid
        else:
            hi = mid
    return lo


def test_the_region_reference_reproduces_the_pointwise_article_132_slant():
    """区域ごとの適合建築物の上面 ＝ 令132条を当てはめた道路斜線の限度。

    `road_regions.article_132_regions()`（多角形）と
    `road_regions.region_at_point()`（距離だけ）は独立の実装なので、
    これは2つの経路の突き合わせになっています。
    """
    site = _corner()
    regions = road_sky_regions(site)
    rng = np.random.default_rng(20260831)
    compared = 0
    for _ in range(60):
        point = (float(rng.uniform(0.2, 29.8)), float(rng.uniform(0.2, 49.8)))
        sp = ShPoint(point)
        region = next((r for r in regions if r.polygon.covers(sp)), None)
        if region is None:
            continue
        height = _reference_height_at(site, region, point)
        if height is None:
            continue          # 適用距離の外。道路高さ制限がかからない部分
        assert height == pytest.approx(road_slant.height_limit_at(site, point),
                                       abs=0.05)
        compared += 1
    assert compared >= 20     # 突き合わせが空振りしていないこと


def test_the_deemed_width_makes_the_narrow_road_reference_taller():
    """令132条1項の読み替えは**天空率にも効く**。

    1項の区域では狭いほうの道路も最大幅員とみなすので、その区域の適合
    建築物は実幅員で組んだ場合より高くなります。これが角地で天空率を使う
    意味そのものです。効いていなければ読み替えが天空率に届いていません。
    """
    site = _corner(ring=SHALLOW, a=12.0, b=4.0)
    region = road_sky_regions(site)[0]
    assert region.deemed_width_m == pytest.approx(12.0)
    # 狭い道路（辺1）の際、敷地の東端での適合建築物の高さ
    point = (29.5, 10.0)
    deemed = _reference_height_at(site, region, point)
    assert deemed is not None
    # 読み替えが無ければ 4m 道路の斜線で頭を押さえられていたはず
    assert deemed > road_slant_limit_without_deeming(site, 1, point) + 1.0


def road_slant_limit_without_deeming(site, edge_index, point):
    """辺 `edge_index` を実幅員のまま見たときの、その点の道路斜線の限度。"""
    from mvce.geometry import point_line_distance
    from mvce.zoning import road_slant_tier

    edge = site.edges[edge_index]
    tier = road_slant_tier(site.zoning.zone_type, site.zoning.far_ratio,
                           site.zoning.unspecified_road_slant_slope)
    total = (point_line_distance(point, edge.p1, edge.p2)
             + edge.road_width_m + edge.wall_setback_m
             + road_slant._relaxation_extra(edge))
    return tier.slope * total


# === 3・4. 算定位置 ===================================================

def test_positions_only_appear_on_the_roads_the_region_has():
    """令132条3項の区域は「その接する前面道路のみ」。"""
    site = _corner()
    regions = road_sky_regions(site)
    positions = measurement_points(site, regions=regions)
    for position in positions:
        if position.kind != "road":
            continue
        region = regions[position.region_index]
        assert position.edge_index in region.road_indices


def test_the_third_paragraph_region_only_gets_positions_over_its_frontage():
    """3項の区域は敷地の奥だけなので、位置もその範囲だけに出る。"""
    site = _corner()
    regions = road_sky_regions(site)
    third = next(k for k, r in enumerate(regions) if r.paragraph == 3)
    lo, hi = regions[third].polygon.bounds[1], regions[third].polygon.bounds[3]
    ys = [p.point[1] for p in measurement_points(site, regions=regions)
          if p.region_index == third]
    assert ys
    assert min(ys) == pytest.approx(lo, abs=1e-6)
    assert max(ys) == pytest.approx(hi, abs=1e-6)


def test_the_interval_uses_the_actual_width_not_the_deemed_width():
    """みなし幅員で割ると間隔が粗くなり、点の間をすり抜けます。

    1項の区域で幅員4mの道路が12mとみなされている敷地で、その道路の位置の
    間隔が 2m（＝4/2）であって 6m（＝12/2）でないことを固定します。
    """
    site = _corner(ring=SHALLOW, a=12.0, b=4.0)
    regions = road_sky_regions(site)
    ys = sorted(p.point[1] for p in measurement_points(site, regions=regions)
                if p.kind == "road" and p.edge_index == 1)
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert gaps
    assert max(gaps) == pytest.approx(2.0, abs=1e-6)


def test_the_user_can_only_tighten_the_interval():
    site = _corner()
    coarse = measurement_points(site)
    fine = measurement_points(site, max_interval_m=1.0)
    loose = measurement_points(site, max_interval_m=99.0)
    assert len(fine) > len(coarse)
    assert len(loose) == len(coarse)


# === 5. 令134条2項は止まる ============================================

def test_article_134_2_is_refused_for_the_sky_ratio():
    """令135条の6第3項が参照する「令134条2項に規定する区域」を作れない。

    算定位置の側からも同じところで止まること（`road_positions` を直接
    呼んでも令132条の区域で計算してしまわないこと）を固定します。
    """
    site = _corner(edge0={"relaxation": {"kind": "park", "width_m": 10.0}},
                   apply_article_134_2=True)
    with pytest.raises(UndeterminedRegulation, match="令134条2項"):
        road_sky_regions(site)
    with pytest.raises(UndeterminedRegulation, match="令134条2項"):
        road_positions(site)
    with pytest.raises(UndeterminedRegulation, match="令134条2項"):
        check(site, [], n_azimuth=N_AZIMUTH)


def test_article_134_2_without_a_park_is_fine():
    """公園等が無ければ令134条2項は発動しないので、令132条で計算できる。"""
    site = _corner(apply_article_134_2=True)
    assert len(road_sky_regions(site)) >= 2


# === インデックスとの突き合わせ ======================================

def test_the_index_is_never_more_lenient_than_the_polygon_calculation():
    """最適化に使うインデックスが、多角形の計算より甘くならないこと。

    インデックスはマスが区域に一部でもかかれば丸ごと含めるので、塞ぐ側に
    多めに見ます。差が出るのは構いませんが、**向きが逆になってはいけません**。
    """
    site = _corner()
    area = build_mesh(site, cell_size_x_m=5.0, cell_size_y_m=5.0)
    assign_height_limits(area)
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    heights = floors * site.floor_height_m
    blocks = _floors_to_blocks(area, floors, site.floor_height_m)

    index = build_sky_index(site, area, n_azimuth=N_AZIMUTH)
    polygon = check(site, blocks, n_azimuth=N_AZIMUTH,
                    azimuth_offset_ratio=AZIMUTH_OFFSET_RATIO)
    assert len(index.points) == len(polygon)
    for i, result in enumerate(polygon):
        index_margin = index.ps_at(i, heights) - index.pr[i]
        assert index_margin <= result.margin + 1e-9


# === 通しの判定 =======================================================

def test_a_low_building_passes_and_a_tall_one_does_not():
    site = _corner()
    footprint = Polygon([(2, 2), (28, 2), (28, 48), (2, 48)])
    low = [Block(footprint=footprint, z_bottom=0.0, z_top=8.0)]
    tall = [Block(footprint=footprint, z_bottom=0.0, z_top=60.0)]
    assert all_ok(check(site, low, n_azimuth=N_AZIMUTH))
    assert not all_ok(check(site, tall, n_azimuth=N_AZIMUTH))


def test_the_proposed_building_is_clipped_per_region():
    """計画建築物も区域ごとに切ること（令135条の6第3項）。

    3項の区域（敷地の奥）だけに建つ塊は、1項の区域の測定点からは**見えない**
    扱いです。切っていないと1項の Ps が下がり、判定が変わってしまいます。
    """
    site = _corner()
    regions = road_sky_regions(site)
    third = next(r for r in regions if r.paragraph == 3)
    x0, y0, x1, y1 = third.polygon.bounds
    inside_third = [Block(
        footprint=Polygon([(x0 + 0.5, y0 + 0.5), (x1 - 0.5, y0 + 0.5),
                           (x1 - 0.5, y1 - 0.5), (x0 + 0.5, y1 - 0.5)]),
        z_bottom=0.0, z_top=40.0)]
    results = check(site, inside_third, n_azimuth=N_AZIMUTH)
    first = [c for c in results if c.region_index is not None
             and regions[c.region_index].paragraph == 1]
    third_points = [c for c in results if c.region_index is not None
                    and regions[c.region_index].paragraph == 3]
    assert first and third_points
    # 1項の区域の測定点からは、3項の区域に建つ塊は見えない
    for result in first:
        assert result.ps == pytest.approx(100.0, abs=1e-9)
    # 3項の区域の測定点からは見える（＝切りすぎてもいない）
    assert min(c.ps for c in third_points) < 99.0
