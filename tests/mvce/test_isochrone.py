"""等時間日影図（マーチングスクエア法・グリッド計算）のテスト。"""
import math

import numpy as np
import pytest

from mvce.index.isochrone import (
    _default_grid_margin_m,
    compute_isochrones,
    site_isochrones,
)
from mvce.massing import Block
from mvce.mesh import build_mesh
from mvce.regulations.shadow import ShadowRegulationSpec, _point_in_block_shadow
from mvce.index.shadow_index import grid_shadow_hours
from mvce.site import Site
from mvce.solar import WINTER_SOLSTICE, day_of_year, solar_declination_deg, solar_position_deg
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(**kwargs):
    specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    return Site.from_rings(SQUARE, specs, ZoningParams("1res", 2.0, 0.6), **kwargs)


def _spec(**overrides):
    base = dict(measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
                time_step_minutes=30.0, sample_interval_m=6.0)
    base.update(overrides)
    return ShadowRegulationSpec(**base)


# === compute_isochrones（マーチングスクエア法そのもの） ===================

def test_compute_isochrones_matches_known_circle():
    """原点からの距離 r に対して value = 10 - r という円錐状の合成データ。

    レベル L の等高線は半径 (10-L) の円になるはず。
    """
    n = 41
    xs = np.linspace(-20, 20, n)
    ys = np.linspace(-20, 20, n)
    values = np.zeros((n, n))
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            values[j, i] = max(0.0, 10.0 - math.hypot(x, y))

    result = compute_isochrones(xs, ys, values, [2.0, 5.0, 8.0])
    for level, polylines in result.items():
        assert len(polylines) == 1
        points, closed = polylines[0]
        assert closed
        expected_radius = 10.0 - level
        for p in points:
            assert math.hypot(*p) == pytest.approx(expected_radius, abs=0.05)


def test_compute_isochrones_closed_polyline_for_interior_peak():
    """グリッド全体を覆いきらない山（中心が高い）は閉じた等高線になる。"""
    n = 21
    xs = np.linspace(-10, 10, n)
    ys = np.linspace(-10, 10, n)
    values = np.array([[max(0.0, 5.0 - math.hypot(x, y)) for x in xs] for y in ys])
    result = compute_isochrones(xs, ys, values, [1.0])
    assert len(result[1.0]) == 1
    _points, closed = result[1.0][0]
    assert closed is True


def test_compute_isochrones_open_polyline_when_cut_by_grid_edge():
    """山の裾がグリッドの外まで続く場合は、グリッド境界で切れた開いた線になる。"""
    n = 11
    xs = np.linspace(0, 10, n)   # 山の中心(0,0)はグリッドの外
    ys = np.linspace(0, 10, n)
    values = np.array([[max(0.0, 8.0 - math.hypot(x, y)) for x in xs] for y in ys])
    result = compute_isochrones(xs, ys, values, [3.0])
    assert len(result[3.0]) >= 1
    assert any(not closed for _points, closed in result[3.0])


def test_compute_isochrones_empty_level_returns_empty_list():
    n = 11
    xs = np.linspace(0, 10, n)
    ys = np.linspace(0, 10, n)
    values = np.full((n, n), 1.0)
    result = compute_isochrones(xs, ys, values, [99.0])
    assert result[99.0] == []


def test_compute_isochrones_handles_saddle_case_without_crashing():
    """対角の角だけが高い（鞍点）ケースでも例外にならず、線分数が偶数本になる。"""
    xs = np.array([0.0, 1.0])
    ys = np.array([0.0, 1.0])
    values = np.array([[10.0, 0.0], [0.0, 10.0]])  # BL,TR が高い・BR,TLが低い
    result = compute_isochrones(xs, ys, values, [5.0])
    assert len(result[5.0]) == 2  # 2本の線分（つながらない2つの角の切り取り）


# === grid_shadow_hours（任意点での日影時間） ============================

def _ground_truth_hours(site, blocks, spec, points):
    """`compute_shadow_hours` と同じロジックを任意の点集合向けに書いたもの。"""
    declination = solar_declination_deg(day_of_year(*WINTER_SOLSTICE))
    step = spec.time_step_minutes / 60.0
    out = []
    for point in points:
        total = 0.0
        for hour in spec.true_solar_hours():
            altitude, azimuth = solar_position_deg(spec.latitude_deg, declination, hour)
            if altitude <= 0:
                continue
            if any(_point_in_block_shadow(point, block, altitude, azimuth,
                                          spec.measurement_height_m, site)
                   for block in blocks):
                total += step
        out.append(total)
    return out


