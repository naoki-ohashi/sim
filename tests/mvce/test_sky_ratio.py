"""天空率（法56条7項）がボクセル最適化に接続されていることの検証.

`use_sky_ratio: true` は「斜線制限を外す」だけでなく、**Ps ≧ Pr を実際に
確認して満たすまで下げる**ところまでを行います。ここではその適合性を、
インデックスとは独立した `sky_ratio.check()` で検証します。
"""
import numpy as np
import pytest

from mvce.mesh import assign_height_limits, build_mesh
from mvce.solvers.optimizer import OptimizeOptions, _floors_to_blocks, optimize
from mvce.regulations import sky_ratio
from mvce.site import Site
from mvce.index.sky_index import AZIMUTH_OFFSET_RATIO, build_sky_index, summarize
from mvce.zoning import ZoningParams

CELL = 3.0
N_AZIMUTH = 72


def _site(setback=0.0, far=2.0, zone="1res", road=6.0, coverage=0.6, height=None):
    zoning = ZoningParams(zone_type=zone, far_ratio=far, coverage_ratio=coverage,
                          absolute_height_limit_m=height)
    specs = [
        {"kind": "road", "road_width_m": road, "wall_setback_m": setback},
        {"kind": "adjacent", "wall_setback_m": setback},
        {"kind": "adjacent", "wall_setback_m": setback},
        {"kind": "adjacent", "wall_setback_m": setback},
    ]
    return Site.from_rings([(0, 0), (30, 0), (30, 20), (0, 20)], specs, zoning)


def _options(**kwargs):
    base = dict(cell_size_x_m=CELL, cell_size_y_m=CELL,
                sky_ratio_n_azimuth=N_AZIMUTH)
    base.update(kwargs)
    return OptimizeOptions(**base)


def _independent_check(site, blocks):
    """インデックスを使わず、shapely 版で Ps ≧ Pr を確かめ直す。"""
    return sky_ratio.check(site, blocks, n_azimuth=N_AZIMUTH,
                           azimuth_offset_ratio=AZIMUTH_OFFSET_RATIO)


# === インデックスの正しさ ============================================

@pytest.mark.parametrize("cell", [2.0, 3.0, 4.0])
def test_index_matches_the_polygon_based_calculation(cell):
    """マス単位のインデックスが、階ごとに結合したブロックの天空率と一致する。

    これが成り立つので、インデックスで最適化しても結果は本来の定義と同じです。
    """
    site = _site()
    area = build_mesh(site, cell_size_x_m=cell, cell_size_y_m=cell)
    assign_height_limits(area)
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    heights = floors * site.floor_height_m
    blocks = _floors_to_blocks(area, floors, site.floor_height_m)

    index = build_sky_index(site, area, n_azimuth=N_AZIMUTH)
    for i, point in enumerate(index.points):
        expected = sky_ratio.sky_ratio_percent(
            (point[0], point[1], 0.0), blocks, N_AZIMUTH, AZIMUTH_OFFSET_RATIO)
        assert index.ps_at(i, heights) == pytest.approx(expected, abs=1e-9)


def test_lowering_a_cell_never_decreases_sky_ratio():
    """マスを下げれば天空率は必ず上がる（または変わらない）。

    解消アルゴリズムはこの単調性に依存しています。
    """
    site = _site()
    area = build_mesh(site, cell_size_x_m=CELL, cell_size_y_m=CELL)
    assign_height_limits(area)
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    heights = floors * site.floor_height_m
    index = build_sky_index(site, area, n_azimuth=N_AZIMUTH)

    before = index.ps(heights)
    for ci in range(0, len(area.cells), 7):
        trial = heights.copy()
        trial[ci] = max(0.0, trial[ci] - site.floor_height_m)
        assert (index.ps(trial) >= before - 1e-9).all()


def test_only_ridge_cells_affect_a_measurement_point():
    """稜線を作っていないマスを下げても、その測定点の天空率は変わらない。

    これが「原因となるマスだけを下げる」ことの根拠です。
    """
    site = _site()
    area = build_mesh(site, cell_size_x_m=CELL, cell_size_y_m=CELL)
    assign_height_limits(area)
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    heights = floors * site.floor_height_m
    index = build_sky_index(site, area, n_azimuth=N_AZIMUTH)

    point_index = 0
    ridge = set(index.ridge_cells(point_index, heights))
    others = [i for i in range(len(area.cells)) if i not in ridge and floors[i] > 0]
    assert ridge and others, "稜線のマスと、そうでないマスが両方あること"

    base = index.ps_at(point_index, heights)
    for ci in others[:10]:
        trial = heights.copy()
        trial[ci] -= site.floor_height_m
        assert index.ps_at(point_index, trial) == pytest.approx(base, abs=1e-9)


# === 最適化への接続 ==================================================

def test_result_is_verified_compliant_by_an_independent_check():
    """`use_sky_ratio` の結果が、独立した計算でも Ps ≧ Pr を満たす。"""
    site = _site(setback=0.0, far=3.0, road=8.0)
    result = optimize(site, None, _options(use_sky_ratio=True))

    assert result.sky_ratio is not None, "天空率の判定結果が残っていること"
    assert result.sky_ratio_ok
    checks = _independent_check(site, result.blocks)
    assert sky_ratio.all_ok(checks), \
        f"最小余裕 {min(c.margin for c in checks):+.3f}%"


