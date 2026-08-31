"""別表第三・別表第四の条文値を直接検証する（第10.1節「条文基準値テスト」）。

期待値は `docs/mvce/statutes/建築基準法.md` に収録した原文から取っています。
基本設計書の表からではありません（第0章の指示）。
"""
import pytest

from mvce.regulations.shadow import DEEMED_BOUNDARY_KINDS, ShadowRegulationSpec, deemed_boundary_offsets
from mvce.site import Boundary, BoundaryKind, RelaxationKind, Site
from mvce.zoning import (
    EAVES_OR_STOREYS,
    SHADOW_EXEMPT_ZONES,
    TOTAL_HEIGHT,
    UndeterminedRegulation,
    ZoningParams,
    allowed_measurement_heights_m,
    is_shadow_target,
    road_slant_row,
    road_slant_tier,
    shadow_table_row,
)

# --- 別表第三 -------------------------------------------------------------

#: (用途地域, 容積率, 適用距離, 勾配)。原文の全段を並べる。
TABLE3_ROW1 = [(2.0, 20.0), (3.0, 25.0), (4.0, 30.0), (5.0, 35.0), (13.0, 35.0)]
TABLE3_ROW2 = [(4.0, 20.0), (6.0, 25.0), (8.0, 30.0), (10.0, 35.0),
               (11.0, 40.0), (12.0, 45.0), (13.0, 50.0)]
TABLE3_ROW3 = [(2.0, 20.0), (3.0, 25.0), (4.0, 30.0), (5.0, 35.0), (13.0, 35.0)]
TABLE3_ROW5 = [(2.0, 20.0), (3.0, 25.0), (4.0, 30.0), (13.0, 30.0)]


@pytest.mark.parametrize("zone", ["1low", "2low", "denen", "1mid", "2mid",
                                  "1res", "2res", "quasi_res"])
def test_row1_zones(zone):
    """一の項: 低層住専・中高層住専・田園住居・住居系。勾配 1.25、上限 35m。"""
    assert road_slant_row(zone) == 1
    for far, distance in TABLE3_ROW1:
        tier = road_slant_tier(zone, far)
        assert (tier.applicable_distance_m, tier.slope) == (distance, 1.25)


@pytest.mark.parametrize("zone", ["neighbor_commercial", "commercial"])
def test_row2_zones(zone):
    """二の項: 近隣商業・商業。勾配 1.5、7段で上限 50m。"""
    assert road_slant_row(zone) == 2
    for far, distance in TABLE3_ROW2:
        tier = road_slant_tier(zone, far)
        assert (tier.applicable_distance_m, tier.slope) == (distance, 1.5)


@pytest.mark.parametrize("zone", ["quasi_industrial", "industrial", "industrial_exclusive"])
def test_row3_zones(zone):
    """三の項: 準工業・工業・工業専用。勾配は 1.5 だが距離は一の項と同じ刻み。

    ここが二の項と取り違えられていた箇所（食い違い Q）。二の項なら
    400% で 20m だが、三の項では 30m。
    """
    assert road_slant_row(zone) == 3
    for far, distance in TABLE3_ROW3:
        tier = road_slant_tier(zone, far)
        assert (tier.applicable_distance_m, tier.slope) == (distance, 1.5)


def test_row3_is_not_row2():
    """三の項に二の項の表を当てていないことを、差が出る点で固定する。"""
    for far, expected in [(3.0, 25.0), (4.0, 30.0), (5.0, 35.0)]:
        assert road_slant_tier("quasi_industrial", far).applicable_distance_m == expected
        # 二の項ならこうなってしまう
        assert road_slant_tier("commercial", far).applicable_distance_m != expected


def test_row5_distances():
    """五の項: 無指定。3段で上限 30m。"""
    assert road_slant_row("unspecified") == 5
    for far, distance in TABLE3_ROW5:
        tier = road_slant_tier("unspecified", far, 1.5)
        assert tier.applicable_distance_m == distance


def test_row5_slope_is_undetermined_without_a_designation():
    """五の項の勾配は特定行政庁が定める。既定値で埋めない（原則H）。"""
    with pytest.raises(UndeterminedRegulation):
        road_slant_tier("unspecified", 3.0)