def test_grid_shadow_hours_matches_block_based_ground_truth():
    """建物内部の点も含め、独立実装（shapely）と一致することを確認する。"""
    site = _site()
    spec = _spec(time_step_minutes=60.0, sample_interval_m=8.0)
    area = build_mesh(site, cell_size_x_m=6.0, cell_size_y_m=6.0)
    assert area is not None and area.cells

    floors = np.full(len(area.cells), 3)
    heights = floors * site.floor_height_m
    blocks = [Block(footprint=c.polygon, z_bottom=0.0, z_top=float(h))
              for c, h in zip(area.cells, heights)]

    # 敷地内・建物直下・敷地外の点を混ぜる（建物直下＝マスク処理をしない設計の裏付け）
    inside_building = area.cells[0].center
    points = [inside_building, (15.0, 10.0), (2.0, 2.0), (40.0, 10.0), (-5.0, -5.0)]

    expected = _ground_truth_hours(site, blocks, spec, points)
    got = grid_shadow_hours(site, area, floors, spec, points)
    for e, g in zip(expected, got):
        assert g == pytest.approx(e, abs=spec.time_step_minutes / 60.0 + 1e-9)


def test_grid_shadow_hours_with_no_cells_returns_zeros():
    site = _site()
    spec = _spec()
    area = build_mesh(site, cell_size_x_m=6.0, cell_size_y_m=6.0)
    floors = np.zeros(len(area.cells))
    got = grid_shadow_hours(site, area, floors, spec, [(15.0, 10.0), (5.0, 5.0)])
    assert list(got) == [0.0, 0.0]


# === site_isochrones（エンドツーエンド） =================================

def test_site_isochrones_end_to_end():
    site = _site()
    spec = _spec()
    area = build_mesh(site, cell_size_x_m=5.0, cell_size_y_m=5.0)
    floors = np.full(len(area.cells), 4)

    result = site_isochrones(site, area, floors, spec, [1.0, 2.0],
                             interval_m=3.0, margin_m=15.0)
    assert set(result.keys()) == {1.0, 2.0}
    # 建物が建っているので、少なくともどれかのレベルで等高線が出るはず
    assert any(result[level] for level in result)


def test_site_isochrones_empty_levels_returns_empty_dict():
    site = _site()
    spec = _spec()
    area = build_mesh(site, cell_size_x_m=5.0, cell_size_y_m=5.0)
    floors = np.full(len(area.cells), 4)
    assert site_isochrones(site, area, floors, spec, []) == {}


def test_site_isochrones_no_area_returns_empty_lists():
    site = _site()
    spec = _spec()
    result = site_isochrones(site, None, np.array([]), spec, [1.0, 2.0])
    assert result == {1.0: [], 2.0: []}


# === グリッド余白の自動計算 ===============================================

def test_default_grid_margin_scales_with_building_height():
    spec = _spec()
    low = _default_grid_margin_m(spec, 10.0)
    high = _default_grid_margin_m(spec, 30.0)
    assert high > low > 0


def test_default_grid_margin_zero_for_building_below_measurement_plane():
    spec = _spec()
    assert _default_grid_margin_m(spec, spec.measurement_height_m - 0.1) > 0  # フォールバック値


# === 設定 =================================================================

def test_isochrone_hours_must_be_positive():
    with pytest.raises(ValueError, match="isochrone_hours"):
        ShadowRegulationSpec(measurement_height_m=4.0, line_5m_max_hours=5.0,
                             line_10m_max_hours=3.0, isochrone_hours=[0.0])


def test_isochrone_grid_interval_must_be_positive():
    with pytest.raises(ValueError, match="isochrone_grid_interval_m"):
        ShadowRegulationSpec(measurement_height_m=4.0, line_5m_max_hours=5.0,
                             line_10m_max_hours=3.0, isochrone_grid_interval_m=0.0)


def test_isochrone_hours_option_parses_in_config(tmp_path):
    from mvce.config import load_project

    config = tmp_path / "p.yaml"
    config.write_text("""
site:
  points: [[0, 0], [30, 0], [30, 20], [0, 20]]
  edges:
    - {kind: road, road_width_m: 6.0}
    - {kind: adjacent}
    - {kind: adjacent}
    - {kind: adjacent}
  zoning: {zone_type: 1res, far_ratio: 200, coverage_ratio: 60}
shadow:
  measurement_height_m: 4.0
  line_5m_max_hours: 5.0
  line_10m_max_hours: 3.0
  isochrone_hours: [1.0, 2.0, 3.0]
  isochrone_grid_interval_m: 3.0
""", encoding="utf-8")
    project = load_project(str(config))
    assert project.shadow.isochrone_hours == [1.0, 2.0, 3.0]
    assert project.shadow.isochrone_grid_interval_m == 3.0
    assert project.shadow.isochrone_margin_m is None
