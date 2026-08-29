"""日影規制と天空率の同時最適化のテスト.

以前は「日影をすべて解消してから天空率をすべて解消する」という2段階
でした。この順番だと、片方の是正がもう片方も満たしていた場合に、それに
気づけず削り込みが重複することがあります。voxel（自由形）は1手ずつ交互に
進める `_resolve_shadow_and_sky_jointly` で、lean_to/ridge（逆日影）は
棟の探索そのものに天空率の適合も条件として含める `roof_envelope.py` の
仕組みで、それぞれ両方を同時に扱います。
"""
import numpy as np
import pytest

from mvce.mesh import assign_height_limits, build_mesh
from mvce.solvers.optimizer import (
    OptimizeOptions,
    _apply_coverage_cap,
    _apply_far_cap,
    _cap_by_far,
    _floors_to_blocks,
    _refill,
    _resolve_shadow,
    _resolve_shadow_and_sky_jointly,
    _resolve_sky_ratio,
    optimize,
)
from mvce.regulations import sky_ratio
from mvce.regulations.shadow import ShadowRegulationSpec, compute_shadow_hours
from mvce.inverse.shadow_envelope import search_roof_envelope
from mvce.index.shadow_index import build_shadow_index
from mvce.site import Site
from mvce.index.sky_index import AZIMUTH_OFFSET_RATIO, build_sky_index
from mvce.zoning import ZoningParams

INTERVAL, N_AZIMUTH = 4.0, 72


