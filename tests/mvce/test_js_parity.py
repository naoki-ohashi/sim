"""JavaScript版のMVEエンジンがPython版と同じ答えを出すことの検証。

Web版UI（web/mvce/）はPython版の移植なので、両方が同じ入力で同じ結果に
なっていないと信用できません。実際にNode.jsでJS版を走らせて突き合わせます。
"""
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from mvce.far import compute_far
from mvce.index.isochrone import _default_grid_margin_m, site_isochrones
from mvce.mesh import assign_height_limits, build_mesh
from mvce.north import NorthReference
from mvce.solvers.optimizer import OptimizeOptions, optimize
from mvce.regulations import road_slant
from mvce.regulations.height_field import height_limit_at, required_setback_for_height
from mvce.regulations.shadow import ShadowRegulationSpec, deemed_boundary_offsets
from mvce.regulations.sky_ratio import (
    azimuths_deg,
    measurement_points,
    reference_building,
    sky_ratio_percent,
)
from mvce.index.shadow_index import grid_shadow_hours
from mvce.site import Site
from mvce.solar import day_of_year, solar_declination_deg, solar_position_deg
from mvce.zoning import ZoningParams

RUNNER = Path(__file__).parent / "js_runner.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js が無い環境ではスキップ")

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(specs=None, zone="1res", far=2.0, coverage=0.6, north=0.0, setback=0.0):
    if specs is None:
        specs = [
            {"kind": "road", "road_width_m": 6.0, "wall_setback_m": setback},
            {"kind": "adjacent", "wall_setback_m": setback},
            {"kind": "adjacent", "wall_setback_m": setback},
            {"kind": "adjacent", "wall_setback_m": setback},
        ]
    return Site.from_rings(
        SQUARE, specs, ZoningParams(zone, far, coverage),
        north=NorthReference(north_angle_deg=north))


def _js_site(site):
    return {
        "points": [list(p) for p in site.points],
        "edges": [
            {
                "p1": list(e.p1), "p2": list(e.p2), "kind": e.kind.value,
                "roadWidthM": e.road_width_m, "wallSetbackM": e.wall_setback_m,
                "groundLevelDiffM": e.ground_level_diff_m,
                "relaxation": {"kind": e.relaxation.kind.value, "widthM": e.relaxation.width_m},
            }
            for e in site.edges
        ],
        "zoning": {
            "zoneType": site.zoning.zone_type, "farRatio": site.zoning.far_ratio,
            "coverageRatio": site.zoning.coverage_ratio,
            "absoluteHeightLimitM": site.zoning.absolute_height_limit_m,
            "unspecifiedRoadSlantSlope": site.zoning.unspecified_road_slant_slope,
            "unspecifiedAdjacentSlantSlope": site.zoning.unspecified_adjacent_slant_slope,
            "adjacentSlant25Designated": site.zoning.adjacent_slant_2_5_designated,
        },
        "northAngleDeg": site.north.north_angle_deg,
        "floorHeightM": site.floor_height_m,
        "applyArticle1342": site.apply_article_134_2,
        "railwayIsAdjacentRelaxation": site.railway_is_adjacent_relaxation,
    }


def _js_shadow(spec: ShadowRegulationSpec) -> dict:
    return {
        "measurementHeightM": spec.measurement_height_m,
        "line5mMaxHours": spec.line_5m_max_hours,
        "line10mMaxHours": spec.line_10m_max_hours,
        "latitudeDeg": spec.latitude_deg, "hokkaido": spec.hokkaido,
        "timeStepMinutes": spec.time_step_minutes,
        "sampleIntervalM": spec.sample_interval_m,
        "applyDeemedBoundary": spec.apply_deemed_boundary,
    }


def _run_js(payload):
    result = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssertionError(f"JS実行に失敗:\n{result.stderr}")
    return json.loads(result.stdout)


# === 太陽位置 =========================================================