@pytest.mark.parametrize("slope", [1.25, 1.5])
def test_row5_accepts_either_designated_slope(slope):
    assert road_slant_tier("unspecified", 3.0, slope).slope == slope


def test_row5_rejects_other_slopes():
    with pytest.raises(ValueError):
        road_slant_tier("unspecified", 3.0, 2.5)


def test_unknown_zone_is_rejected():
    with pytest.raises(ValueError):
        road_slant_row("nonesuch")


def test_zoning_params_validates_the_unspecified_slope():
    with pytest.raises(ValueError):
        ZoningParams(zone_type="unspecified", far_ratio=2.0, coverage_ratio=0.6,
                     unspecified_road_slant_slope=2.5)
    ok = ZoningParams(zone_type="unspecified", far_ratio=2.0, coverage_ratio=0.6,
                      unspecified_road_slant_slope=1.25)
    assert ok.unspecified_road_slant_slope == 1.25


# --- 別表第四 -------------------------------------------------------------

def test_row1_measurement_plane_is_1_5m():
    """一の項: 低層住専・田園住居 → 1.5m のみ。"""
    for zone in ("1low", "2low", "denen"):
        assert allowed_measurement_heights_m(zone) == (1.5,)
        assert shadow_table_row(zone).criterion == EAVES_OR_STOREYS


def test_row2_and_row3_measurement_planes():
    """二の項・三の項 → 4m または 6.5m。"""
    for zone in ("1mid", "2mid", "1res", "2res", "quasi_res",
                 "neighbor_commercial", "quasi_industrial"):
        assert allowed_measurement_heights_m(zone) == (4.0, 6.5)
        assert shadow_table_row(zone).criterion == TOTAL_HEIGHT


def test_row3_has_only_two_time_options():
    """三の項には（三）が無い（法56条の2第1項の括弧書きと整合）。"""
    for zone in ("1res", "2res", "quasi_res", "neighbor_commercial", "quasi_industrial"):
        assert shadow_table_row(zone).time_options == ("一", "二")
    for zone in ("1low", "1mid"):
        assert shadow_table_row(zone).time_options == ("一", "二", "三")


def test_row4_ro_has_no_6_5m():
    """四の項ロの測定面は 4m のみ。6.5m は無い（食い違い R）。"""
    assert allowed_measurement_heights_m("unspecified", "ro") == (4.0,)
    assert 6.5 not in allowed_measurement_heights_m("unspecified", "ro")


def test_row4_i_is_1_5m_and_eaves_based():
    assert allowed_measurement_heights_m("unspecified", "i") == (1.5,)
    assert shadow_table_row("unspecified", "i").criterion == EAVES_OR_STOREYS


def test_unspecified_needs_the_ordinance_choice():
    """イかロかが分からなければ判定しない（原則H）。"""
    with pytest.raises(UndeterminedRegulation):
        allowed_measurement_heights_m("unspecified")
    with pytest.raises(UndeterminedRegulation):
        is_shadow_target("unspecified", max_height_m=12.0)


def test_zones_that_cannot_be_designated():
    """商業・工業・工業専用は別表第四（い）欄に無い。"""
    for zone in SHADOW_EXEMPT_ZONES:
        assert shadow_table_row(zone) is None
        assert allowed_measurement_heights_m(zone) == ()
        assert not is_shadow_target(zone, max_height_m=100.0)


# --- 別表第四（ろ）欄の対象建築物 ------------------------------------------

def test_total_height_criterion():
    assert not is_shadow_target("1mid", max_height_m=10.0)     # 「超える」
    assert is_shadow_target("1mid", max_height_m=10.01)


def test_eaves_criterion():
    assert not is_shadow_target("1low", max_height_m=9.0, eaves_height_m=7.0)
    assert is_shadow_target("1low", max_height_m=9.0, eaves_height_m=7.01)


