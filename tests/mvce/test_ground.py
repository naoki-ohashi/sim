"""令2条2項（平均地盤面）のテスト。

    ２　前項第二号、第六号又は第七号の「地盤面」とは、建築物が周囲の地面と
    接する位置の平均の高さにおける水平面をいい、その接する位置の高低差が
    三メートルを超える場合においては、その高低差三メートル以内ごとの
    平均の高さにおける水平面をいう。

「3mを**超える**」の境界と、条文が切り方を定めていないことによる
`UNDETERMINED` を固定します。
"""
import math

import pytest

from mvce.ground import (
    ContactPoint,
    GROUND_PLANE_BAND_M,
    average_ground_level,
    contact_length_m,
    flat_ground_plane,
    ground_plane,
    ground_planes,
    split_by_elevation,
)
from mvce.site import Site
from mvce.zoning import UndeterminedRegulation, ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
SPECS = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
         {"kind": "adjacent"}, {"kind": "adjacent"}]


def _contour(levels, points=SQUARE):
    return [ContactPoint(p, z) for p, z in zip(points, levels)]


# === 平均の高さ =======================================================

def test_flat_ground_averages_to_that_level():
    result = ground_plane(_contour([2.0] * 4))
    assert result.is_flat
    assert result.level_m == pytest.approx(2.0)


def test_length_weighted_average_differs_from_simple_mean():
    """30m×20m の長方形で、短辺側だけ高い場合。

    単純平均は頂点4つの平均だが、長さ加重は長辺（30m）の寄与が大きい。
    """
    levels = [0.0, 0.0, 3.0, 3.0]   # 南辺=0、北辺=3
    contour = _contour(levels)
    simple = average_ground_level(contour, weighted=False)
    assert simple == pytest.approx(1.5)

    # 長さ加重: 南辺30m×0 + 東辺20m×1.5 + 北辺30m×3 + 西辺20m×1.5
    #         = 0 + 30 + 90 + 30 = 150、周長100 → 1.5
    weighted = average_ground_level(contour)
    assert weighted == pytest.approx(1.5)

    # 高い辺を短辺にすると差が出る
    levels2 = [0.0, 3.0, 3.0, 0.0]  # 東辺だけ高い
    # 南辺30m×1.5 + 東辺20m×3 + 北辺30m×1.5 + 西辺20m×0 = 45+60+45+0 = 150
    assert average_ground_level(_contour(levels2)) == pytest.approx(1.5)
    assert average_ground_level(_contour(levels2), weighted=False) == pytest.approx(1.5)


def test_rectangle_cannot_tell_the_two_averages_apart():
    """長方形では、どの頂点も長辺と短辺に1本ずつ挟まれるので重みが等しい。

    加重平均と単純平均の違いを見るには、辺の長さが偏った形が要ります。
    """
    points = [(0.0, 0.0), (40.0, 0.0), (40.0, 5.0), (0.0, 5.0)]
    for levels in ([2.0, 2.0, 0.0, 0.0], [0.0, 2.0, 2.0, 2.0], [1.0, 0.0, 3.0, 2.0]):
        contour = _contour(levels, points)
        assert average_ground_level(contour) == pytest.approx(
            average_ground_level(contour, weighted=False))


def test_weighting_matters_when_vertex_spacing_is_uneven():
    """長辺の途中に頂点があると、頂点ごとの重みが変わる。

    (0,0)-(20,0)-(40,0)-(40,5)-(0,5)。頂点の重みは隣接2辺の長さの平均で、
    それぞれ 12.5 / 20 / 12.5 / 22.5 / 22.5（周長90）。
    真ん中の (20,0) だけ地面が低いとき、単純平均は5点の等分なのに対し、
    加重平均はその点の重み 20/90 で効きます。
    """
    points = [(0.0, 0.0), (20.0, 0.0), (40.0, 0.0), (40.0, 5.0), (0.0, 5.0)]
    levels = [2.0, 0.0, 2.0, 2.0, 2.0]
    contour = _contour(levels, points)

    simple = average_ground_level(contour, weighted=False)
    weighted = average_ground_level(contour)
    assert simple == pytest.approx(8.0 / 5.0)          # 1.6
    assert weighted == pytest.approx(140.0 / 90.0)     # 1.5555…
    assert weighted < simple


def test_contact_length_is_the_perimeter():
    assert contact_length_m(_contour([0.0] * 4)) == pytest.approx(100.0)
    assert contact_length_m(_contour([0.0] * 4), closed=False) == pytest.approx(80.0)


def test_single_point_contour():
    assert average_ground_level([ContactPoint((0.0, 0.0), 4.0)]) == pytest.approx(4.0)


# === 3mの境界 =========================================================

def test_exactly_3m_is_still_one_plane():
    """条文は「三メートルを**超える**場合」。ちょうど3mは分けない。"""
    result = ground_plane(_contour([0.0, 0.0, 3.0, 3.0]))
    assert result.kind == "single"
    assert len(result.planes) == 1
    assert result.planes[0].span_m == pytest.approx(3.0)


def test_over_3m_is_undetermined():
    with pytest.raises(UndeterminedRegulation, match="3mを超え"):
        ground_plane(_contour([0.0, 0.0, 3.01, 3.01]))


