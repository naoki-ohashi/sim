"""逆日影計算（屋根越しパターン・棟状パターン）の検証.

インデックス上の判定に加えて、`compute_shadow_hours`（shapely を使う独立
実装）で必ず再確認します。天空率のときと同じ検証の考え方です。
"""
import numpy as np
import pytest

from mvce.mesh import assign_height_limits, build_mesh
from mvce.solvers.optimizer import _apply_coverage_cap, _apply_far_cap, _floors_to_blocks
from mvce.regulations.shadow import ShadowRegulationSpec, compute_shadow_hours
from mvce.inverse.shadow_envelope import RoofPlaneSpec, search_roof_envelope
from mvce.site import Site
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
DEEP = [(0.0, 0.0), (20.0, 0.0), (20.0, 40.0), (0.0, 40.0)]


def _site(points=SQUARE, far=3.0, coverage=0.6, road=8.0, zone="1res", north=0.0):
    from mvce.north import NorthReference
    zoning = ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=coverage)
    specs = [{"kind": "road", "road_width_m": road}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    return Site.from_rings(points, specs, zoning, north=NorthReference(north_angle_deg=north))


def _spec(**kwargs):
    base = dict(measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
                time_step_minutes=30.0, sample_interval_m=6.0)
    base.update(kwargs)
    return ShadowRegulationSpec(**base)


def _base_floors(site, cell=3.0, mesh_angle_deg=0.0):
    area = build_mesh(site, cell, cell, angle_deg=mesh_angle_deg)
    assign_height_limits(area)
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    _apply_coverage_cap(area, floors, site.max_building_area_m2())
    _apply_far_cap(area, floors, site.max_total_floor_area_m2())
    return area, floors


def _independent_check(site, area, floors, spec):
    blocks = _floors_to_blocks(area, floors, site.floor_height_m)
    return all(line.ok for line in compute_shadow_hours(site, blocks, spec))


# === 基本的な適合性 ===================================================

@pytest.mark.parametrize("pattern", ["lean_to", "ridge"])
def test_result_is_independently_verified_compliant(pattern):
    site = _site(far=3.0)
    spec = _spec()
    area, base = _base_floors(site)
    result = search_roof_envelope(site, area, spec, base, site.floor_height_m, pattern=pattern)

    assert result.spec is not None, "この条件では屋根形状による調整が必要なはず"
    assert _independent_check(site, area, result.floors, spec)


def test_already_compliant_site_needs_no_roof():
    """緩い日影規制では、屋根形状を使わなくても最初から適合している。"""
    site = _site(far=1.0, coverage=0.4)
    spec = _spec(line_5m_max_hours=8.0, line_10m_max_hours=8.0)
    area, base = _base_floors(site)
    result = search_roof_envelope(site, area, spec, base, site.floor_height_m)

    assert result.spec is None
    assert (result.floors == base).all()


def test_floors_never_exceed_the_slant_line_baseline():
    """屋根形状で削ることはあっても、元の高さ制限を超えて積むことはない。"""
    site = _site(far=3.0)
    spec = _spec()
    area, base = _base_floors(site)
    for pattern in ("lean_to", "ridge"):
        result = search_roof_envelope(site, area, spec, base, site.floor_height_m, pattern=pattern)
        assert (result.floors <= base).all()


# === パターン間の関係 ===================================================

def test_ridge_is_at_least_as_good_as_lean_to():
    """棟状パターンは屋根越しパターンを特殊形として含むので、劣ることはない。"""
    site = _site(points=DEEP, far=4.0, coverage=0.6, road=8.0)
    spec = _spec(line_5m_max_hours=4.0, line_10m_max_hours=2.5, sample_interval_m=8.0)
    area, base = _base_floors(site, cell=4.0)

    lean_to = search_roof_envelope(site, area, spec, base, site.floor_height_m, pattern="lean_to")
    ridge = search_roof_envelope(site, area, spec, base, site.floor_height_m, pattern="ridge")

    area_of = lambda r: sum(r.floors[i] * area.cells[i].area_m2 for i in range(len(area.cells)))
    assert area_of(ridge) >= area_of(lean_to) - 1e-6


def test_lean_to_uses_a_single_slope_direction():
    """屋根越しパターンは、全マスが同じ低勾配側になる（反対側が存在しない）。"""
    site = _site(far=3.0)
    spec = _spec()
    area, base = _base_floors(site)
    result = search_roof_envelope(site, area, spec, base, site.floor_height_m, pattern="lean_to")
    assert result.spec.pattern == "lean_to"
    assert result.spec.pitch_far_deg == 0.0


# === 方位の探索 ==========================================================

def test_search_stays_near_the_critical_azimuth():
    """棟の向きは、臨界方位±探索幅の範囲に収まる（無関係な方向へは飛ばない）。"""
    site = _site(far=3.0)
    spec = _spec()
    area, base = _base_floors(site)
    span = 15.0
    result = search_roof_envelope(
        site, area, spec, base, site.floor_height_m, pattern="ridge", angle_span_deg=span)

    assert result.spec.critical_azimuth_deg is not None
    center = (result.spec.critical_azimuth_deg + 180.0) % 360.0
    delta = abs(((result.spec.low_azimuth_deg - center + 180.0) % 360.0) - 180.0)
    assert delta <= span + 1e-6


def test_fixed_azimuth_skips_the_search():
    """方位を固定すると、その1方位だけで探索する（実務者が向きを指定したい場合）。"""
    site = _site(far=3.0)
    spec = _spec()
    area, base = _base_floors(site)
    result = search_roof_envelope(
        site, area, spec, base, site.floor_height_m, pattern="ridge",
        fixed_low_azimuth_deg=90.0)
    assert result.spec.low_azimuth_deg == pytest.approx(90.0)
    assert _independent_check(site, area, result.floors, spec)


def test_rotated_true_north_still_anchors_the_search_correctly():
    """真北が図面に対して斜めでも、低勾配側は「その敷地の」臨界方位±探索幅に収まる。

    敷地の形はそのまま、真北の向き（`north_angle_deg`）だけを回します。
    敷地の物理的な配置自体が変わる（道路の向きが真北に対して変わる）ので、
    臨界方位の値そのものが north=0 と一致する理由はありません。確かめたいのは
    「north_angle_deg を回しても、探索が正しくその敷地の臨界方位を中心に
    行われる」という配線そのものです（`_low_normal` が `NorthReference` 経由で
    真北回転を正しく反映しているかの確認）。
    """
    site = _site(far=3.0, north=40.0)
    spec = _spec()
    area, base = _base_floors(site)
    span = 15.0
    result = search_roof_envelope(
        site, area, spec, base, site.floor_height_m, pattern="ridge", angle_span_deg=span)

    assert result.spec is not None
    assert _independent_check(site, area, result.floors, spec)
    center = (result.spec.critical_azimuth_deg + 180.0) % 360.0
    delta = abs(((result.spec.low_azimuth_deg - center + 180.0) % 360.0) - 180.0)
    assert delta <= span + 1e-6


def test_low_azimuth_is_always_opposite_the_critical_sun_azimuth():
    """低勾配側の方位は、必ず「臨界太陽方位＋180度」を中心にした値である。

    測定点は太陽と反対側にあるので、低勾配側（測定点に面する側）は
    臨界方位そのものではなく、その反対向きになるはずです。
    """
    site = _site(far=3.0)
    spec = _spec()
    area, base = _base_floors(site)
    result = search_roof_envelope(
        site, area, spec, base, site.floor_height_m, pattern="ridge",
        angle_span_deg=0.0)   # 探索幅0＝ズレなしで確認する

    expected = (result.spec.critical_azimuth_deg + 180.0) % 360.0
    assert result.spec.low_azimuth_deg == pytest.approx(expected, abs=1e-6)


# === 異常系・境界ケース ==================================================

def test_rejects_unknown_pattern():
    site = _site()
    spec = _spec()
    area, base = _base_floors(site)
    with pytest.raises(ValueError):
        search_roof_envelope(site, area, spec, base, site.floor_height_m, pattern="hip")


def test_empty_base_floors_returns_unchanged():
    site = _site()
    spec = _spec()
    area, _base = _base_floors(site)
    zero = np.zeros(len(area.cells), dtype=int)
    result = search_roof_envelope(site, area, spec, zero, site.floor_height_m)
    assert result.spec is None
    assert (result.floors == 0).all()


def test_describe_ja_mentions_pattern_and_pitch():
    spec = RoofPlaneSpec(pattern="ridge", low_azimuth_deg=45.0, ridge_offset_m=2.0,
                         pitch_near_deg=30.0, pitch_far_deg=15.0, ridge_height_m=12.5,
                         critical_azimuth_deg=225.0)
    text = spec.describe_ja()
    assert "棟状" in text and "30" in text and "12.5" in text