def test_storeys_criterion_is_an_or_not_an_and():
    """「軒の高さが七メートルを超える**又は**地階を除く階数が三以上」。

    軒高 6m の3階建ては条文上は対象。高さだけを見ていると取りこぼす
    （食い違い S）。
    """
    assert is_shadow_target("1low", max_height_m=9.0,
                            eaves_height_m=6.0, storeys_above_ground=3)
    assert is_shadow_target("1low", max_height_m=9.0,
                            eaves_height_m=8.0, storeys_above_ground=2)
    assert not is_shadow_target("1low", max_height_m=9.0,
                                eaves_height_m=6.0, storeys_above_ground=2)


def test_unspecified_row_i_uses_the_eaves_criterion():
    """四の項イの区域では 10m 以下でも対象になりうる（食い違い S）。"""
    assert is_shadow_target("unspecified", max_height_m=9.0,
                            eaves_height_m=8.0, unspecified_row="i")
    # ロなら高さ基準なので対象外
    assert not is_shadow_target("unspecified", max_height_m=9.0,
                                eaves_height_m=8.0, unspecified_row="ro")


# --- 令135条の12第3項第1号（食い違い C） ------------------------------------

def _site_with(kind: RelaxationKind, width_m: float) -> Site:
    return Site.from_rings(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        [{"kind": "adjacent", "relaxation": {"kind": kind.value, "width_m": width_m}},
         {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"}],
        zoning=ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6),
    )


def test_park_is_not_a_deemed_boundary_by_default():
    """条文の列挙は「道路、水面、線路敷その他これらに類するもの」。"""
    assert RelaxationKind.PARK not in DEEMED_BOUNDARY_KINDS
    site = _site_with(RelaxationKind.PARK, 8.0)
    assert deemed_boundary_offsets(site)[0] == 0.0


def test_water_and_railway_are_deemed_boundaries():
    for kind in (RelaxationKind.WATER, RelaxationKind.RAILWAY):
        site = _site_with(kind, 8.0)
        assert deemed_boundary_offsets(site)[0] == pytest.approx(4.0)


def test_park_can_be_opted_in_for_authorities_that_allow_it():
    site = _site_with(RelaxationKind.PARK, 8.0)
    spec = ShadowRegulationSpec(measurement_height_m=4.0,
                                line_5m_max_hours=4.0, line_10m_max_hours=2.5,
                                park_is_deemed_boundary=True)
    assert deemed_boundary_offsets(site, spec)[0] == pytest.approx(4.0)


def test_the_ten_metre_rule_is_unchanged():
    """幅10m以下は幅の1/2、10m超は反対側から敷地側5m（＝幅−5）。"""
    assert deemed_boundary_offsets(_site_with(RelaxationKind.WATER, 6.0))[0] == pytest.approx(3.0)
    assert deemed_boundary_offsets(_site_with(RelaxationKind.WATER, 10.0))[0] == pytest.approx(5.0)
    assert deemed_boundary_offsets(_site_with(RelaxationKind.WATER, 14.0))[0] == pytest.approx(9.0)


# --- 法56条1項2号（隣地斜線・食い違い I） ----------------------------------

from mvce.zoning import (  # noqa: E402
    ADJACENT_SLANT_START_HEIGHT_M,
    adjacent_slant_item,
    adjacent_slant_params,
)


@pytest.mark.parametrize("zone", ["1mid", "2mid", "1res", "2res", "quasi_res"])
def test_item_i_is_20m_and_1_25(zone):
    """イ: 中高層住専・住居系 → 1.25、立上り 20m。"""
    assert adjacent_slant_item(zone) == "i"
    assert adjacent_slant_params(zone, 3.0) == (20.0, 1.25)


@pytest.mark.parametrize("zone", ["neighbor_commercial", "quasi_industrial",
                                  "commercial", "industrial", "industrial_exclusive"])
def test_item_ro_is_31m_and_2_5(zone):
    """ロ: 近隣商業・準工業・商業・工業・工業専用 → 2.5、立上り 31m。"""
    assert adjacent_slant_item(zone) == "ro"
    assert adjacent_slant_params(zone, 3.0) == (31.0, 2.5)


@pytest.mark.parametrize("zone", ["1low", "2low", "denen"])
def test_low_rise_zones_have_no_adjacent_slant(zone):
    """低層住専・田園住居はイ〜ニのどれにも列挙されていない。"""
    assert adjacent_slant_item(zone) is None
    assert adjacent_slant_params(zone, 3.0) is None


def test_item_ni_is_undetermined_without_a_designation():
    """ニ: 無指定は「1.25 又は 2.5 のうち特定行政庁が定めるもの」（食い違い I）。

    2.5 を既定にすると、1.25 が指定された区域で法が許すより高い建築物を
    適合と判定してしまう。原則H に従って止める。
    """
    assert adjacent_slant_item("unspecified") == "ni"
    with pytest.raises(UndeterminedRegulation):
        adjacent_slant_params("unspecified", 3.0)


@pytest.mark.parametrize("slope,start", [(1.25, 20.0), (2.5, 31.0)])
def test_item_ni_accepts_either_designated_slope(slope, start):
    assert adjacent_slant_params("unspecified", 3.0, slope) == (start, slope)


def test_item_ni_rejects_other_slopes():
    with pytest.raises(ValueError):
        adjacent_slant_params("unspecified", 3.0, 1.5)


def test_start_height_follows_the_slope_not_the_zone():
    """立上りは勾配で決まる（号の本文）。1.25→20m、2.5→31m。"""
    assert ADJACENT_SLANT_START_HEIGHT_M == {1.25: 20.0, 2.5: 31.0}
    # 同じ無指定でも、勾配が変われば立上りも変わる
    assert adjacent_slant_params("unspecified", 3.0, 1.25)[0] == 20.0
    assert adjacent_slant_params("unspecified", 3.0, 2.5)[0] == 31.0


def test_item_i_proviso_raises_the_slope_where_designated():
    """イのただし書: 特定行政庁の指定で 1.25 → 2.5。"""
    assert adjacent_slant_params("1res", 3.0, designated_2_5=True) == (31.0, 2.5)


def test_item_i_proviso_excludes_mid_rise_at_or_below_30_10():
    """中高層住専で容積率の限度が 30/10 以下なら、ただし書の対象外。"""
    with pytest.raises(ValueError):
        adjacent_slant_params("1mid", 3.0, designated_2_5=True)
    # 30/10 を超えていれば対象
    assert adjacent_slant_params("1mid", 4.0, designated_2_5=True) == (31.0, 2.5)


def test_zoning_params_validates_the_unspecified_adjacent_slope():
    with pytest.raises(ValueError):
        ZoningParams(zone_type="unspecified", far_ratio=2.0, coverage_ratio=0.6,
                     unspecified_adjacent_slant_slope=1.5)
    ok = ZoningParams(zone_type="unspecified", far_ratio=2.0, coverage_ratio=0.6,
                      unspecified_adjacent_slant_slope=2.5)
    assert ok.unspecified_adjacent_slant_slope == 2.5


def test_applies_is_answerable_without_the_designation():
    """適用の有無は列挙だけで決まるので、勾配未指定でも答えられる。"""
    from mvce.regulations.adjacent_slant import applies
    site = Site.from_rings(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 30.0), (0.0, 30.0)],
        [{"kind": "road", "road_width_m": 6.0}] + [{"kind": "adjacent"}] * 3,
        zoning=ZoningParams(zone_type="unspecified", far_ratio=3.0, coverage_ratio=0.6),
    )
    assert applies(site) is True