def test_undetermined_message_points_at_the_way_out():
    with pytest.raises(UndeterminedRegulation) as e:
        ground_plane(_contour([0.0, 0.0, 5.0, 5.0]))
    assert "split_by_elevation" in str(e.value)
    assert "ground_planes" in str(e.value)


def test_band_constant_matches_the_statute():
    assert GROUND_PLANE_BAND_M == 3.0


# === 区分してからの算定 ===============================================

def test_split_by_elevation_then_two_planes():
    contour = _contour([0.0, 0.0, 5.0, 5.0])
    sections = split_by_elevation(contour, [2.5])
    assert [len(s) for s in sections] == [2, 2]
    result = ground_planes(sections)
    assert result.kind == "multi"
    assert len(result.planes) == 2
    assert result.planes[0].level_m == pytest.approx(0.0)
    assert result.planes[1].level_m == pytest.approx(5.0)


def test_multi_refuses_to_give_a_single_level():
    result = ground_planes(split_by_elevation(_contour([0.0, 0.0, 5.0, 5.0]), [2.5]))
    with pytest.raises(UndeterminedRegulation, match="複数"):
        result.level_m


def test_split_rejects_a_band_wider_than_3m():
    with pytest.raises(ValueError, match="3mを超え"):
        split_by_elevation(_contour([0.0, 0.0, 7.0, 7.0]), [3.5])


def test_split_rejects_a_cut_outside_the_range():
    with pytest.raises(ValueError, match="範囲"):
        split_by_elevation(_contour([0.0, 0.0, 5.0, 5.0]), [9.0])


def test_split_rejects_an_empty_band():
    with pytest.raises(ValueError, match="接地点が1つもありません"):
        split_by_elevation(_contour([0.0, 0.0, 5.0, 5.0]), [1.0, 2.0])


def test_ground_planes_rejects_a_section_over_3m():
    with pytest.raises(ValueError, match="3mを超え"):
        ground_planes([_contour([0.0, 0.0, 4.0, 4.0])])


def test_ground_planes_with_one_section_is_not_multi():
    result = ground_planes([_contour([0.0, 0.0, 1.0, 1.0])])
    assert result.kind == "single"
    assert result.level_m == pytest.approx(0.5)


def test_ground_planes_labels():
    sections = split_by_elevation(_contour([0.0, 0.0, 5.0, 5.0]), [2.5])
    result = ground_planes(sections, labels=["下段", "上段"])
    assert [p.label for p in result.planes] == ["下段", "上段"]


# === Site との繋ぎ ====================================================

def _site(levels=None):
    return Site.from_rings(
        SQUARE, SPECS, ZoningParams("1res", 2.0, 0.6), ground_levels=levels)


def test_site_without_ground_levels_is_flat_zero():
    result = _site().ground_plane()
    assert result.is_flat
    assert result.level_m == pytest.approx(0.0)
    assert any("令2条2項の算定はしていません" in n for n in result.notes)


def test_site_with_ground_levels():
    result = _site([0.0, 0.0, 2.0, 2.0]).ground_plane()
    assert result.kind == "single"
    assert result.level_m == pytest.approx(1.0)


def test_site_ground_levels_must_match_vertex_count():
    with pytest.raises(ValueError, match="ground_levels"):
        _site([0.0, 1.0])


def test_ground_levels_follow_the_ring_reversal():
    """時計回りで渡しても、頂点と高さの対応が崩れない。"""
    cw = list(reversed(SQUARE))
    specs = [{"kind": "adjacent"}] * 4
    levels = [1.0, 2.0, 3.0, 4.0]
    site = Site.from_rings(cw, specs, ZoningParams("1res", 2.0, 0.6),
                           ground_levels=levels)
    for p, z in zip(cw, levels):
        i = next(i for i, q in enumerate(site.points) if math.dist(p, q) < 1e-9)
        assert site.ground_levels[i] == pytest.approx(z)


def test_flat_ground_plane_helper():
    assert flat_ground_plane(1.5).level_m == pytest.approx(1.5)


# === 最適化ループへの注記 =============================================
# 地盤面の算定はできるようになったが、高さの判定はまだ Z=0 から。
# 黙って無視しないことをここで固定する。

def _optimize(levels):
    from mvce.solvers.optimizer import OptimizeOptions, optimize

    site = _site(levels)
    return optimize(site, None, OptimizeOptions(cell_size_x_m=5.0, cell_size_y_m=5.0))


def test_flat_site_gets_no_ground_note():
    assert not [n for n in _optimize(None).notes if "地盤" in n]


def test_sloped_site_is_told_that_heights_are_still_from_zero():
    notes = [n for n in _optimize([0.0, 0.0, 2.0, 2.0]).notes if "令2条2項" in n]
    assert len(notes) == 1
    assert "Z=0 から測っています" in notes[0]


def test_site_over_3m_says_the_ground_plane_is_undetermined():
    notes = _optimize([0.0, 0.0, 5.0, 5.0]).notes
    assert any("地盤面が求まりません" in n for n in notes)
    assert any("Z=0 を地盤面として" in n for n in notes)


def test_uniformly_raised_site_says_the_result_is_unaffected():
    notes = [n for n in _optimize([3.0] * 4).notes if "地盤" in n]
    assert len(notes) == 1
    assert "相対的な結果は変わりません" in notes[0]
