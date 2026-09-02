"""法52条2項（前面道路幅員による容積率制限）のテスト。"""
import pytest

from mvce.far import compute_far
from mvce.site import Site
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(zone="1res", far=4.0, road_widths=(6.0,), **zoning_kwargs):
    specs = []
    for i in range(4):
        if i < len(road_widths) and road_widths[i] is not None:
            specs.append({"kind": "road", "road_width_m": road_widths[i]})
        else:
            specs.append({"kind": "adjacent"})
    return Site.from_rings(
        SQUARE, specs, ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=0.6,
                                    **zoning_kwargs))


def test_residential_coefficient_is_four_tenths():
    # 6m × 0.4 = 240% < 指定400% なので道路幅員が効く
    result = compute_far(_site(zone="1res", far=4.0, road_widths=(6.0,)))
    assert result.coefficient == pytest.approx(0.4)
    assert result.road_far == pytest.approx(2.4)
    assert result.effective_far == pytest.approx(2.4)
    assert result.limited_by_road


def test_commercial_coefficient_is_six_tenths():
    # 6m × 0.6 = 360% < 指定600%
    result = compute_far(_site(zone="commercial", far=6.0, road_widths=(6.0,)))
    assert result.coefficient == pytest.approx(0.6)
    assert result.road_far == pytest.approx(3.6)
    assert result.effective_far == pytest.approx(3.6)


def test_designated_far_wins_when_smaller():
    # 8m × 0.4 = 320% だが指定が200%なので指定が優先
    result = compute_far(_site(zone="1res", far=2.0, road_widths=(8.0,)))
    assert result.road_far == pytest.approx(3.2)
    assert result.effective_far == pytest.approx(2.0)
    assert not result.limited_by_road


def test_no_reduction_at_twelve_metres_or_wider():
    result = compute_far(_site(zone="1res", far=4.0, road_widths=(12.0,)))
    assert result.road_far is None
    assert result.effective_far == pytest.approx(4.0)
    assert any("12m以上" in n for n in result.notes)


def test_widest_road_is_used_when_several():
    # 4m と 10m の2本 → 10m で判定 (10*0.4 = 400%)
    site = _site(zone="1res", far=6.0, road_widths=(4.0, 10.0))
    result = compute_far(site)
    assert result.max_road_width_m == pytest.approx(10.0)
    assert result.road_far == pytest.approx(4.0)
    assert any("2本" in n for n in result.notes)


def test_site_max_total_floor_area_uses_effective_far():
    site = _site(zone="1res", far=4.0, road_widths=(6.0,))
    # 600 m2 × 240% = 1440 m2（指定400%なら2400 m2だが道路で制限される）
    assert site.max_total_floor_area_m2() == pytest.approx(1440.0)


def test_no_road_falls_back_to_designated_with_warning():
    site = _site(zone="1res", far=4.0, road_widths=(None,))
    result = compute_far(site)
    assert result.effective_far == pytest.approx(4.0)
    assert any("前面道路が設定されていません" in n for n in result.notes)


# === 法52条2項各号の括弧書き（特定行政庁が指定する区域）===============
#
#     一　…低層住居専用地域…又は田園住居地域内の建築物　十分の四
#     二　…中高層住居専用地域…又は…住居地域…（略）　十分の四（特定行政庁が
#         都道府県都市計画審議会の議を経て指定する区域内の建築物にあつては、
#         十分の六）
#     三　その他の建築物　十分の六（特定行政庁が…指定する区域内の建築物に
#         あつては、十分の四又は十分の八のうち特定行政庁が…定めるもの）
#
# 三号の 4/10 が要注意です。既定の 6/10 で計算すると実際の限度の1.5倍を
# 許してしまいます（緩い側）。