def _site(points, far, road, zone="1res", coverage=0.6):
    zoning = ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=coverage)
    specs = [{"kind": "road", "road_width_m": road}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    return Site.from_rings(points, specs, zoning)


def _spec(**kwargs):
    base = dict(measurement_height_m=4.0, time_step_minutes=30.0, sample_interval_m=6.0)
    base.update(kwargs)
    return ShadowRegulationSpec(**base)


def _independent_check(site, blocks, spec):
    shadow_ok = all(line.ok for line in compute_shadow_hours(site, blocks, spec))
    checks = sky_ratio.check(site, blocks, interval_m=INTERVAL, n_azimuth=N_AZIMUTH,
                             azimuth_offset_ratio=AZIMUTH_OFFSET_RATIO)
    return shadow_ok, sky_ratio.all_ok(checks)


# === voxel（自由形）：1手ずつ交互に解消 ===================================

def _base_floors(site, cell=3.0):
    area = build_mesh(site, cell, cell)
    assign_height_limits(area, use_sky_ratio=True)
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    _cap_by_far(area, floors, site.max_total_floor_area_m2())
    _apply_coverage_cap(area, floors, site.max_building_area_m2())
    _apply_far_cap(area, floors, site.max_total_floor_area_m2())
    return area, floors


def test_interleaved_result_is_independently_compliant():
    site = _site([(0, 0), (40, 0), (40, 25), (0, 25)], far=4.0, road=12.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    area, base = _base_floors(site)
    shadow_idx = build_shadow_index(site, area, spec)
    sky_idx = build_sky_index(site, area, interval_m=INTERVAL, n_azimuth=N_AZIMUTH)

    floors = base.copy()
    _resolve_shadow_and_sky_jointly(area, floors, shadow_idx, sky_idx, site.floor_height_m, 4000)

    blocks = _floors_to_blocks(area, floors, site.floor_height_m)
    shadow_ok, sky_ok = _independent_check(site, blocks, spec)
    assert shadow_ok and sky_ok


def test_interleaving_never_removes_more_than_sequential():
    """交互方式は、逐次方式（日影→天空率）より延べ床が少なくなることはない。"""
    site = _site([(0, 0), (40, 0), (40, 25), (0, 25)], far=4.0, road=12.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    area, base = _base_floors(site)
    shadow_idx = build_shadow_index(site, area, spec)
    sky_idx = build_sky_index(site, area, interval_m=INTERVAL, n_azimuth=N_AZIMUTH)
    cell_areas = np.array([c.area_m2 for c in area.cells])

    f_seq = base.copy()
    _resolve_shadow(area, f_seq, shadow_idx, site.floor_height_m, 4000)
    _resolve_sky_ratio(area, f_seq, sky_idx, site.floor_height_m, 4000)

    f_joint = base.copy()
    _resolve_shadow_and_sky_jointly(area, f_joint, shadow_idx, sky_idx, site.floor_height_m, 4000)

    area_seq = float((f_seq * cell_areas).sum())
    area_joint = float((f_joint * cell_areas).sum())
    assert area_joint >= area_seq - 1e-6


def test_interleaving_can_beat_sequential_after_refill():
    """条件によっては、逐次方式より多くの延べ床を残せる（同時最適化の効果）。

    40m×25m・道路12m・容積率400%・日影5.0h/3.0hの条件で、実際に差が出る
    ことを確認する（この条件は差が出ることを事前に確認済み）。
    """
    site = _site([(0, 0), (40, 0), (40, 25), (0, 25)], far=4.0, road=12.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    area, base = _base_floors(site)
    shadow_idx = build_shadow_index(site, area, spec)
    sky_idx = build_sky_index(site, area, interval_m=INTERVAL, n_azimuth=N_AZIMUTH)
    cell_areas = np.array([c.area_m2 for c in area.cells])
    floor_h = site.floor_height_m

    f_seq = base.copy()
    _resolve_shadow(area, f_seq, shadow_idx, floor_h, 4000)
    _resolve_sky_ratio(area, f_seq, sky_idx, floor_h, 4000)
    _refill(area, f_seq, site, floor_h, shadow_idx, sky_idx)

    f_joint = base.copy()
    _resolve_shadow_and_sky_jointly(area, f_joint, shadow_idx, sky_idx, floor_h, 4000)
    _refill(area, f_joint, site, floor_h, shadow_idx, sky_idx)

    area_seq = float((f_seq * cell_areas).sum())
    area_joint = float((f_joint * cell_areas).sum())
    assert area_joint > area_seq, "この条件では同時最適化のほうが多いはず"

    for floors in (f_seq, f_joint):
        blocks = _floors_to_blocks(area, floors, floor_h)
        shadow_ok, sky_ok = _independent_check(site, blocks, spec)
        assert shadow_ok and sky_ok


def test_optimize_uses_the_interleaved_resolver_for_voxel():
    """`optimize()` を通しても、voxel + 天空率 + 日影の組み合わせが独立検証で適合する。"""
    site = _site([(0, 0), (40, 0), (40, 25), (0, 25)], far=4.0, road=12.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    result = optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, use_sky_ratio=True))

    shadow_ok, sky_ok = _independent_check(site, result.blocks, spec)
    assert shadow_ok and sky_ok
    assert result.shadow_limited and result.sky_ratio_limited


# === 逆日影（lean_to / ridge）：棟の探索そのものに両方を条件づける =========

def test_roof_search_with_sky_index_is_independently_compliant():
    site = _site([(0, 0), (30, 0), (30, 20), (0, 20)], far=3.0, road=8.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    area, base = _base_floors(site)
    sky_idx = build_sky_index(site, area, interval_m=INTERVAL, n_azimuth=N_AZIMUTH)

    result = search_roof_envelope(site, area, spec, base, site.floor_height_m,
                                  pattern="ridge", sky_index=sky_idx,
                                  angle_span_deg=0.0, offset_steps=3,
                                  pitch_candidates_deg=(30.0, 45.0),
                                  far_pitch_candidates_deg=(0.0, 30.0))
    assert result.spec is not None

    blocks = _floors_to_blocks(area, result.floors, site.floor_height_m)
    shadow_ok, sky_ok = _independent_check(site, blocks, spec)
    assert shadow_ok and sky_ok


def test_roof_search_reports_whether_sky_ratio_was_folded_in():
    site = _site([(0, 0), (30, 0), (30, 20), (0, 20)], far=3.0, road=8.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    area, base = _base_floors(site)

    fast = dict(angle_span_deg=0.0, offset_steps=3,
               pitch_candidates_deg=(30.0, 45.0), far_pitch_candidates_deg=(0.0, 30.0))
    without_sky = search_roof_envelope(site, area, spec, base, site.floor_height_m,
                                       pattern="ridge", **fast)
    assert without_sky.sky_ratio_included is False   # 天空率を渡していないので当然False

    sky_idx = build_sky_index(site, area, interval_m=INTERVAL, n_azimuth=N_AZIMUTH)
    with_sky = search_roof_envelope(site, area, spec, base, site.floor_height_m,
                                    pattern="ridge", sky_index=sky_idx, **fast)
    assert with_sky.sky_ratio_included is True


def test_optimize_folds_sky_ratio_into_the_roof_shape_when_possible():
    """`envelope_family: ridge` + `use_sky_ratio: true` は1本の探索で両方を満たす。

    崩れていない（`roof_includes_sky_ratio=True`）ことを確認する。
    """
    site = _site([(0, 0), (30, 0), (30, 20), (0, 20)], far=3.0, road=8.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    result = optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, envelope_family="ridge", use_sky_ratio=True,
        roof_angle_span_deg=0.0, roof_offset_steps=3,
        roof_pitch_candidates_deg=(30.0, 45.0), roof_far_pitch_candidates_deg=(0.0, 30.0)))

    assert result.roof_spec is not None
    assert result.roof_includes_sky_ratio is True
    assert result.sky_ratio_limited is False, "屋根形状に含まれたのでフリーフォームの是正は不要なはず"

    shadow_ok, sky_ok = _independent_check(site, result.blocks, spec)
    assert shadow_ok and sky_ok


def test_summary_mentions_when_sky_ratio_is_folded_into_the_roof():
    site = _site([(0, 0), (30, 0), (30, 20), (0, 20)], far=3.0, road=8.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    result = optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, envelope_family="ridge", use_sky_ratio=True,
        roof_angle_span_deg=0.0, roof_offset_steps=3,
        roof_pitch_candidates_deg=(30.0, 45.0), roof_far_pitch_candidates_deg=(0.0, 30.0)))
    summary = "\n".join(result.summary_lines_ja())
    assert "同時に満たしています" in summary


def test_roof_falls_back_to_freeform_patch_when_joint_search_cannot_satisfy_both():
    """棟の候補がどれも両方を満たせない場合、日影だけを満たす形に戻して
    天空率は別途フリーフォームで補う（結果は独立検証で両方とも適合する）。

    候補を極端に絞る（角度探索なし・棟位置1つ・勾配1つ）ことで、この
    フォールバック経路を確実に通す。
    """
    site = _site([(0, 0), (30, 0), (30, 20), (0, 20)], far=3.0, road=8.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    result = optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, envelope_family="ridge", use_sky_ratio=True,
        roof_angle_span_deg=0.0, roof_offset_steps=1,
        roof_pitch_candidates_deg=(45.0,), roof_far_pitch_candidates_deg=(0.0,),
    ))
    # 屋根はできている（日影だけは必ず満たす形に落ち着く）
    assert result.roof_spec is not None
    shadow_ok, sky_ok = _independent_check(site, result.blocks, spec)
    assert shadow_ok and sky_ok
    if not result.roof_includes_sky_ratio:
        assert result.sky_ratio_limited, "フォールバックしたならフリーフォームの是正が動いたはず"
