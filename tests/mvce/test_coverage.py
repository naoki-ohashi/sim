"""建蔽率の緩和と適用除外（法53条3項・6項・7項・8項）のテスト。

    ３　前二項の規定の適用については、第一号又は第二号のいずれかに該当する
    建築物にあつては第一項各号に定める数値に十分の一を加えたものをもつて
    当該各号に定める数値とし、第一号及び第二号に該当する建築物にあつては
    同項各号に定める数値に十分の二を加えたものをもつて当該各号に定める
    数値とする。
    一　防火地域（第一項第二号から第四号までの規定により建蔽率の限度が
    十分の八とされている地域を除く。）内にあるイに該当する建築物又は
    準防火地域内にあるイ若しくはロのいずれかに該当する建築物
    二　街区の角にある敷地又はこれに準ずる敷地で特定行政庁が指定するものの
    内にある建築物

固定するのは3つです。

1. **準防火地域と準耐火建築物等**が対象に入ること（旧法には無かった）
2. 8/10 の地域は 3項1号ではなく **6項1号（適用除外）**に行くこと
3. **加算が先、按分が後**であること（3項は「前二項の規定の適用については」）
"""
import pytest

from mvce.site import Site
from mvce.zone_split import ZonePart, ZoneSplit, weighted_coverage_limit
from mvce.zoning import (
    FIRE_ZONES,
    FIREPROOF_GRADES,
    ZoningParams,
    coverage_fire_bonus_applies,
    coverage_is_exempt,
    coverage_limit,
    effective_fire_zone,
)

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]   # 600 m2
SPECS = [{"kind": "road", "road_width_m": 6.0}] + [{"kind": "adjacent"}] * 3


def _site(**kw):
    return Site.from_rings(SQUARE, SPECS, ZoningParams(**kw))


# === 定数 =============================================================

def test_the_enums_are_the_statutory_cases():
    assert FIRE_ZONES == ("none", "fire", "quasi_fire",
                          "fire_partial", "quasi_fire_partial")
    assert FIREPROOF_GRADES == ("none", "quasi_fireproof", "fireproof")


# === 3項1号 ===========================================================

def test_fire_zone_needs_a_fireproof_building():
    """防火地域はイ（耐火建築物等）のみ。準耐火では足りない。"""
    assert coverage_fire_bonus_applies("1res", 0.6, "fire", "fireproof")
    assert not coverage_fire_bonus_applies("1res", 0.6, "fire", "quasi_fireproof")
    assert not coverage_fire_bonus_applies("1res", 0.6, "fire", "none")


def test_quasi_fire_zone_accepts_quasi_fireproof():
    """準防火地域はイ**若しくは**ロ。準耐火建築物等でも対象。

    旧法（平成30年版）には準防火地域も準耐火建築物も入っていませんでした。
    """
    assert coverage_fire_bonus_applies("1res", 0.6, "quasi_fire", "fireproof")
    assert coverage_fire_bonus_applies("1res", 0.6, "quasi_fire", "quasi_fireproof")
    assert not coverage_fire_bonus_applies("1res", 0.6, "quasi_fire", "none")


def test_no_bonus_without_a_fire_zone():
    for grade in FIREPROOF_GRADES:
        assert not coverage_fire_bonus_applies("1res", 0.6, "none", grade)


def test_eight_tenths_zones_go_to_the_exemption_not_the_bonus():
    """8/10 の地域は 3項1号の括弧書きで除かれ、6項1号（適用除外）に行く。"""
    assert not coverage_fire_bonus_applies("commercial", 0.8, "fire", "fireproof")
    assert coverage_is_exempt("commercial", 0.8, "fire", "fireproof")


@pytest.mark.parametrize("zone", [
    "1res", "2res", "quasi_res", "quasi_industrial",   # 1項2号
    "neighbor_commercial",                             # 1項3号
    "commercial",                                      # 1項4号
])
def test_all_item_2_to_4_zones_can_be_eight_tenths(zone):
    assert coverage_is_exempt(zone, 0.8, "fire", "fireproof")


@pytest.mark.parametrize("zone", ["1low", "1mid", "denen", "industrial",
                                  "industrial_exclusive", "unspecified"])
def test_zones_outside_items_2_to_4_never_reach_the_exemption(zone):
    """1項1号・5号・6号の地域は 8/10 になりえないので括弧書きの対象外。"""
    height = 10.0 if zone in ("1low", "2low", "denen") else None
    _ = height   # ZoningParams を作らない直接呼び出しなので未使用
    assert not coverage_is_exempt(zone, 0.8, "fire", "fireproof")
    assert coverage_fire_bonus_applies(zone, 0.8, "fire", "fireproof")


def test_eight_tenths_only_matters_at_exactly_eight_tenths():
    assert not coverage_is_exempt("commercial", 0.6, "fire", "fireproof")
    assert coverage_fire_bonus_applies("commercial", 0.6, "fire", "fireproof")


# === 3項2号と加算量 ===================================================

def test_one_item_adds_one_tenth():
    assert coverage_limit("1res", 0.6, "fire", "fireproof") == pytest.approx(0.7)
    assert coverage_limit("1res", 0.6, corner_lot_designated=True) == pytest.approx(0.7)