def test_the_third_item_designation_can_tighten_the_coefficient():
    """三号（商業等）の指定区域は 4/10 もありえる。**既定より厳しい**。"""
    loose = compute_far(_site(zone="commercial", far=6.0, road_widths=(8.0,)))
    tight = compute_far(_site(zone="commercial", far=6.0, road_widths=(8.0,),
                              far_road_coefficient_designated=0.4))
    assert loose.coefficient == pytest.approx(0.6)
    assert loose.effective_far == pytest.approx(4.8)
    assert tight.coefficient == pytest.approx(0.4)
    assert tight.effective_far == pytest.approx(3.2)
    # 既定のままだと実際の1.5倍。この差を黙って出さないための入力です
    assert loose.effective_far == pytest.approx(tight.effective_far * 1.5)


def test_the_third_item_designation_can_also_loosen():
    result = compute_far(_site(zone="commercial", far=8.0, road_widths=(8.0,),
                               far_road_coefficient_designated=0.8))
    assert result.coefficient == pytest.approx(0.8)
    assert result.effective_far == pytest.approx(6.4)


def test_the_second_item_designation_only_loosens():
    """二号（中高層住専・住居系）は 4/10 → 6/10 の緩和だけ。"""
    plain = compute_far(_site(zone="1res", far=4.0, road_widths=(8.0,)))
    designated = compute_far(_site(zone="1res", far=4.0, road_widths=(8.0,),
                                   far_road_coefficient_designated=0.6))
    assert plain.coefficient == pytest.approx(0.4)
    assert designated.coefficient == pytest.approx(0.6)


def test_the_first_item_has_no_parenthetical():
    """一号（低層住専・田園住居）に括弧書きは無い。指定は受け付けない。"""
    with pytest.raises(ValueError, match="第一号"):
        _site(zone="1low", far=1.0, road_widths=(6.0,),
              absolute_height_limit_m=10.0, far_road_coefficient_designated=0.6)


@pytest.mark.parametrize("zone,bad", [("1res", 0.4), ("1res", 0.8),
                                      ("commercial", 0.6), ("commercial", 0.5)])
def test_a_coefficient_the_item_does_not_allow_is_rejected(zone, bad):
    with pytest.raises(ValueError, match="法52条2項"):
        _site(zone=zone, far=4.0, road_widths=(6.0,),
              far_road_coefficient_designated=bad)


def test_the_note_names_the_direction_for_the_third_item():
    """注意書きが**向き**を言うこと。

    「割増は未対応」とだけ書くと、読んだ人は「小さめに出るなら安全」と
    受け取ります。三号は逆に**緩い側**に出るので、そう書かなければ
    危険な誤解を招きます。
    """
    notes = " ".join(compute_far(
        _site(zone="commercial", far=6.0, road_widths=(8.0,))).notes)
    assert "第三号" in notes
    assert "1.5倍" in notes
    assert "far_road_coefficient_designated" in notes


def test_no_scary_note_when_the_designation_is_given():
    notes = " ".join(compute_far(
        _site(zone="commercial", far=6.0, road_widths=(8.0,),
              far_road_coefficient_designated=0.4)).notes)
    assert "1.5倍" not in notes
    assert "指定されています" in notes


def test_the_first_item_gets_no_designation_note():
    """一号に括弧書きは無いので、注意書きも出さない。"""
    notes = " ".join(compute_far(
        _site(zone="1low", far=1.0, road_widths=(6.0,),
              absolute_height_limit_m=10.0)).notes)
    assert "指定区域" not in notes


def test_the_split_path_uses_the_designated_coefficient_too():
    """法52条7項の按分でも括弧書きが効くこと（片方だけ直すと食い違う）。"""
    from mvce.zone_split import ZonePart, ZoneSplit, far_limit_for

    zoning = ZoningParams(zone_type="commercial", far_ratio=6.0, coverage_ratio=0.8,
                          far_road_coefficient_designated=0.4)
    assert far_limit_for(zoning, 8.0) == pytest.approx(3.2)
    assert ZoneSplit((ZonePart(zoning=zoning, area_m2=100.0),)).is_single