# --- 令132条・令134条2項・令135条の2/3（V〜AA） ----------------------------

from mvce.regulations import road_slant  # noqa: E402


def _roads_site(specs, **kw):
    return Site.from_rings(
        [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)], specs,
        zoning=ZoningParams(zone_type="1res", far_ratio=4.0, coverage_ratio=0.6), **kw)


def test_three_frontages_now_compute():
    """前面道路3本でも計算できる（食い違い W、2026-08-30 に解消）。

    以前は令132条2項の「これらの前面道路のみ」の切り方が決まらないとして
    `UndeterminedRegulation` で止めていました。新JCBA方式の解説で区域の
    切り方が確認できたので、`road_regions.py` で区域を作って計算します。
    """
    site = _roads_site([
        {"kind": "road", "road_width_m": 6.0}, {"kind": "road", "road_width_m": 4.0},
        {"kind": "road", "road_width_m": 10.0}, {"kind": "adjacent"},
    ])
    assert road_slant.height_limit_at(site, (15.0, 15.0)) < float("inf")


def test_two_frontages_still_compute():
    """2本なら2項の区域は空。1項か3項で決まるので計算できる。"""
    site = _roads_site([
        {"kind": "road", "road_width_m": 6.0}, {"kind": "road", "road_width_m": 10.0},
        {"kind": "adjacent"}, {"kind": "adjacent"},
    ])
    assert road_slant.height_limit_at(site, (15.0, 15.0)) < float("inf")


