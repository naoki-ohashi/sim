"""ボクセル最適化（敷地→壁面後退線→外郭線→メッシュ→階数）のテスト。"""
import numpy as np
import pytest

from mve.mesh import assign_height_limits, build_mesh, building_outline, wall_setback_ring
from mve.optimizer import OptimizeOptions, optimize
from mve.regulations.shadow import ShadowRegulationSpec
from mve.site import Site
from mve.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]

FAST_SHADOW = dict(time_step_minutes=30.0, sample_interval_m=6.0)


def _site(setback=0.0, far=2.0, coverage=0.6, zone="1res", road_width=6.0):
    specs = [
        {"kind": "road", "road_width_m": road_width, "wall_setback_m": setback},
        {"kind": "adjacent", "wall_setback_m": setback},
        {"kind": "adjacent", "wall_setback_m": setback},
        {"kind": "adjacent", "wall_setback_m": setback},
    ]
    return Site.from_rings(SQUARE, specs, ZoningParams(zone, far, coverage))


def _spec(**kwargs):
    base = dict(measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    base.update(FAST_SHADOW)
    base.update(kwargs)
    return ShadowRegulationSpec(**base)


# === 壁面後退線と建物外郭線 ===========================================

def test_wall_setback_ring_shrinks_the_site():
    ring = wall_setback_ring(_site(setback=2.0))
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    assert min(xs) == pytest.approx(2.0)
    assert max(xs) == pytest.approx(28.0)
    assert min(ys) == pytest.approx(2.0)
    assert max(ys) == pytest.approx(18.0)


def test_no_setback_keeps_the_site_outline():
    assert building_outline(_site(setback=0.0)).area == pytest.approx(600.0)


def test_setback_reduces_the_outline_area():
    assert building_outline(_site(setback=2.0)).area == pytest.approx(26 * 16)


def test_excessive_setback_leaves_no_outline():
    assert building_outline(_site(setback=15.0)) is None


# === メッシュ =========================================================

def test_mesh_cell_size_is_respected():
    area = build_mesh(_site(), cell_size_x_m=5.0, cell_size_y_m=4.0)
    assert area.cell_size_x_m == 5.0 and area.cell_size_y_m == 4.0
    # 30x20 を 5x4 で刻むとちょうど 6x5 = 30 マス
    assert len(area.cells) == 30
    assert all(c.area_m2 == pytest.approx(20.0) for c in area.cells)


def test_mesh_covers_the_outline_area():
    area = build_mesh(_site(), cell_size_x_m=2.0, cell_size_y_m=2.0)
    covered = sum(c.area_m2 for c in area.cells)
    assert covered == pytest.approx(area.outline_area_m2, rel=0.02)


def test_mesh_rejects_too_small_cells():
    with pytest.raises(ValueError, match="0.5m以上"):
        build_mesh(_site(), cell_size_x_m=0.1, cell_size_y_m=0.1)


def test_mesh_returns_none_when_no_outline():
    assert build_mesh(_site(setback=15.0)) is None


def test_height_limits_decrease_towards_the_road():
    """道路斜線があるので、道路に近いマスほど積める階数が少ない。"""
    area = build_mesh(_site(), cell_size_x_m=5.0, cell_size_y_m=5.0)
    assign_height_limits(area)
    near = min(c.max_floors for c in area.cells if c.center[1] < 5)
    far = max(c.max_floors for c in area.cells if c.center[1] > 15)
    assert near < far


def test_rotated_mesh_still_covers_the_outline():
    area = build_mesh(_site(), cell_size_x_m=3.0, cell_size_y_m=3.0, angle_deg=30.0)
    assert area.cells
    covered = sum(c.area_m2 for c in area.cells)
    assert covered == pytest.approx(area.outline_area_m2, rel=0.15)


# === 最適化 ===========================================================

def test_optimize_without_shadow_reaches_the_far_cap():
    result = optimize(_site(), None, OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))
    assert result.blocks
    assert result.total_floor_area_m2 <= result.site.max_total_floor_area_m2() + 1e-6
    assert result.far_attainment > 0.95


def test_coverage_cap_limits_building_area():
    result = optimize(_site(coverage=0.4), None,
                      OptimizeOptions(cell_size_x_m=2.0, cell_size_y_m=2.0))
    assert result.coverage_limited
    assert result.building_area_m2 <= result.site.max_building_area_m2() + 1e-6


def test_far_cap_limits_floor_area():
    result = optimize(_site(far=1.0), None,
                      OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))
    assert result.far_limited
    assert result.total_floor_area_m2 <= result.site.max_total_floor_area_m2() + 1e-6


def test_shadow_regulation_is_satisfied():
    result = optimize(_site(), _spec(), OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))
    assert result.shadow_ok
    for line in result.shadow_lines:
        assert line.worst_hours <= line.max_hours + 1e-6


