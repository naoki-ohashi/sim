"""日影規制（法56条の2、令135条の12）のテスト。"""
import math

import pytest
from shapely.geometry import Polygon

from mvce.massing import Block
from mvce.mesh import build_mesh
from mvce.regulations.shadow import (
    ShadowRegulationSpec,
    compute_shadow_hours,
    deemed_boundary_offsets,
    measurement_points,
    regulation_boundary,
)
from mvce.index.shadow_index import build_shadow_index
from mvce.site import Site
from mvce.solar import solar_position_deg, winter_solstice_declination_deg
from mvce.zoning import ZoningParams

import numpy as np

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(specs=None, zone="1res"):
    if specs is None:
        specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
                 {"kind": "adjacent"}, {"kind": "adjacent"}]
    return Site.from_rings(SQUARE, specs, ZoningParams(zone, 2.0, 0.6))


def _spec(**kwargs):
    base = dict(measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
                time_step_minutes=30.0, sample_interval_m=5.0)
    base.update(kwargs)
    return ShadowRegulationSpec(**base)


# === 仕様の検証 =======================================================

def test_measurement_height_must_be_a_statutory_value():
    with pytest.raises(ValueError, match="1.5m / 4m / 6.5m"):
        _spec(measurement_height_m=3.0)


def test_all_three_measurement_planes_are_accepted():
    for height in (1.5, 4.0, 6.5):
        assert _spec(measurement_height_m=height).measurement_height_m == height


def test_outer_line_hours_must_not_exceed_inner():
    with pytest.raises(ValueError, match="別表第四"):
        _spec(line_5m_max_hours=3.0, line_10m_max_hours=5.0)


def test_hokkaido_uses_nine_to_fifteen():
    assert _spec(hokkaido=True).hours_range == (9.0, 15.0)
    assert _spec().hours_range == (8.0, 16.0)


def test_true_solar_hours_cover_the_measurement_window():
    hours = _spec(time_step_minutes=60.0).true_solar_hours()
    assert hours == [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]


# === みなし境界線（令135条の12第3項）=================================

def test_deemed_boundary_half_width_for_narrow_road():
    site = _site()  # 6m 道路
    assert deemed_boundary_offsets(site)[0] == pytest.approx(3.0)


def test_deemed_boundary_five_metres_inside_for_wide_road():
    """幅10m超は「反対側境界線から敷地側5m」なので、外側への移動は W-5。"""
    specs = [{"kind": "road", "road_width_m": 16.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    assert deemed_boundary_offsets(_site(specs))[0] == pytest.approx(11.0)


def test_deemed_boundary_exactly_ten_metres_uses_half():
    specs = [{"kind": "road", "road_width_m": 10.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    assert deemed_boundary_offsets(_site(specs))[0] == pytest.approx(5.0)


def test_deemed_boundary_applies_to_water_and_railway():
    specs = [{"kind": "road", "road_width_m": 6.0},
             {"kind": "adjacent", "relaxation": {"kind": "water", "width_m": 8.0}},
             {"kind": "adjacent", "relaxation": {"kind": "railway", "width_m": 20.0}},
             {"kind": "adjacent"}]
    offsets = deemed_boundary_offsets(_site(specs))
    assert offsets[1] == pytest.approx(4.0)    # 8m の 1/2
    assert offsets[2] == pytest.approx(15.0)   # 20m 超なので 20-5


def test_regulation_boundary_moves_outward_on_the_road_side():
    site = _site()
    ring = regulation_boundary(site, _spec())
    assert min(p[1] for p in ring) == pytest.approx(-3.0)


def test_deemed_boundary_can_be_switched_off():
    site = _site()
    ring = regulation_boundary(site, _spec(apply_deemed_boundary=False))
    assert min(p[1] for p in ring) == pytest.approx(0.0)


def test_measurement_points_sit_on_the_offset_line():
    site = _site()
    spec = _spec()
    pts5 = measurement_points(site, spec, 5.0)
    pts10 = measurement_points(site, spec, 10.0)
    # 道路側は みなし境界(-3) からさらに5m/10m 外
    assert min(p[1] for p in pts5) == pytest.approx(-8.0, abs=1e-6)
    assert min(p[1] for p in pts10) == pytest.approx(-13.0, abs=1e-6)


# === 日影時間の計算 ===================================================

def test_no_building_casts_no_shadow():
    lines = compute_shadow_hours(_site(), [], _spec())
    assert all(line.worst_hours == 0.0 for line in lines)
    assert all(line.ok for line in lines)


def test_building_below_measurement_plane_casts_no_shadow():
    """測定面より低い部分は日影を生じない（令135条の12）。"""
    site = _site()
    block = Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=3.5)
    lines = compute_shadow_hours(site, [block], _spec(measurement_height_m=4.0))
    assert all(line.worst_hours == 0.0 for line in lines)


def _total_shadow_hours(site, blocks, spec):
    """全測定点の日影時間の合計。

    最も長い点だけを見ると、敷地いっぱいの建物では測定時間帯（8時間）に
    張り付いて差が出ないため、影響範囲まで含む合計で比べる。
    """
    return sum(h for line in compute_shadow_hours(site, blocks, spec)
               for _p, h in line.point_hours)


def test_taller_building_casts_longer_shadow():
    site = _site()
    low = [Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=10.0)]
    high = [Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=30.0)]
    assert _total_shadow_hours(site, high, _spec()) > _total_shadow_hours(site, low, _spec())


def test_measurement_plane_height_changes_the_result():
    """測定面が高いほど日影は短くなる。"""
    site = _site()
    blocks = [Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=20.0)]
    low = _total_shadow_hours(site, blocks, _spec(measurement_height_m=1.5))
    high = _total_shadow_hours(site, blocks, _spec(measurement_height_m=6.5))
    assert high < low


