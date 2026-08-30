"""令135条の12第3項第2号・第4項（日影の高低差緩和）のテスト。

    二　建築物の敷地の平均地盤面が隣地又はこれに連接する土地で日影の
    生ずるものの地盤面（略）より一メートル以上低い場合においては、その
    建築物の敷地の平均地盤面は、当該高低差から一メートルを減じたものの
    二分の一だけ高い位置にあるものとみなす。

日影規制の平均地盤面には令2条2項の「3m以内ごと」の区分が無いこと
（照合台帳の食い違い T）も、ここで固定します。
"""
import pytest

from mvce.regulations.shadow import (
    ShadowRegulationSpec,
    compute_shadow_hours,
    deemed_average_ground_level_m,
    measurement_plane_z_m,
    shadow_average_ground_level_m,
)
from mvce.massing import Block
from mvce.site import ShadowGroundRelaxation, Site
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
SPECS = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
         {"kind": "adjacent"}, {"kind": "adjacent"}]


def _site(ground_levels=None, neighbour=None, designated=None):
    relax = ShadowGroundRelaxation(neighbour_level_m=neighbour,
                                   designated_level_m=designated)
    return Site.from_rings(
        SQUARE, SPECS, ZoningParams("1res", 2.0, 0.6),
        ground_levels=ground_levels, shadow_ground=relax)


def _spec(height=4.0):
    return ShadowRegulationSpec(measurement_height_m=height,
                                line_5m_max_hours=5.0, line_10m_max_hours=3.0)


# === 日影の平均地盤面（食い違い T）====================================

def test_flat_site_average_is_zero():
    assert shadow_average_ground_level_m(_site()) == pytest.approx(0.0)


def test_average_is_length_weighted_like_ground_py():
    assert shadow_average_ground_level_m(
        _site([0.0, 0.0, 2.0, 2.0])) == pytest.approx(1.0)


def test_no_3m_split_for_shadow():
    """令2条2項なら3m超で UNDETERMINED。日影の平均地盤面は区分が無い。

    別表第四の備考は「当該建築物が周囲の地面と接する位置の平均の高さに
    おける水平面」だけで、「高低差三メートル以内ごと」がありません。
    """
    from mvce.zoning import UndeterminedRegulation

    site = _site([0.0, 0.0, 8.0, 8.0])
    with pytest.raises(UndeterminedRegulation):
        site.ground_plane()                      # 令2条2項は止まる
    assert shadow_average_ground_level_m(site) == pytest.approx(4.0)   # 日影は出る


# === 第3項第2号 =======================================================

def test_no_relaxation_without_a_neighbour_level():
    level, notes = deemed_average_ground_level_m(_site())
    assert level == pytest.approx(0.0)
    assert notes == []


def test_relaxation_needs_at_least_1m():
    level, notes = deemed_average_ground_level_m(_site(neighbour=0.99))
    assert level == pytest.approx(0.0)
    assert any("1m未満" in n for n in notes)


def test_exactly_1m_qualifies_but_adds_nothing():
    """条文は「一メートル以上低い場合」。1mちょうどは対象だが (1−1)/2 = 0。"""
    level, notes = deemed_average_ground_level_m(_site(neighbour=1.0))
    assert level == pytest.approx(0.0)
    assert not any("1m未満" in n for n in notes)


def test_relaxation_is_half_of_the_excess():
    """隣地が3m高い → (3−1)/2 = 1.0m 高い位置にあるものとみなす。"""
    level, notes = deemed_average_ground_level_m(_site(neighbour=3.0))
    assert level == pytest.approx(1.0)
    assert any("令135条の12第3項第2号" in n for n in notes)


def test_relaxation_is_measured_from_the_average_not_from_zero():
    """敷地が傾斜していれば、比較の起点は平均地盤面。"""
    site = _site([0.0, 0.0, 2.0, 2.0], neighbour=4.0)   # 平均 1.0、差 3.0
    assert deemed_average_ground_level_m(site)[0] == pytest.approx(1.0 + 1.0)


def test_a_lower_neighbour_gives_no_relaxation():
    """敷地の方が高い場合。条文は敷地が「低い」ときの緩和なので効かない。"""
    assert deemed_average_ground_level_m(_site(neighbour=-2.0))[0] == pytest.approx(0.0)


# === 第4項（特定行政庁の定め）=========================================

def test_designated_level_wins():
    level, notes = deemed_average_ground_level_m(_site(neighbour=5.0, designated=1.2))
    assert level == pytest.approx(1.2)
    assert any("令135条の12第4項" in n for n in notes)


# === 測定面のZ ========================================================

def test_measurement_plane_is_unchanged_without_relaxation():
    assert measurement_plane_z_m(_site(), _spec(4.0)) == pytest.approx(4.0)


def test_measurement_plane_rises_with_the_relaxation():
    assert measurement_plane_z_m(_site(neighbour=3.0), _spec(4.0)) == pytest.approx(5.0)


def test_measurement_plane_uses_the_chosen_height():
    assert measurement_plane_z_m(_site(neighbour=3.0), _spec(1.5)) == pytest.approx(2.5)


# === 実際に日影が短くなる =============================================

def _hours(site):
    """南側に高い塊を置いて、北側の測定点の日影時間を見る。"""
    from shapely.geometry import Polygon

    block = Block(footprint=Polygon([(5.0, 2.0), (25.0, 2.0), (25.0, 12.0), (5.0, 12.0)]),
                  z_bottom=0.0, z_top=8.0)
    lines = compute_shadow_hours(site, [block], _spec(4.0))
    return sum(h for line in lines for _p, h in line.point_hours)


def test_relaxation_shortens_the_shadow():
    plain = _hours(_site())
    relaxed = _hours(_site(neighbour=5.0))     # (5−1)/2 = 2m 測定面が上がる
    assert relaxed < plain


def test_no_relaxation_leaves_the_shadow_unchanged():
    assert _hours(_site(neighbour=0.5)) == pytest.approx(_hours(_site()))


# === 最適化ループへの注記 =============================================

def test_optimizer_reports_the_relaxation():
    from mvce.solvers.optimizer import OptimizeOptions, optimize

    result = optimize(_site(neighbour=3.0), _spec(4.0),
                      OptimizeOptions(cell_size_x_m=10.0, cell_size_y_m=10.0))
    assert any("令135条の12第3項第2号" in n for n in result.notes)


def test_optimizer_says_nothing_without_a_shadow_spec():
    from mvce.solvers.optimizer import OptimizeOptions, optimize

    result = optimize(_site(neighbour=3.0), None,
                      OptimizeOptions(cell_size_x_m=10.0, cell_size_y_m=10.0))
    assert not any("令135条の12" in n for n in result.notes)