def test_solar_position_matches():
    cases = [{"lat": 35.7, "month": 12, "day": 22, "hour": h} for h in (8.0, 10.0, 12.0, 15.0)]
    cases.append({"lat": 43.1, "month": 12, "day": 22, "hour": 9.0})
    js = _run_js({"want": ["solar"], "site": _js_site(_site()), "solarCases": cases})
    for case, (alt, az) in zip(cases, js["solar"]):
        dec = solar_declination_deg(day_of_year(case["month"], case["day"]))
        py_alt, py_az = solar_position_deg(case["lat"], dec, case["hour"])
        assert alt == pytest.approx(py_alt, abs=1e-9)
        assert az == pytest.approx(py_az, abs=1e-9)


# === 法52条2項 ========================================================

@pytest.mark.parametrize("zone,far,width", [
    ("1res", 4.0, 6.0), ("commercial", 6.0, 6.0), ("1res", 2.0, 8.0), ("1res", 4.0, 12.0),
])
def test_far_matches(zone, far, width):
    specs = [{"kind": "road", "road_width_m": width}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    site = _site(specs, zone=zone, far=far)
    js = _run_js({"want": ["far"], "site": _js_site(site)})["far"]
    py = compute_far(site)
    assert js["effective"] == pytest.approx(py.effective_far)
    assert js["maxRoadWidthM"] == pytest.approx(py.max_road_width_m)
    if py.road_far is None:
        assert js["roadFar"] is None
    else:
        assert js["roadFar"] == pytest.approx(py.road_far)


# === 斜線制限 =========================================================

def _height_parity(site, points):
    js = _run_js({"want": ["heightLimits"], "site": _js_site(site),
                  "points": [list(p) for p in points]})["heightLimits"]
    for point, js_value in zip(points, js):
        py_value = height_limit_at(site, point)
        if math.isinf(py_value):
            assert js_value is None, point
        else:
            assert js_value == pytest.approx(py_value, abs=1e-9), point


def test_height_limits_match_basic():
    _height_parity(_site(), [(15, 0), (15, 5), (15, 10), (15, 19), (1, 1), (29, 19)])


def test_height_limits_match_with_setback_and_relaxations():
    specs = [
        {"kind": "road", "road_width_m": 6.0, "wall_setback_m": 2.0,
         "relaxation": {"kind": "park", "width_m": 5.0}},
        {"kind": "adjacent", "wall_setback_m": 1.0,
         "relaxation": {"kind": "water", "width_m": 6.0}},
        {"kind": "adjacent", "ground_level_diff_m": 3.0},
        {"kind": "adjacent", "relaxation": {"kind": "railway", "width_m": 8.0}},
    ]
    _height_parity(_site(specs), [(15, 2), (15, 10), (28, 10), (2, 10), (15, 18)])


def test_height_limits_match_for_north_slant_zones():
    for zone, far in (("1low", 0.8), ("1mid", 2.0), ("2mid", 3.0)):
        _height_parity(_site(zone=zone, far=far), [(15, 19), (15, 10), (15, 2)])


def test_height_limits_match_with_rotated_north():
    _height_parity(_site(zone="1low", far=0.8, north=90.0), [(2, 10), (15, 10), (28, 10)])


def test_height_limits_match_for_commercial():
    _height_parity(_site(zone="commercial", far=6.0), [(15, 0), (15, 10), (29, 10)])


# === 令132条 ==========================================================

def test_article_132_widths_match():
    specs = [{"kind": "road", "road_width_m": 4.0}, {"kind": "road", "road_width_m": 10.0},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    site = _site(specs, far=4.0)
    cases = [{"edgeIndex": 0, "point": p} for p in
             ([25, 2], [2, 2], [2, 12], [15, 10], [29, 19])]
    js = _run_js({"want": ["roadWidths"], "site": _js_site(site), "roadWidthCases": cases})
    for case, js_width in zip(cases, js["roadWidths"]):
        py_width, _ = road_slant.applied_width_at(site, tuple(case["point"]), site.edges[0])
        assert js_width == pytest.approx(py_width), case


# === 日影のみなし境界線 ================================================

def test_deemed_boundary_offsets_match():
    specs = [
        {"kind": "road", "road_width_m": 6.0},
        {"kind": "road", "road_width_m": 16.0},
        {"kind": "adjacent", "relaxation": {"kind": "water", "width_m": 8.0}},
        {"kind": "adjacent", "relaxation": {"kind": "railway", "width_m": 20.0}},
    ]
    site = _site(specs, far=4.0)
    js = _run_js({"want": ["deemed"], "site": _js_site(site)})["deemed"]
    assert js == pytest.approx(deemed_boundary_offsets(site))


# === メッシュ =========================================================

@pytest.mark.parametrize("cell,setback", [(5.0, 0.0), (3.0, 1.0), (4.0, 2.0)])
def test_mesh_matches(cell, setback):
    site = _site(setback=setback)
    options = {"cellSizeXM": cell, "cellSizeYM": cell, "coverageThreshold": 0.5}
    js = _run_js({"want": ["mesh"], "site": _js_site(site), "meshOptions": options})["mesh"]

    area = build_mesh(site, cell_size_x_m=cell, cell_size_y_m=cell)
    assign_height_limits(area)
    assert js["cellCount"] == len(area.cells)
    assert js["outlineArea"] == pytest.approx(area.outline_area_m2, rel=1e-6)
    assert js["maxFloors"] == [c.max_floors for c in area.cells]
    # 外郭線で切ったあとの面積・中心も一致すること（割り切れない幅で効く）
    assert js["cellAreas"] == pytest.approx([c.area_m2 for c in area.cells], rel=1e-9)
    flat_js = [v for c in js["cellCenters"] for v in c]
    flat_py = [v for c in area.cells for v in c.center]
    assert flat_js == pytest.approx(flat_py, rel=1e-9, abs=1e-9)


def test_mesh_cells_stay_inside_the_outline():
    """マスが建物外郭線をはみ出さないこと（Python版・JS版とも）。

    はみ出していると、敷地の外に建物が建ち、建築面積も過大に出ます。
    """
    from shapely.ops import unary_union

    cell = 4.0   # 30m / 4m は割り切れないので、端のマスが必ずはみ出す条件
    site = _site()
    area = build_mesh(site, cell_size_x_m=cell, cell_size_y_m=cell)
    outside = unary_union([c.polygon for c in area.cells]).difference(area.outline)
    assert outside.area == pytest.approx(0.0, abs=1e-9)
    assert sum(c.area_m2 for c in area.cells) <= area.outline_area_m2 + 1e-9

    options = {"cellSizeXM": cell, "cellSizeYM": cell, "coverageThreshold": 0.5}
    js = _run_js({"want": ["mesh"], "site": _js_site(site), "meshOptions": options})["mesh"]
    assert sum(js["cellAreas"]) == pytest.approx(sum(c.area_m2 for c in area.cells), rel=1e-9)


# === 最適化（全体） ===================================================

def _optimize_parity(site, cell, shadow_spec):
    options = {"cellSizeXM": cell, "cellSizeYM": cell, "coverageThreshold": 0.5}
    payload = {"want": ["optimize"], "site": _js_site(site), "meshOptions": options}
    if shadow_spec is not None:
        payload["shadowSpec"] = _js_shadow(shadow_spec)
    js = _run_js(payload)["optimize"]

    py = optimize(site, shadow_spec,
                  OptimizeOptions(cell_size_x_m=cell, cell_size_y_m=cell))

    assert js["floors"] == [int(f) for f in py.floors], "各マスの階数が一致していない"
    assert js["volume"] == pytest.approx(py.volume_m3, rel=1e-6)
    assert js["floorArea"] == pytest.approx(py.total_floor_area_m2, rel=1e-6)
    assert js["buildingArea"] == pytest.approx(py.building_area_m2, rel=1e-6)
    assert js["maxHeight"] == pytest.approx(py.max_height_m, rel=1e-6)
    assert js["coverageLimited"] is py.coverage_limited
    assert js["farLimited"] is py.far_limited
    assert js["shadowLimited"] is py.shadow_limited
    assert js["summary"] == py.summary_lines_ja()
    return js, py


def test_optimize_matches_without_shadow():
    _optimize_parity(_site(), 5.0, None)


def test_optimize_matches_when_cells_are_clipped():
    """メッシュ幅が敷地寸法で割り切れない場合も一致すること。

    端のマスが外郭線で切られるため、マスの面積と中心が両版で揃っている
    必要があります。
    """
    _optimize_parity(_site(), 4.0, None)


def test_optimize_matches_with_shadow():
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    js, py = _optimize_parity(_site(), 5.0, spec)
    assert py.shadow_limited, "この条件では日影が効くはず（テストの前提）"


def test_optimize_matches_with_setback_and_relaxation():
    specs = [
        {"kind": "road", "road_width_m": 6.0, "wall_setback_m": 1.5},
        {"kind": "adjacent", "wall_setback_m": 1.0},
        {"kind": "adjacent", "wall_setback_m": 1.0,
         "relaxation": {"kind": "water", "width_m": 4.0}},
        {"kind": "adjacent", "wall_setback_m": 1.0},
    ]
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    _optimize_parity(_site(specs), 4.0, spec)


def test_optimize_matches_with_two_roads():
    specs = [{"kind": "road", "road_width_m": 4.0}, {"kind": "road", "road_width_m": 10.0},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    _optimize_parity(_site(specs, far=4.0), 5.0, None)


def test_optimize_matches_for_low_rise_zone():
    _optimize_parity(_site(zone="1low", far=0.8, coverage=0.5), 5.0, None)


# === 天空率（法56条7項） ==============================================
#
# 左右対称な敷地・条件では、貪欲法のタイブレークが Python/JS で異なる場合
# （どちらも同じ体積を削るが、削る場所の組み合わせが複数ある）があるため、
# 天空率のテストは非対称な条件（後退距離・緩和のどちらかを辺ごとに変える）
# を使う。

_ASYMMETRIC_SPECS = [
    {"kind": "road", "road_width_m": 6.0, "wall_setback_m": 1.5},
    {"kind": "adjacent", "wall_setback_m": 1.0},
    {"kind": "adjacent", "wall_setback_m": 1.0, "relaxation": {"kind": "water", "width_m": 4.0}},
    {"kind": "adjacent", "wall_setback_m": 1.0},
]

# 後退距離は0のまま、緩和だけで左右対称を崩す（天空率が実際に効く条件を作りやすい）
_SKY_ASYMMETRIC_SPECS = [
    {"kind": "road", "road_width_m": 6.0},
    {"kind": "adjacent"},
    {"kind": "adjacent", "relaxation": {"kind": "water", "width_m": 4.0}},
    {"kind": "adjacent"},
]


def test_azimuths_match():
    js = _run_js({"want": ["sky"], "site": _js_site(_site()), "skyNAzimuth": 72,
                  "skyAzimuthOffsetRatio": 0.5})["sky"]
    assert js["azimuths"] == pytest.approx(azimuths_deg(72, 0.5))


def test_sky_measurement_points_match():
    site = _site(_ASYMMETRIC_SPECS, far=4.0)
    js = _run_js({"want": ["sky"], "site": _js_site(site), "skyIntervalM": 3.0})["sky"]
    py = measurement_points(site, 3.0)
    assert len(js["measurementPoints"]) == len(py)
    for jp, (p, kind, edge_index) in zip(js["measurementPoints"], py):
        assert jp["point"] == pytest.approx(list(p), abs=1e-9)
        assert jp["kind"] == kind
        assert jp["edgeIndex"] == edge_index


def test_reference_building_layer_count_matches():
    site = _site(_ASYMMETRIC_SPECS, far=4.0)
    js = _run_js({"want": ["sky"], "site": _js_site(site), "skyNLayers": 16})["sky"]
    assert js["referenceLayerCount"] == len(reference_building(site, n_layers=16))


def test_required_setback_for_height_matches():
    site = _site(_ASYMMETRIC_SPECS, far=4.0)
    cases = [{"edgeIndex": 0, "heightM": h} for h in (0.0, 5.0, 10.0, 20.0)]
    cases += [{"edgeIndex": 1, "heightM": h} for h in (5.0, 15.0, 40.0)]
    cases += [{"edgeIndex": 2, "heightM": h} for h in (5.0, 15.0, 40.0)]
    js = _run_js({"want": ["sky"], "site": _js_site(site), "skySetbackCases": cases})["sky"]
    for case, js_value in zip(cases, js["requiredSetbacks"]):
        py_value = required_setback_for_height(site, case["edgeIndex"], case["heightM"])
        assert js_value == pytest.approx(py_value, abs=1e-9), case


def test_sky_ratio_percent_matches():
    site = _site(_ASYMMETRIC_SPECS, far=4.0)
    cases = [{"point3": [15, 0, 4]}, {"point3": [0, 10, 4]}, {"point3": [30, 10, 4]},
             {"point3": [15, 20, 4]}]
    js = _run_js({"want": ["sky"], "site": _js_site(site), "skyRatioCases": cases,
                  "skyNLayers": 20})["sky"]
    reference = reference_building(site, n_layers=20)
    for case, js_value in zip(cases, js["skyRatios"]):
        py_value = sky_ratio_percent(tuple(case["point3"]), reference, 72, 0.5)
        assert js_value == pytest.approx(py_value, rel=1e-9), case


def _sky_options(cell, extra=None):
    options = {"cellSizeXM": cell, "cellSizeYM": cell, "coverageThreshold": 0.5,
               "useSkyRatio": True, "skyRatioIntervalM": 3.0, "skyRatioNAzimuth": 48}
    options.update(extra or {})
    return options


def _optimize_parity_with_options(site, shadow_spec, js_options, py_options):
    payload = {"want": ["optimize"], "site": _js_site(site), "meshOptions": js_options}
    if shadow_spec is not None:
        payload["shadowSpec"] = _js_shadow(shadow_spec)
    js = _run_js(payload)["optimize"]
    py = optimize(site, shadow_spec, py_options)

    assert js["floors"] == [int(f) for f in py.floors], "各マスの階数が一致していない"
    assert js["volume"] == pytest.approx(py.volume_m3, rel=1e-6)
    assert js["floorArea"] == pytest.approx(py.total_floor_area_m2, rel=1e-6)
    assert js["buildingArea"] == pytest.approx(py.building_area_m2, rel=1e-6)
    assert js["maxHeight"] == pytest.approx(py.max_height_m, rel=1e-6)
    assert js["shadowLimited"] is py.shadow_limited
    assert js["skyLimited"] is py.sky_ratio_limited
    assert js["removedBySky"] == pytest.approx(py.volume_removed_by_sky_ratio_m3, rel=1e-6)
    if py.sky_ratio is None:
        assert js["skySummary"] is None
    else:
        assert js["skySummary"]["ok"] is py.sky_ratio.ok
        assert js["skySummary"]["worstMargin"] == pytest.approx(py.sky_ratio.worst_margin, abs=1e-6)
    assert js["summary"] == py.summary_lines_ja()
    return js, py


def test_optimize_matches_with_sky_ratio_only():
    site = _site(_SKY_ASYMMETRIC_SPECS, far=2.0)
    js, py = _optimize_parity_with_options(
        site, None, _sky_options(4.0), OptimizeOptions(
            cell_size_x_m=4.0, cell_size_y_m=4.0, use_sky_ratio=True,
            sky_ratio_interval_m=3.0, sky_ratio_n_azimuth=48))
    assert py.sky_ratio_limited, "この条件では天空率が効くはず（テストの前提）"


def test_optimize_matches_with_shadow_and_sky_ratio_jointly():
    """日影と天空率を同時に解消するケース（_resolve_shadow_and_sky_jointly の検証）。"""
    site = _site(_SKY_ASYMMETRIC_SPECS, far=3.0)
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    js, py = _optimize_parity_with_options(
        site, spec, _sky_options(4.0), OptimizeOptions(
            cell_size_x_m=4.0, cell_size_y_m=4.0, use_sky_ratio=True,
            sky_ratio_interval_m=3.0, sky_ratio_n_azimuth=48))
    assert py.shadow_limited and py.sky_ratio_limited, (
        "この条件では日影・天空率の両方が効くはず（テストの前提）")


# === 等時間日影図 ======================================================

def test_isochrone_grid_margin_matches():
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0)
    cases = [{"spec": _js_shadow(spec), "maxHeightM": h} for h in (0.0, 4.0, 9.0, 15.0)]
    js = _run_js({"want": ["isochroneMargin"], "site": _js_site(_site()), "marginCases": cases})
    for case, js_value in zip(cases, js["isochroneMargin"]):
        py_value = _default_grid_margin_m(spec, case["maxHeightM"])
        assert js_value == pytest.approx(py_value, rel=1e-9), case


def test_isochrone_grid_shadow_hours_matches():
    site = _site(far=4.0)
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    cell = 5.0
    options = {"cellSizeXM": cell, "cellSizeYM": cell, "coverageThreshold": 0.5}
    grid_points = [[x, y] for x in (-5.0, 5.0, 15.0, 25.0, 35.0) for y in (-5.0, 10.0, 25.0)]

    js = _run_js({"want": ["gridShadowHours"], "site": _js_site(site), "meshOptions": options,
                  "shadowSpec": _js_shadow(spec), "gridPoints": grid_points})["gridShadowHours"]

    py_options = OptimizeOptions(cell_size_x_m=cell, cell_size_y_m=cell)
    py = optimize(site, spec, py_options)
    py_hours = grid_shadow_hours(
        py.site, py.area, py.floors, spec, [tuple(p) for p in grid_points])
    assert js == pytest.approx(list(py_hours), abs=1e-9)


def test_isochrone_polylines_match():
    """マーチングスクエア法で抽出した等高線の線分集合がPython/JSで一致すること。

    ポリラインを繋ぐ順序はdict/Mapの反復順に依存しうるので、繋いだあとの
    折れ線ではなく、繋ぐ前の線分（端点の組）の集合として比較する。
    """
    site = _site(far=4.0)
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    cell = 5.0
    options = {"cellSizeXM": cell, "cellSizeYM": cell, "coverageThreshold": 0.5}
    levels = [1.0, 2.0]
    margin_m = 15.0
    interval_m = 4.0

    js = _run_js({"want": ["isochrone"], "site": _js_site(site), "meshOptions": options,
                  "shadowSpec": _js_shadow(spec), "isochroneLevels": levels,
                  "isochroneIntervalM": interval_m, "isochroneMarginM": margin_m})["isochrone"]

    py_options = OptimizeOptions(cell_size_x_m=cell, cell_size_y_m=cell)
    py = optimize(site, spec, py_options)
    py_iso = site_isochrones(py.site, py.area, py.floors, spec, levels,
                              interval_m=interval_m, margin_m=margin_m)

    def segments(polylines):
        segs = set()
        for points, closed in polylines:
            pts = [(round(p[0], 4), round(p[1], 4)) for p in points]
            pairs = list(zip(pts, pts[1:]))
            if closed and len(pts) > 1:
                pairs.append((pts[-1], pts[0]))
            for a, b in pairs:
                segs.add(frozenset((a, b)))
        return segs

    for level in levels:
        # JSのオブジェクトキーは数値を文字列化するので、整数値は "1.0" ではなく "1" になる
        js_key = str(int(level)) if level == int(level) else str(level)
        js_polylines = [(p["points"], p["closed"]) for p in js[js_key]]
        py_polylines = py_iso[level]
        assert segments(js_polylines) == segments(py_polylines), level


def test_optimize_matches_with_sky_ratio_and_setback_relaxation():
    specs = [
        {"kind": "road", "road_width_m": 5.0, "wall_setback_m": 0.5},
        {"kind": "adjacent", "wall_setback_m": 0.5,
         "relaxation": {"kind": "park", "width_m": 6.0}},
        {"kind": "adjacent", "wall_setback_m": 1.5},
        {"kind": "adjacent", "wall_setback_m": 0.5},
    ]
    site = _site(specs, far=3.0)
    js, py = _optimize_parity_with_options(
        site, None, _sky_options(5.0), OptimizeOptions(
            cell_size_x_m=5.0, cell_size_y_m=5.0, use_sky_ratio=True,
            sky_ratio_interval_m=3.0, sky_ratio_n_azimuth=48))