def test_shadow_falls_north_at_winter_solstice():
    site = _site()
    blocks = [Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=25.0)]
    lines = compute_shadow_hours(site, blocks, _spec())
    north = [h for (x, y), h in lines[0].point_hours if y > 20]
    south = [h for (x, y), h in lines[0].point_hours if y < 0]
    assert max(north) > max(south)


def test_shadow_follows_true_north_when_rotated():
    """真北を90度回すと、日影が伸びる向きも図面上で90度回る。"""
    from mvce.north import NorthReference
    specs = [{"kind": "adjacent"}] * 4
    blocks = [Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=25.0)]

    default = Site.from_rings(SQUARE, specs, ZoningParams("1res", 2.0, 0.6))
    rotated = Site.from_rings(SQUARE, specs, ZoningParams("1res", 2.0, 0.6),
                              north=NorthReference(north_angle_deg=90.0))

    d_lines = compute_shadow_hours(default, blocks, _spec())
    r_lines = compute_shadow_hours(rotated, blocks, _spec())
    # 既定は図面の上(+Y)側、90度回すと図面の左(-X)側が最も日影になる
    d_worst = max(d_lines[0].point_hours, key=lambda ph: ph[1])[0]
    r_worst = max(r_lines[0].point_hours, key=lambda ph: ph[1])[0]
    assert d_worst[1] > 20
    assert r_worst[0] < 0


# === しきい値インデックスと直接計算の一致 =============================

def test_shadow_index_agrees_with_direct_computation():
    """しきい値方式（最適化で使う）と直接計算が同じ答えになるか。

    最適化は shadow_index の比較だけで日影を判定するので、直接の
    影計算と食い違っていると最適化結果が信用できなくなる。
    """
    site = _site()
    spec = _spec(time_step_minutes=30.0, sample_interval_m=6.0)
    area = build_mesh(site, cell_size_x_m=5.0, cell_size_y_m=5.0)
    assert area is not None and area.cells

    index = build_shadow_index(site, area, spec)

    # 全マスを一律15mにした建物で比較する
    heights = np.full(len(area.cells), 15.0)
    blocks = [Block(footprint=c.polygon, z_bottom=0.0, z_top=15.0) for c in area.cells]
    direct = compute_shadow_hours(site, blocks, spec)

    for line in direct:
        for i, (_point, hours) in enumerate(line.point_hours):
            indexed = index.hours_at(line.distance_m, i, heights)
            assert indexed == pytest.approx(hours, abs=spec.time_step_minutes / 60.0 + 1e-9)


def test_shadow_index_threshold_is_monotonic_in_height():
    """高さを上げると日影時間は減らない（しきい値方式の前提）。"""
    site = _site()
    spec = _spec(time_step_minutes=60.0, sample_interval_m=8.0)
    area = build_mesh(site, cell_size_x_m=6.0, cell_size_y_m=6.0)
    index = build_shadow_index(site, area, spec)

    previous = -1.0
    for height in (0.0, 5.0, 10.0, 20.0, 40.0):
        hours = index.hours_at(10.0, 0, np.full(len(area.cells), height))
        assert hours >= previous - 1e-9
        previous = hours