def test_both_items_add_two_tenths():
    assert coverage_limit("1res", 0.6, "fire", "fireproof",
                          corner_lot_designated=True) == pytest.approx(0.8)


def test_no_item_adds_nothing():
    assert coverage_limit("1res", 0.6) == pytest.approx(0.6)


def test_the_limit_never_exceeds_one():
    assert coverage_limit("commercial", 0.9, "quasi_fire", "fireproof",
                          corner_lot_designated=True) == pytest.approx(1.0)


def test_the_exemption_returns_none_not_one():
    """6項1号は「適用しない」。1.0（＝敷地いっぱい）とは意味が違う。"""
    assert coverage_limit("commercial", 0.8, "fire", "fireproof") is None


# === 7項・8項のみなし =================================================

def test_article_53_paragraph_7():
    """敷地が防火地域の内外にわたり、全部が耐火建築物等なら全て防火地域内。"""
    assert effective_fire_zone("fire_partial", "fireproof") == "fire"
    assert effective_fire_zone("fire_partial", "quasi_fireproof") == "none"
    assert effective_fire_zone("fire_partial", "none") == "none"


def test_article_53_paragraph_8():
    """準防火地域とその他にわたり、全部が耐火または準耐火なら全て準防火地域内。"""
    assert effective_fire_zone("quasi_fire_partial", "fireproof") == "quasi_fire"
    assert effective_fire_zone("quasi_fire_partial", "quasi_fireproof") == "quasi_fire"
    assert effective_fire_zone("quasi_fire_partial", "none") == "none"


def test_a_plain_zone_passes_through():
    for zone in ("none", "fire", "quasi_fire"):
        assert effective_fire_zone(zone, "fireproof") == zone


def test_the_deeming_reaches_the_bonus():
    assert coverage_limit("1res", 0.6, "fire_partial", "fireproof") == pytest.approx(0.7)
    assert coverage_limit("1res", 0.6, "fire_partial", "quasi_fireproof") == pytest.approx(0.6)


def test_bad_values_are_rejected():
    with pytest.raises(ValueError, match="fire_zone"):
        effective_fire_zone("semi_fire", "none")
    with pytest.raises(ValueError, match="fireproof"):
        effective_fire_zone("fire", "wood")
    with pytest.raises(ValueError, match="fire_zone"):
        ZoningParams("1res", 2.0, 0.6, fire_zone="semi_fire")


# === Site との繋ぎ ====================================================

def test_site_applies_the_bonus():
    site = _site(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6,
                 fire_zone="fire", fireproof="fireproof")
    assert site.coverage_ratio_limit() == pytest.approx(0.7)
    assert site.max_building_area_m2() == pytest.approx(420.0)


def test_site_with_the_exemption_has_no_coverage_limit():
    site = _site(zone_type="commercial", far_ratio=6.0, coverage_ratio=0.8,
                 fire_zone="fire", fireproof="fireproof")
    assert site.coverage_ratio_limit() is None
    assert site.max_building_area_m2() == pytest.approx(600.0)   # 敷地面積そのもの


def test_the_default_site_is_unchanged():
    site = _site(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    assert site.coverage_ratio_limit() == pytest.approx(0.6)
    assert site.max_building_area_m2() == pytest.approx(360.0)


# === 按分との順番（3項 → 2項）=========================================

def _split(*parts):
    return ZoneSplit(tuple(
        ZonePart(ZoningParams(z, 2.0, c, fire_zone=fz, fireproof=fp,
                              corner_lot_designated=corner), a, label=z)
        for z, c, a, fz, fp, corner in parts))


def test_the_bonus_is_applied_before_the_proration():
    """3項は「前二項の規定の適用については」＝1項の数値を読み替える規定。

    1住居 50%（300m2）と商業 60%（300m2）、どちらも角地指定あり。
      加算が先: (50+10)/2 + (60+10)/2 = 30 + 35 = 65%
      按分が先: (50+60)/2 + 10 = 55 + 10 = 65%
    この例では一致するので、片方だけ加算が付く例で確かめる。
    """
    # 1住居だけ角地指定、商業は無し
    split = _split(("1res", 0.5, 300.0, "none", "none", True),
                   ("commercial", 0.6, 300.0, "none", "none", False))
    value, notes = weighted_coverage_limit(split)
    # 加算が先: (50+10)×0.5 + 60×0.5 = 30 + 30 = 60%
    assert value == pytest.approx(0.6)
    assert any("法53条3項で +10%" in n for n in notes)


def test_an_exempt_part_removes_the_whole_limit():
    """6項は「前各項の規定は…適用しない」。按分せず制限なしにする。"""
    split = _split(("commercial", 0.8, 300.0, "fire", "fireproof", False),
                   ("1res", 0.5, 300.0, "none", "none", False))
    value, notes = weighted_coverage_limit(split)
    assert value is None
    assert any("法53条6項1号" in n for n in notes)


def test_a_split_without_bonuses_is_unchanged():
    split = _split(("1res", 0.5, 300.0, "none", "none", False),
                   ("commercial", 0.8, 300.0, "none", "none", False))
    assert weighted_coverage_limit(split)[0] == pytest.approx(0.65)