def test_shadow_lowers_only_the_cells_that_cause_it():
    """一律に低くするのではなく、日影に効くマスだけが下がること。

    旧方式（全体を一律縮小）では全マスが同じ高さになるが、ボクセル法では
    高さに差が残るのが正しい。
    """
    result = optimize(_site(far=10.0), _spec(line_5m_max_hours=3.0, line_10m_max_hours=2.0),
                      OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))
    assert result.shadow_limited
    used = result.floors[result.floors > 0]
    assert used.size > 0
    assert used.max() > used.min(), "全マスが同じ階数＝一律縮小になっている"


def test_strict_shadow_limits_reduce_volume():
    lenient = optimize(_site(far=10.0), _spec(line_5m_max_hours=8.0, line_10m_max_hours=8.0),
                       OptimizeOptions(cell_size_x_m=4.0, cell_size_y_m=4.0))
    strict = optimize(_site(far=10.0), _spec(line_5m_max_hours=2.0, line_10m_max_hours=1.0),
                      OptimizeOptions(cell_size_x_m=4.0, cell_size_y_m=4.0))
    assert strict.volume_m3 < lenient.volume_m3
    assert strict.shadow_ok


def test_voxel_beats_uniform_scaling_on_floor_area():
    """同じ条件で、一律縮小より多くの延床が取れること。

    一律縮小は「全マスを同じ高さまで下げる」方式。これを再現して比べる。
    """
    site = _site(far=2.0)
    spec = _spec()
    result = optimize(site, spec, OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))

    # 一律縮小の再現: 全マスを同じ階数にして、適合する最大の階数を探す。
    # 建蔽率は旧方式でも守る必要があるので、同じ条件を課してから比べる。
    from mve.mesh import build_mesh as _build
    from mve.optimizer import _apply_coverage_cap
    from mve.shadow_index import build_shadow_index
    area = _build(site, cell_size_x_m=3.0, cell_size_y_m=3.0)
    assign_height_limits(area)
    index = build_shadow_index(site, area, spec)
    cell_areas = np.array([c.area_m2 for c in area.cells])
    caps = np.array([c.max_floors for c in area.cells])
    _apply_coverage_cap(area, caps, site.max_building_area_m2())

    best_uniform = 0.0
    for level in range(1, int(caps.max()) + 1):
        floors = np.minimum(caps, level)
        floor_area = float((floors * cell_areas).sum())
        if floor_area > site.max_total_floor_area_m2() + 1e-9:
            break
        if index.is_compliant(floors * site.floor_height_m):
            best_uniform = floor_area

    assert result.total_floor_area_m2 > best_uniform


def test_result_reports_which_regulations_bind():
    result = optimize(_site(), _spec(), OptimizeOptions(cell_size_x_m=4.0, cell_size_y_m=4.0))
    summary = "\n".join(result.summary_lines_ja())
    assert "敷地面積" in summary
    assert "達成容積率" in summary
    assert "上限に達した規制" in summary


def test_impossible_setback_returns_empty_result_with_note():
    result = optimize(_site(setback=15.0), None)
    assert result.blocks == []
    assert any("建物外郭線" in n for n in result.notes)


def test_blocks_are_grouped_by_floor():
    result = optimize(_site(far=1.0), None, OptimizeOptions(cell_size_x_m=5.0, cell_size_y_m=5.0))
    floor_h = result.site.floor_height_m
    for block in result.blocks:
        assert block.height == pytest.approx(floor_h)
        assert (block.z_bottom / floor_h) == pytest.approx(round(block.z_bottom / floor_h))


# === 逆日影パターン（envelope_family）との接続 ============================

def test_rejects_unknown_envelope_family():
    with pytest.raises(ValueError):
        optimize(_site(), _spec(), OptimizeOptions(envelope_family="hip"))


def test_roof_pattern_result_is_independently_compliant():
    from mve.regulations.shadow import compute_shadow_hours

    site = _site(far=3.0, road_width=8.0)
    spec = _spec(line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    result = optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, envelope_family="ridge"))

    assert result.roof_spec is not None
    lines = compute_shadow_hours(site, result.blocks, spec)
    assert all(line.ok for line in lines)


def test_roof_pattern_summary_names_the_shape():
    site = _site(far=3.0, road_width=8.0)
    spec = _spec()
    result = optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, envelope_family="lean_to"))
    summary = "\n".join(result.summary_lines_ja())
    assert "逆日影" in summary
    assert "屋根越し" in summary


def test_voxel_family_never_sets_roof_spec():
    result = optimize(_site(far=2.0), _spec(), OptimizeOptions(cell_size_x_m=4.0, cell_size_y_m=4.0))
    assert result.roof_spec is None


def test_roof_family_never_exceeds_voxel_floor_area():
    """屋根形状（規則正しい後退）は、自由形（ボクセル）より容積が大きくなることはない。"""
    site = _site(far=3.0, road_width=8.0)
    spec = _spec()
    voxel = optimize(site, spec, OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))
    ridge = optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, envelope_family="ridge"))
    assert ridge.total_floor_area_m2 <= voxel.total_floor_area_m2 + 1e-6