def test_index_margin_is_never_more_optimistic_than_the_independent_check():
    """インデックスの余裕は、多角形版の余裕を上回らない。

    **これが「インデックスが適合と言えば本当に適合」を支える性質です。**
    以前は両者が厳密に一致していましたが、令135条の6第1項1号の
    「適用範囲内の部分に限る」で計画建築物を切るようになって差が出ます。

    - 多角形版はブロックの平面形状を範囲で**正確に**切る
    - インデックスはマスの単位でしか切れないので、範囲に一部でもかかった
      マスは丸ごと残す（多めに残す＝空を塞ぐ側＝Ps が小さい）

    したがってインデックスのほうが常に厳しく出ます。逆向きになったら、
    最適化が「適合」と言った結果が実際には不適合になりうるということです。
    """
    site = _site(setback=3.0, far=3.0, road=8.0)
    result = optimize(site, None, _options(use_sky_ratio=True))
    checks = _independent_check(site, result.blocks)
    index_margin = result.sky_ratio.worst_margin
    polygon_margin = min(c.margin for c in checks)
    assert index_margin <= polygon_margin + 1e-9, (
        f"インデックス {index_margin:+.4f}% が多角形版 {polygon_margin:+.4f}% より"
        "甘く出ています（この向きが崩れると最適化結果を信用できません）"
    )
    assert polygon_margin >= 0.0


def test_not_used_means_no_sky_ratio_judgement():
    """斜線制限を守っている場合は天空率の判定を行わない（不要なため）。"""
    result = optimize(_site(), None, _options(use_sky_ratio=False))
    assert result.sky_ratio is None
    assert result.sky_ratio_ok is True
    assert result.sky_ratio_limited is False
    assert "天空率" not in "\n".join(result.summary_lines_ja())


def test_sky_ratio_can_unlock_more_floor_area_than_slant_lines():
    """壁面後退を取った敷地では、天空率の方が多くの延床を取れる。

    これが法56条7項を使う目的そのものです。
    """
    site_kwargs = dict(setback=5.0, far=6.0, zone="commercial", road=20.0)
    slant = optimize(_site(**site_kwargs), None, _options(use_sky_ratio=False))
    sky = optimize(_site(**site_kwargs), None, _options(use_sky_ratio=True))

    assert sky.total_floor_area_m2 > slant.total_floor_area_m2
    assert sky.sky_ratio_ok
    assert sky_ratio.all_ok(_independent_check(_site(**site_kwargs), sky.blocks))


def test_binding_regulation_is_reported():
    """天空率で削った場合、サマリーにそう出る。"""
    site = _site(setback=0.0, far=6.0, zone="commercial", road=20.0)
    result = optimize(site, None, _options(use_sky_ratio=True))
    summary = "\n".join(result.summary_lines_ja())

    assert "天空率（法56条7項" in summary
    assert "Ps" in summary and "Pr" in summary
    if result.sky_ratio_limited:
        assert "天空率で削った体積" in summary
        assert result.volume_removed_by_sky_ratio_m3 > 0


def test_absolute_height_limit_still_applies_under_sky_ratio():
    """天空率でも法55条の絶対高さ制限は外せない。"""
    site = _site(zone="1low", far=1.0, height=10.0)
    result = optimize(site, None, _options(use_sky_ratio=True))
    assert result.max_height_m <= 10.0 + 1e-9


def test_unbounded_height_is_capped_before_the_search():
    """高さ上限が無限でも、容積率から決まる階数で頭が抑えられる。

    抑えないと削り込みの回数が現実的でなくなります。
    """
    site = _site(zone="commercial", far=6.0, road=20.0)
    result = optimize(site, None, _options(use_sky_ratio=True))
    cap = site.max_total_floor_area_m2() / min(c.area_m2 for c in result.area.cells)
    assert result.floors.max() <= cap + 1


def test_shadow_and_sky_ratio_are_both_satisfied():
    """日影と天空率を同時に課しても、両方を満たすこと。"""
    from mvce.regulations.shadow import ShadowRegulationSpec

    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    site = _site(setback=2.0, far=3.0, road=8.0)
    result = optimize(site, spec, _options(use_sky_ratio=True))

    assert result.shadow_ok, "日影が不適合"
    assert result.sky_ratio_ok, "天空率が不適合"
    assert sky_ratio.all_ok(_independent_check(site, result.blocks))


def test_summary_helper_agrees_with_the_index():
    site = _site()
    area = build_mesh(site, cell_size_x_m=CELL, cell_size_y_m=CELL)
    assign_height_limits(area)
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    heights = floors * site.floor_height_m
    index = build_sky_index(site, area, n_azimuth=N_AZIMUTH)

    s = summarize(index, heights)
    assert s.n_points == len(index.points)
    assert s.worst_margin == pytest.approx(
        min(index.ps_at(i, heights) - index.pr[i] for i in range(len(index.points))))
    assert s.ok is index.is_compliant(heights)