def test_article_134_2_is_off_by_default():
    """条文は「よることができる」。選択規定なので既定では使わない。"""
    specs = [
        {"kind": "road", "road_width_m": 4.0,
         "relaxation": {"kind": "park", "width_m": 12.0}},
        {"kind": "road", "road_width_m": 6.0},
        {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    off = road_slant.height_limit_at(_roads_site(specs), (28.0, 15.0))
    on = road_slant.height_limit_at(
        _roads_site(specs, apply_article_134_2=True), (28.0, 15.0))
    assert on > off          # 選択すると緩む
    assert off == pytest.approx(10.0)
    assert on == pytest.approx(22.5)


def test_article_134_2_carries_the_deemed_park_too():
    """「その反対側に同様の公園等があるものとみなす」。幅員だけでなく公園も及ぶ。

    公園の無い側の道路（東6m）でも、公園12mぶんの距離が乗る。
    """
    specs = [
        {"kind": "road", "road_width_m": 4.0,
         "relaxation": {"kind": "park", "width_m": 12.0}},
        {"kind": "road", "road_width_m": 6.0},
        {"kind": "adjacent"}, {"kind": "adjacent"},
    ]
    site = _roads_site(specs, apply_article_134_2=True)
    d = road_slant.detail_at(site, (28.0, 15.0), 1)   # 東の道路
    assert d.applied_width_m == pytest.approx(4.0)     # 公園側道路の幅員
    assert d.relaxation_extra_m == pytest.approx(12.0)  # みなしの公園


# --- 緩和対象の種別（食い違い AA） ------------------------------------------

def _adjacent_site(kind, width=8.0, **kw):
    return Site.from_rings(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 30.0), (0.0, 30.0)],
        [{"kind": "road", "road_width_m": 6.0},
         {"kind": "adjacent", "relaxation": {"kind": kind, "width_m": width}},
         {"kind": "adjacent"}, {"kind": "adjacent"}],
        zoning=ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6), **kw)


def test_adjacent_relaxation_follows_the_enumeration():
    """令135条の3第1項1号: 公園（都市公園を除く）・広場・水面。線路敷は無い。"""
    from mvce.regulations import adjacent_slant
    base = adjacent_slant.edge_height_limit(_adjacent_site("none", 0.0), 1, (10.0, 15.0))
    got = {k: adjacent_slant.edge_height_limit(_adjacent_site(k), 1, (10.0, 15.0))
           for k in ("park", "urban_park", "water", "railway")}
    assert got["park"] > base           # 公園は対象
    assert got["water"] > base          # 水面は対象
    assert got["urban_park"] == base    # 都市公園は明文で除外
    assert got["railway"] == base       # 線路敷は列挙されていない


def test_railway_can_be_opted_in_for_the_adjacent_slant():
    from mvce.regulations import adjacent_slant
    off = adjacent_slant.edge_height_limit(_adjacent_site("railway"), 1, (10.0, 15.0))
    on = adjacent_slant.edge_height_limit(
        _adjacent_site("railway", railway_is_adjacent_relaxation=True), 1, (10.0, 15.0))
    assert on > off


