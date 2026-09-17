"""法52条9項（特定道路による容積率緩和）と令135条の18 のテスト。

    法52条9項
    ９　建築物の敷地が、幅員十五メートル以上の道路（以下この項において
    「特定道路」という。）に接続する幅員六メートル以上十二メートル未満の
    前面道路のうち当該特定道路からの延長が七十メートル以内の部分において
    接する場合における当該建築物に対する第二項から第七項までの規定の
    適用については、第二項中「幅員」とあるのは、「幅員（…その幅員に、…
    延長に応じて政令で定める数値を加えたもの）」とする。

    令135条の18
    Ｗａ＝（１２－Ｗｒ）（７０－Ｌ）／７０

条文の3条件と読み替えの**範囲**（2項〜7項に限る）を固定します。
"""
import pytest

from mvce.far import (
    article_135_18_addition,
    compute_far,
    far_road_width_m,
    road_far_width,
)
from mvce.regulations.road_slant import detail_at
from mvce.site import Site, SpecifiedRoad
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(road_width=6.0, spec=None, zone="1res", far=4.0, extra_roads=()):
    """南辺だけ道路。`spec` は {"width_m":…, "distance_m":…}。"""
    specs = [{"kind": "road", "road_width_m": road_width}]
    if spec is not None:
        specs[0]["specified_road"] = spec
    for i in range(3):
        if i < len(extra_roads) and extra_roads[i] is not None:
            specs.append({"kind": "road", "road_width_m": extra_roads[i]})
        else:
            specs.append({"kind": "adjacent"})
    return Site.from_rings(
        SQUARE, specs, ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=0.6))


# === 令135条の18 の式 =================================================

@pytest.mark.parametrize("wr,l,expected", [
    (6.0, 0.0, 6.0),        # L=0 → 12−Wr
    (6.0, 35.0, 3.0),       # ちょうど半分
    (6.0, 70.0, 0.0),       # 上限で0（不連続にならない）
    (8.0, 20.0, 4.0 * 50.0 / 70.0),
    (11.0, 10.0, 1.0 * 60.0 / 70.0),
])
def test_article_135_18_formula(wr, l, expected):
    assert article_135_18_addition(wr, l) == pytest.approx(expected)


def test_addition_at_zero_distance_reaches_exactly_12m():
    """L=0 で加算後ちょうど12m。法52条2項の「12m未満」がここで外れる。"""
    for wr in (6.0, 8.0, 10.0, 11.9):
        assert wr + article_135_18_addition(wr, 0.0) == pytest.approx(12.0)


# === 適用条件 =========================================================

def test_applies_when_all_three_conditions_met():
    site = _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 35.0})
    w = road_far_width(site.edges[0])
    assert w.addition_m == pytest.approx(3.0)
    assert w.width_m == pytest.approx(9.0)
    assert w.relaxed
    assert w.reason == ""


def test_no_specified_road_means_no_addition():
    w = road_far_width(_site(road_width=6.0).edges[0])
    assert w.addition_m == 0.0
    assert w.width_m == pytest.approx(6.0)
    assert w.reason == ""


def test_specified_road_narrower_than_15m_is_not_a_specified_road():
    site = _site(road_width=6.0, spec={"width_m": 14.9, "distance_m": 10.0})
    w = road_far_width(site.edges[0])
    assert w.addition_m == 0.0
    assert "15m未満" in w.reason


def test_specified_road_exactly_15m_qualifies():
    """条文は「十五メートル以上」。境界値は含む。"""
    site = _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 35.0})
    assert road_far_width(site.edges[0]).relaxed


def test_front_road_under_6m_is_out_of_scope():
    site = _site(road_width=4.0, spec={"width_m": 15.0, "distance_m": 10.0})
    w = road_far_width(site.edges[0])
    assert w.addition_m == 0.0
    assert "6m未満" in w.reason


def test_front_road_exactly_6m_qualifies():
    """条文は「六メートル以上十二メートル未満」。下限は含む。"""
    site = _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 10.0})
    assert road_far_width(site.edges[0]).relaxed


def test_front_road_12m_is_out_of_scope():
    """上限は含まない。そもそも12m以上なら法52条2項の低減を受けない。"""
    site = _site(road_width=12.0, spec={"width_m": 15.0, "distance_m": 10.0})
    w = road_far_width(site.edges[0])
    assert w.addition_m == 0.0
    assert "12m以上" in w.reason


