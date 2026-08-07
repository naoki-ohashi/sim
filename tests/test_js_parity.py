"""JavaScript版エンジンがPython版と同じ答えを出すことの検証。

Web版(web/engine.js, web/envelope.js)はPython版の移植なので、両方が
同じ入力で同じ結果になっていないと意味がありません。ここでは実際に
Node.jsでJS版を走らせ、Python版の結果と突き合わせます。

日影計算だけは実装方法が異なります（Python版は多角形の和集合、JS版は
線分交差判定）。数学的には同値ですが、測定点の生成に浮動小数の差が出る
ため、時間数は緩めの許容差で比較しています。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jwcad_volume.envelope import compute_max_envelope
from jwcad_volume.massing import max_height as blocks_max_height, total_floor_area, total_volume
from jwcad_volume.regulations.combined import required_setback_for_height
from jwcad_volume.regulations.reference_building import reference_building_blocks
from jwcad_volume.regulations.shadow import ShadowRegulationParams, compute_shadow_hours
from jwcad_volume.regulations.sky_ratio import sky_ratio_percent
from jwcad_volume.massing import Block
from jwcad_volume.site import Boundary, Site
from jwcad_volume.solar import day_of_year, solar_declination_deg, solar_position_deg
from jwcad_volume.zoning import ZoningParams

from shapely.geometry import Polygon

RUNNER = Path(__file__).parent / "js_runner.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js が無い環境ではスキップ")

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _py_site(far_ratio=2.0, coverage_ratio=0.6, zone="1res"):
    zoning = ZoningParams(zone_type=zone, far_ratio=far_ratio, coverage_ratio=coverage_ratio)
    edges = [
        Boundary((0.0, 0.0), (30.0, 0.0), kind="road", road_width_m=6.0),
        Boundary((30.0, 0.0), (30.0, 20.0), kind="adjacent"),
        Boundary((30.0, 20.0), (0.0, 20.0), kind="north"),
        Boundary((0.0, 20.0), (0.0, 0.0), kind="adjacent"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning, floor_height_m=3.2)


SQUARE30 = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)]


def _py_site_with_tower():
    """天空率の多段タワーが実際に生成される条件（探索経路を通すため）。"""
    zoning = ZoningParams(zone_type="1res", far_ratio=1000.0, coverage_ratio=1.0)
    edges = [
        Boundary((0.0, 0.0), (30.0, 0.0), kind="road", road_width_m=6.0),
        Boundary((30.0, 0.0), (30.0, 30.0), kind="adjacent"),
        Boundary((30.0, 30.0), (0.0, 30.0), kind="none"),
        Boundary((0.0, 30.0), (0.0, 0.0), kind="none"),
    ]
    return Site(points=SQUARE30, edges=edges, zoning=zoning, floor_height_m=3.2)


def _js_site(site):
    return {
        "points": [list(p) for p in site.points],
        "edges": [
            {"p1": list(e.p1), "p2": list(e.p2), "kind": e.kind,
             "roadWidthM": e.road_width_m, "setbackM": e.setback_m}
            for e in site.edges
        ],
        "zoning": {
            "zoneType": site.zoning.zone_type,
            "farRatio": site.zoning.far_ratio,
            "coverageRatio": site.zoning.coverage_ratio,
            "absoluteHeightLimitM": site.zoning.absolute_height_limit_m,
        },
        "floorHeightM": site.floor_height_m,
    }


def _run_js(payload):
    result = subprocess.run(
        ["node", str(RUNNER)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise AssertionError(f"JS実行に失敗:\n{result.stderr}")
    return json.loads(result.stdout)


# --- 太陽位置 ---------------------------------------------------------

def test_solar_position_matches():
    cases = [
        {"lat": 35.7, "month": 12, "day": 22, "hour": 8.0},
        {"lat": 35.7, "month": 12, "day": 22, "hour": 12.0},
        {"lat": 35.7, "month": 6, "day": 21, "hour": 15.0},
        {"lat": 43.0, "month": 12, "day": 22, "hour": 10.0},
    ]
    js = _run_js({"want": ["solar"], "site": _js_site(_py_site()), "solarCases": cases})
    for case, (js_alt, js_az) in zip(cases, js["solar"]):
        dec = solar_declination_deg(day_of_year(case["month"], case["day"]))
        py_alt, py_az = solar_position_deg(case["lat"], dec, case["hour"])
        assert js_alt == pytest.approx(py_alt, abs=1e-9)
        assert js_az == pytest.approx(py_az, abs=1e-9)


# --- 斜線制限の逆算 ---------------------------------------------------

def test_required_setback_matches():
    site = _py_site()
    cases = [
        {"edgeIndex": 0, "height": 5.0}, {"edgeIndex": 0, "height": 20.0},
        {"edgeIndex": 0, "height": 1000.0},
        {"edgeIndex": 1, "height": 20.0}, {"edgeIndex": 1, "height": 35.0},
        {"edgeIndex": 2, "height": 30.0},
        {"edgeIndex": 1, "height": 40.0, "slopeMultiplier": 2.0},
    ]
    js = _run_js({"want": ["setback"], "site": _js_site(site), "setbackCases": cases})
    for case, js_value in zip(cases, js["setback"]):
        py_value = required_setback_for_height(
            site.edges[case["edgeIndex"]], case["height"], site, case.get("slopeMultiplier", 1.0))
        assert js_value == pytest.approx(py_value, abs=1e-9), case


# --- 適合建築物 -------------------------------------------------------

def test_reference_building_matches():
    site = _py_site()
    js = _run_js({"want": ["baseline"], "site": _js_site(site), "nLayers": 8})
    py_blocks = reference_building_blocks(site, n_layers=8)
    assert len(js["baseline"]) == len(py_blocks)
    for js_block, py_block in zip(js["baseline"], py_blocks):
        assert js_block["zBottom"] == pytest.approx(py_block.z_bottom, abs=1e-9)
        assert js_block["zTop"] == pytest.approx(py_block.z_top, abs=1e-9)
        assert js_block["area"] == pytest.approx(py_block.footprint.area, rel=1e-9)


# --- 天空率 -----------------------------------------------------------

def test_sky_ratio_matches():
    site = _py_site()
    py_blocks = reference_building_blocks(site, n_layers=8)
    js_blocks = [
        {"footprint": [[x, y] for x, y, *_ in b.footprint.exterior.coords[:-1]],
         "zBottom": b.z_bottom, "zTop": b.z_top}
        for b in py_blocks
    ]
    points = [[0.0, -6.001, 0.0], [15.0, -6.001, 0.0], [30.001, 10.0, 0.0], [15.0, 20.001, 0.0]]
    js = _run_js({
        "want": ["skyRatio"], "site": _js_site(site),
        "blocks": js_blocks, "skyRatioPoints": points, "nAzimuth": 60,
    })
    for point, js_value in zip(points, js["skyRatio"]):
        py_value = sky_ratio_percent(tuple(point), py_blocks, n_azimuth=60)
        assert js_value == pytest.approx(py_value, rel=1e-6), point


# --- 日影 -------------------------------------------------------------

def test_shadow_hours_match():
    site = _py_site()
    py_blocks = [Block(footprint=Polygon(SQUARE), z_bottom=0.0, z_top=25.0)]
    js_blocks = [{"footprint": [list(p) for p in SQUARE], "zBottom": 0.0, "zTop": 25.0}]
    params = ShadowRegulationParams(time_step_minutes=30.0, perimeter_sample_interval_m=5.0)
    js = _run_js({
        "want": ["shadow"], "site": _js_site(site), "blocks": js_blocks,
        "shadowParams": {
            "measurementMonth": params.measurement_month, "measurementDay": params.measurement_day,
            "startHour": params.start_hour, "endHour": params.end_hour,
            "timeStepMinutes": params.time_step_minutes, "latitudeDeg": params.latitude_deg,
            "line1DistanceM": params.line1_distance_m, "line1MaxHours": params.line1_max_hours,
            "line2DistanceM": params.line2_distance_m, "line2MaxHours": params.line2_max_hours,
            "perimeterSampleIntervalM": params.perimeter_sample_interval_m,
        },
    })
    py_results = compute_shadow_hours(site, py_blocks, params)
    for js_line, py_line in zip(js["shadow"], py_results):
        assert js_line["lineName"] == py_line.line_name
        # 測定点の生成に浮動小数の差が出るため、時間刻み1つ分を許容する
        assert js_line["worstHours"] == pytest.approx(py_line.worst_point[1], abs=0.5)


# --- 全体（最大ボリューム探索） ---------------------------------------

@pytest.mark.parametrize(
    "far_ratio,coverage_ratio,use_sky_ratio",
    [(1000.0, 1.0, False), (1000.0, 1.0, True), (2.0, 0.6, True)],
)
def test_envelope_matches(far_ratio, coverage_ratio, use_sky_ratio):
    site = _py_site(far_ratio=far_ratio, coverage_ratio=coverage_ratio)
    kwargs = dict(
        n_layers=6, interval_m=10.0, n_azimuth=30, measurement_height=0.0,
        split_fractions=(0.3, 0.5), search_iterations=8,
        stage_insets_m=(0.0, 3.0), max_stages=2, use_sky_ratio=use_sky_ratio,
    )
    py = compute_max_envelope(site, **kwargs)
    js = _run_js({
        "want": ["envelope"], "site": _js_site(site),
        "envelopeOptions": {
            "nLayers": 6, "intervalM": 10.0, "nAzimuth": 30, "measurementHeight": 0.0,
            "splitFractions": [0.3, 0.5], "iterations": 8,
            "stageInsetsM": [0.0, 3.0], "maxStages": 2, "useSkyRatio": use_sky_ratio,
        },
    })["envelope"]

    assert js["maxHeight"] == pytest.approx(blocks_max_height(py.blocks), rel=1e-4)
    assert js["volume"] == pytest.approx(py.volume_m3, rel=1e-4)
    assert js["floorArea"] == pytest.approx(total_floor_area(py.blocks, site.floor_height_m), rel=1e-4)
    assert js["footprintArea"] == pytest.approx(py.footprint_area_m2, rel=1e-4)
    assert js["stageCount"] == len(py.tower.stages)
    assert js["extraHeight"] == pytest.approx(py.tower.extra_height_m, rel=1e-3, abs=1e-6)
    assert js["coverageCapApplied"] is py.coverage_cap_applied
    assert js["farCapApplied"] is py.far_cap_applied
    assert js["allSkyRatioOk"] is all(c.ok for c in py.sky_ratio_checks)


def test_envelope_with_multistage_tower_matches():
    """段が実際に積まれる条件で、多段探索の経路まで一致するか確認する。"""
    site = _py_site_with_tower()
    py = compute_max_envelope(
        site, n_layers=6, interval_m=10.0, n_azimuth=30, measurement_height=0.0,
        split_fractions=(0.3, 0.5), search_iterations=8,
        stage_insets_m=(0.0, 3.0), max_stages=2, use_sky_ratio=True,
    )
    js = _run_js({
        "want": ["envelope"], "site": _js_site(site),
        "envelopeOptions": {
            "nLayers": 6, "intervalM": 10.0, "nAzimuth": 30, "measurementHeight": 0.0,
            "splitFractions": [0.3, 0.5], "iterations": 8,
            "stageInsetsM": [0.0, 3.0], "maxStages": 2, "useSkyRatio": True,
        },
    })["envelope"]

    assert py.tower.stages, "この条件では段が積まれるはず（テストの前提）"
    assert js["stageCount"] == len(py.tower.stages)
    assert js["extraHeight"] == pytest.approx(py.tower.extra_height_m, rel=1e-3)
    assert js["maxHeight"] == pytest.approx(blocks_max_height(py.blocks), rel=1e-3)
    assert js["volume"] == pytest.approx(py.volume_m3, rel=1e-3)
    assert js["allSkyRatioOk"] is all(c.ok for c in py.sky_ratio_checks)
    assert js["summary"] == py.summary_lines_ja()


def test_summary_text_matches():
    site = _py_site()
    kwargs = dict(
        n_layers=6, interval_m=10.0, n_azimuth=30, split_fractions=(0.3, 0.5),
        search_iterations=8, stage_insets_m=(0.0, 3.0), max_stages=2,
    )
    py = compute_max_envelope(site, **kwargs)
    js = _run_js({
        "want": ["envelope"], "site": _js_site(site),
        "envelopeOptions": {
            "nLayers": 6, "intervalM": 10.0, "nAzimuth": 30, "measurementHeight": 0.0,
            "splitFractions": [0.3, 0.5], "iterations": 8,
            "stageInsetsM": [0.0, 3.0], "maxStages": 2, "useSkyRatio": True,
        },
    })["envelope"]
    assert js["summary"] == py.summary_lines_ja()