def test_urban_park_still_relaxes_the_road_slant():
    """令134条には都市公園の除外が無い。道路斜線では対象のまま。"""
    def road_limit(kind):
        site = Site.from_rings(
            [(0.0, 0.0), (20.0, 0.0), (20.0, 30.0), (0.0, 30.0)],
            [{"kind": "road", "road_width_m": 6.0,
              "relaxation": {"kind": kind, "width_m": 8.0}},
             {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"}],
            zoning=ZoningParams(zone_type="1res", far_ratio=4.0, coverage_ratio=0.6))
        return road_slant.height_limit_at(site, (10.0, 2.0))
    assert road_limit("urban_park") == road_limit("park")
    assert road_limit("urban_park") > road_limit("none")


def test_north_relaxation_excludes_parks():
    """令135条の4は水面・線路敷のみ。公園・広場は列挙されていない。"""
    from mvce.regulations import north_slant
    from mvce.regulations.north_slant import NORTH_RELAXATION_KINDS
    assert RelaxationKind.PARK not in NORTH_RELAXATION_KINDS
    assert RelaxationKind.URBAN_PARK not in NORTH_RELAXATION_KINDS
    assert NORTH_RELAXATION_KINDS == {RelaxationKind.WATER, RelaxationKind.RAILWAY}


# === 法55条1項（低層住専・田園住居の絶対高さ制限）=====================
#
#   第五十五条　第一種低層住居専用地域、第二種低層住居専用地域又は田園住居
#   地域内においては、建築物の高さは、**十メートル又は十二メートルのうち
#   当該地域に関する都市計画において定められた**建築物の高さの限度を
#   超えてはならない。
#
# どちらかは都市計画が定めるもので、条文に既定値はありません。
# 以前は黙って 10.0 を入れていました（原則H 違反）。

@pytest.mark.parametrize("zone", ["1low", "2low", "denen"])
def test_low_rise_requires_the_absolute_height(zone):
    with pytest.raises(UndeterminedRegulation, match="法55条1項"):
        ZoningParams(zone_type=zone, far_ratio=0.8, coverage_ratio=0.5)


@pytest.mark.parametrize("zone", ["1low", "2low", "denen"])
@pytest.mark.parametrize("height", [10.0, 12.0])
def test_low_rise_accepts_only_10_or_12(zone, height):
    params = ZoningParams(zone_type=zone, far_ratio=0.8, coverage_ratio=0.5,
                          absolute_height_limit_m=height)
    assert params.absolute_height_limit_m == pytest.approx(height)


@pytest.mark.parametrize("height", [8.0, 11.0, 15.0, 0.0])
def test_low_rise_rejects_other_heights(height):
    with pytest.raises(ValueError, match="10mか12m"):
        ZoningParams(zone_type="1low", far_ratio=0.8, coverage_ratio=0.5,
                     absolute_height_limit_m=height)


def test_other_zones_have_no_absolute_height_by_default():
    """法55条は低層住専・田園住居だけ。ほかの用途地域には絶対高さ制限が無い。"""
    for zone in ("1mid", "1res", "commercial", "industrial", "unspecified"):
        params = ZoningParams(zone_type=zone, far_ratio=2.0, coverage_ratio=0.6)
        assert params.absolute_height_limit_m is None, zone


def test_the_refusal_names_both_routes_to_12m():
    """12m は都市計画で定めた場合と、法55条2項の緩和の場合がある。"""
    with pytest.raises(UndeterminedRegulation) as e:
        ZoningParams(zone_type="1low", far_ratio=0.8, coverage_ratio=0.5)
    assert "法55条2項" in str(e.value)


# === 法56条1項3号の括弧書き（食い違い H）==============================
#
#   三　第一種低層住居専用地域、第二種低層住居専用地域若しくは田園住居地域内
#   又は第一種中高層住居専用地域若しくは第二種中高層住居専用地域（**次条
#   第一項の規定に基づく条例で別表第四の二の項に規定する（一）、（二）又は
#   （三）の号が指定されているものを除く。以下この号及び第七項第三号に
#   おいて同じ。**）内においては、（略）
#
# 括弧書きが付いているのは中高層住専だけ。低層住専・田園住居は「又は」の
# 前に列挙されていて、括弧書きの外です。

@pytest.mark.parametrize("zone", ["1mid", "2mid"])
def test_shadow_designation_removes_the_north_slant_in_mid_rise(zone):
    from mvce.zoning import north_slant_params

    assert north_slant_params(zone) == (10.0, 1.25)
    assert north_slant_params(zone, shadow_designated=True) is None


@pytest.mark.parametrize("zone", ["1low", "2low", "denen"])
def test_low_rise_keeps_the_north_slant_even_when_designated(zone):
    """低層住専・田園住居には括弧書きが無い。"""
    from mvce.zoning import north_slant_params

    assert north_slant_params(zone, shadow_designated=True) == (5.0, 1.25)


def test_the_exclusion_only_covers_mid_rise():
    from mvce.zoning import NORTH_SLANT_EXCLUDABLE_ZONES

    assert NORTH_SLANT_EXCLUDABLE_ZONES == frozenset({"1mid", "2mid"})


def test_north_slant_applies_follows_the_designation():
    from mvce.regulations import north_slant

    square = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
    specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    for designated, expected in ((False, True), (True, False)):
        site = Site.from_rings(
            square, specs,
            ZoningParams("1mid", 2.0, 0.6, shadow_ordinance_designated=designated))
        assert north_slant.applies(site) is expected


def test_the_exclusion_also_removes_the_sky_ratio_north_positions():
    """「以下この号及び**第七項第三号**において同じ」なので算定位置も消える。"""
    from mvce.regulations.sky_positions import north_positions

    square = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
    specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    plain = Site.from_rings(square, specs, ZoningParams("1mid", 2.0, 0.6))
    designated = Site.from_rings(
        square, specs, ZoningParams("1mid", 2.0, 0.6, shadow_ordinance_designated=True))
    assert north_positions(plain)
    assert north_positions(designated) == []


def test_the_designation_actually_frees_height():
    """北側斜線が外れるぶん、北寄りが高く取れる。"""
    from mvce.regulations.height_field import height_limit_at

    square = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
    specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    plain = Site.from_rings(square, specs, ZoningParams("1mid", 4.0, 0.6))
    designated = Site.from_rings(
        square, specs, ZoningParams("1mid", 4.0, 0.6, shadow_ordinance_designated=True))
    point = (15.0, 18.0)          # 北辺のすぐ手前
    assert height_limit_at(designated, point) > height_limit_at(plain, point)


def test_the_optimizer_warns_when_the_designation_is_missing():
    """日影を計算しているのに指定が無ければ、厳しい側のままだと知らせる。"""
    from mvce.regulations.shadow import ShadowRegulationSpec
    from mvce.solvers.optimizer import OptimizeOptions, optimize

    square = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
    specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    spec = ShadowRegulationSpec(measurement_height_m=4.0, line_5m_max_hours=5.0,
                                line_10m_max_hours=3.0, time_step_minutes=30.0,
                                sample_interval_m=6.0)
    options = OptimizeOptions(cell_size_x_m=10.0, cell_size_y_m=10.0)

    plain = Site.from_rings(square, specs, ZoningParams("1mid", 2.0, 0.6))
    assert any("法56条1項3号" in n for n in optimize(plain, spec, options).notes)

    designated = Site.from_rings(
        square, specs, ZoningParams("1mid", 2.0, 0.6, shadow_ordinance_designated=True))
    assert not any("法56条1項3号" in n for n in optimize(designated, spec, options).notes)

    # 低層住専は括弧書きの外なので注記は出ない
    low = Site.from_rings(
        square, specs,
        ZoningParams("1low", 0.8, 0.5, absolute_height_limit_m=10.0))
    assert not any("法56条1項3号" in n for n in optimize(low, spec, options).notes)


# === 法56条1項2号の本文の括弧書き ====================================
#
#   二　（略）イからニまでに定める数値が二・五とされている建築物（**ロ及び
#   ハに掲げる建築物で、特定行政庁が都道府県都市計画審議会の議を経て指定する
#   区域内にあるものを除く。**以下この号及び第七項第二号において同じ。）で
#   高さが三十一メートルを超える部分を有するものにあつては、それぞれその
#   部分から隣地境界線までの水平距離のうち最小のものに相当する距離を
#   **加えたもの**に、（略）
#
# ロ・ハの指定区域では後退距離の加算をしません。指定はイのただし書と同じ
# ものとみて adjacent_slant_2_5_designated で受けています。

def test_setback_addition_is_the_default():
    from mvce.zoning import adjacent_slant_setback_applies

    for zone in ("1res", "1mid", "commercial", "neighbor_commercial", "unspecified"):
        assert adjacent_slant_setback_applies(zone) is True


@pytest.mark.parametrize("zone", [
    "neighbor_commercial", "quasi_industrial", "commercial",
    "industrial", "industrial_exclusive",
])
def test_designated_removes_the_setback_addition_in_item_ro(zone):
    """ロの地域（近隣商業・準工業・商業・工業・工業専用）。"""
    from mvce.zoning import adjacent_slant_setback_applies

    assert adjacent_slant_setback_applies(zone, designated_2_5=True) is False


@pytest.mark.parametrize("zone", ["1mid", "2mid", "1res", "2res", "quasi_res"])
def test_item_i_keeps_the_setback_addition(zone):
    """イの地域は括弧書きの対象外。ただし書で 2.5 になるだけ。"""
    from mvce.zoning import adjacent_slant_setback_applies

    assert adjacent_slant_setback_applies(zone, designated_2_5=True) is True


def test_unspecified_keeps_the_setback_addition():
    """ニ（無指定区域）も括弧書きの対象外（列挙はロ・ハのみ）。"""
    from mvce.zoning import adjacent_slant_setback_applies

    assert adjacent_slant_setback_applies("unspecified", designated_2_5=True) is True


def _setback_site(zone, far, designated, setback=3.0):
    square = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
    specs = [{"kind": "road", "road_width_m": 6.0, "wall_setback_m": setback}]
    specs += [{"kind": "adjacent", "wall_setback_m": setback}] * 3
    return Site.from_rings(
        square, specs,
        ZoningParams(zone, far, 0.8, adjacent_slant_2_5_designated=designated))


def test_the_designation_makes_a_commercial_site_stricter():
    """ロの指定区域では後退距離が効かなくなるので、制限が下がる。"""
    from mvce.regulations import adjacent_slant

    point = (15.0, 10.0)
    plain = adjacent_slant.height_limit_at(_setback_site("commercial", 6.0, False), point)
    designated = adjacent_slant.height_limit_at(
        _setback_site("commercial", 6.0, True), point)
    assert designated < plain
    # 勾配2.5・後退3m ぶんちょうど下がる
    assert plain - designated == pytest.approx(2.5 * 3.0)


def test_the_designation_makes_a_residential_site_more_generous():
    """イの地域では逆に、ただし書で 1.25 → 2.5 になって緩む。"""
    from mvce.regulations import adjacent_slant

    point = (15.0, 10.0)
    plain = adjacent_slant.height_limit_at(_setback_site("1res", 4.0, False), point)
    designated = adjacent_slant.height_limit_at(_setback_site("1res", 4.0, True), point)
    assert designated > plain


def test_the_rise_height_is_not_removed_by_the_parenthetical():
    """「以下この号において同じ」を末尾にまで及ぼさない。

    文字どおり及ぼすと、ロの指定区域の建築物は立上りが 20m でも 31m でも
    なくなり、隣地境界線上で高さ0になります。明らかに法の趣旨に反するので、
    括弧書きが効くのは後退距離の加算だけと読んでいます。
    """
    from mvce.regulations import adjacent_slant

    # 後退0なら加算の有無で差が出ないので、立上り31mがそのまま残るはず
    site = _setback_site("commercial", 6.0, True, setback=0.0)
    on_boundary = adjacent_slant.edge_height_limit(site, 1, (30.0, 10.0))
    assert on_boundary == pytest.approx(31.0)


def test_the_sky_ratio_baseline_is_not_removed_either():
    """法56条7項2号の基準線（12.4m）も残る。同じ理由。"""
    from mvce.regulations.sky_positions import adjacent_baseline_distance_m

    site = _setback_site("commercial", 6.0, True)
    assert adjacent_baseline_distance_m(site) == pytest.approx(12.4)