def test_distance_over_70m_is_out_of_scope():
    site = _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 70.1})
    w = road_far_width(site.edges[0])
    assert w.addition_m == 0.0
    assert "70mを超える" in w.reason


def test_distance_exactly_70m_qualifies_but_adds_nothing():
    """条文は「七十メートル以内」。境界は対象だが Wa=0 なので効果はゼロ。"""
    site = _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 70.0})
    w = road_far_width(site.edges[0])
    assert w.reason == ""
    assert w.addition_m == pytest.approx(0.0)


# === 容積率への反映 ===================================================

def test_far_increases_with_specified_road():
    """住居系6m道路: 240% → 加算3mで360%。"""
    plain = compute_far(_site(road_width=6.0, far=4.0))
    relaxed = compute_far(_site(road_width=6.0, far=4.0,
                                spec={"width_m": 15.0, "distance_m": 35.0}))
    assert plain.effective_far == pytest.approx(2.4)
    assert relaxed.effective_far == pytest.approx(3.6)
    assert relaxed.max_road_width_m == pytest.approx(9.0)
    assert 0 in relaxed.specified_road_additions


def test_designated_far_still_caps():
    """加算しても指定容積率は超えない（法52条2項は上限の1つにすぎない）。"""
    result = compute_far(_site(road_width=6.0, far=2.0,
                               spec={"width_m": 15.0, "distance_m": 0.0}))
    assert result.max_road_width_m == pytest.approx(12.0)
    assert result.effective_far == pytest.approx(2.0)


def test_addition_can_lift_out_of_article_52_2():
    """L=0 で加算後12m。「12m未満」に当たらなくなり2項の低減が外れる。"""
    result = compute_far(_site(road_width=6.0, far=4.0,
                               spec={"width_m": 15.0, "distance_m": 0.0}))
    assert result.road_far is None
    assert result.effective_far == pytest.approx(4.0)


def test_max_is_taken_after_the_addition():
    """2項の「幅員の最大のもの」も読み替え後の値で比べる。

    実幅員は 東8m > 南6m だが、南に特定道路の加算3mが付くと 9m > 8m。
    """
    site = _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 35.0},
                 extra_roads=(8.0,))
    assert site.max_road_width_m == pytest.approx(8.0)     # 実幅員
    assert far_road_width_m(site) == pytest.approx(9.0)    # 読み替え後
    assert compute_far(site).max_road_width_m == pytest.approx(9.0)


# === 読み替えの範囲（2項〜7項に限る）==================================

def test_addition_does_not_reach_the_road_slant():
    """法52条9項は「第二項から第七項までの規定の適用については」。

    道路斜線（法56条1項1号・令132条）の幅員は実幅員のまま。ここが混ざると
    存在しない高さが出るので固定しておく。
    """
    point = (15.0, 5.0)
    plain = detail_at(_site(road_width=6.0), point, 0)
    relaxed = detail_at(
        _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 35.0}), point, 0)
    assert relaxed.applied_width_m == pytest.approx(plain.applied_width_m)
    assert relaxed.height_limit_m == pytest.approx(plain.height_limit_m)


def test_site_max_road_width_is_unchanged():
    site = _site(road_width=6.0, spec={"width_m": 15.0, "distance_m": 35.0})
    assert site.max_road_width_m == pytest.approx(6.0)


# === 入力の検証 =======================================================

def test_distance_without_width_is_rejected():
    """「特定道路がある」の申告だけでは足りない。15m以上かを確かめられない。"""
    with pytest.raises(ValueError, match="width_m"):
        SpecifiedRoad(distance_m=30.0)


def test_negative_values_are_rejected():
    with pytest.raises(ValueError):
        SpecifiedRoad(width_m=-1.0)
    with pytest.raises(ValueError):
        SpecifiedRoad(width_m=15.0, distance_m=-1.0)


def test_specified_road_on_a_non_road_edge_is_rejected():
    with pytest.raises(ValueError, match="道路境界線"):
        Site.from_rings(
            SQUARE,
            [{"kind": "road", "road_width_m": 6.0},
             {"kind": "adjacent", "specified_road": {"width_m": 15.0, "distance_m": 10.0}},
             {"kind": "adjacent"}, {"kind": "adjacent"}],
            ZoningParams(zone_type="1res", far_ratio=4.0, coverage_ratio=0.6))


def test_note_explains_why_a_declared_specified_road_did_not_apply():
    result = compute_far(_site(road_width=6.0, spec={"width_m": 10.0, "distance_m": 10.0}))
    assert any("加算しません" in n for n in result.notes)
