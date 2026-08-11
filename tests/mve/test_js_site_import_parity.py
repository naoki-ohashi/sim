"""敷地JSON/CSV読み込み（web/mve/site_import.js）がPython版と同じ結果になることの検証。

Python版（mve/io/site_json.py, site_csv.py）と同じ入力を、Node.jsで実際に
site_import.jsを走らせて突き合わせる。エラーになるべき入力は両方が
拒否することも確認する。
"""
import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mve.io.dxf_site import SiteImportError
from mve.io.site_csv import read_site_plan_csv
from mve.io.site_json import read_site_plan_json

RUNNER = Path(__file__).parent / "js_site_import_runner.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js が無い環境ではスキップ")

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _run_js(kind, text):
    result = subprocess.run(["node", str(RUNNER)], input=json.dumps({"kind": kind, "text": text}),
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"JS実行に失敗:\n{result.stderr}")
    return json.loads(result.stdout)


def _edge_dict(js_edge):
    relaxation = js_edge["relaxation"]
    return {
        "kind": js_edge["kind"], "road_width_m": js_edge["roadWidthM"],
        "wall_setback_m": js_edge["wallSetbackM"],
        "relaxation": {"kind": relaxation["kind"], "width_m": relaxation["widthM"]}
                      if relaxation else None,
        "ground_level_diff_m": js_edge["groundLevelDiffM"],
    }


def _py_edge_dict(edge):
    return {
        "kind": edge.kind_hint, "road_width_m": edge.road_width_m,
        "wall_setback_m": edge.wall_setback_m, "relaxation": edge.relaxation,
        "ground_level_diff_m": edge.ground_level_diff_m,
    }


# === JSON =============================================================

def test_json_with_points_and_edges_matches(tmp_path):
    data = {
        "points": [list(p) for p in SQUARE],
        "edges": [
            {"kind": "road", "road_width_m": 6.0, "wall_setback_m": 1.5},
            {"kind": "adjacent"},
            {"kind": "adjacent", "relaxation": {"kind": "water", "width_m": 4.0}},
            {"kind": "adjacent", "ground_level_diff_m": 0.5},
        ],
    }
    text = json.dumps(data)
    path = tmp_path / "site.json"
    path.write_text(text, encoding="utf-8")

    py = read_site_plan_json(str(path))
    js = _run_js("json", text)

    assert js["ok"], js.get("error")
    assert js["result"]["points"] == [list(p) for p in py.points]
    assert [_edge_dict(e) for e in js["result"]["edges"]] == [_py_edge_dict(e) for e in py.edges]


def test_json_without_edges_matches(tmp_path):
    text = json.dumps({"points": [list(p) for p in SQUARE]})
    path = tmp_path / "site.json"
    path.write_text(text, encoding="utf-8")

    py = read_site_plan_json(str(path))
    js = _run_js("json", text)

    assert js["ok"], js.get("error")
    assert js["result"]["edges"] is None
    assert js["result"]["points"] == [list(p) for p in py.points]
    assert len(js["result"]["notes"]) == len(py.notes)


def test_json_with_units_per_meter_matches(tmp_path):
    data = {"points": [[x * 1000, y * 1000] for x, y in SQUARE], "units_per_meter": 1000.0}
    text = json.dumps(data)
    path = tmp_path / "site.json"
    path.write_text(text, encoding="utf-8")

    py = read_site_plan_json(str(path))
    js = _run_js("json", text)

    assert js["ok"], js.get("error")
    js_flat = [v for p in js["result"]["points"] for v in p]
    py_flat = [v for p in py.points for v in p]
    assert js_flat == pytest.approx(py_flat)


@pytest.mark.parametrize("data", [
    {"foo": "bar"},
    {"points": [[0, 0], [1, 0]]},
    {"points": [list(p) for p in SQUARE], "edges": [{"kind": "road"}]},
    {"points": [list(p) for p in SQUARE],
     "edges": [{"kind": "road"}, {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"}]},
    {"points": [list(p) for p in SQUARE],
     "edges": [{"kind": "oops"}, {"kind": "adjacent"}, {"kind": "adjacent"}, {"kind": "adjacent"}]},
])
def test_json_rejects_invalid_input_on_both_sides(tmp_path, data):
    text = json.dumps(data)
    path = tmp_path / "site.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SiteImportError):
        read_site_plan_json(str(path))
    js = _run_js("json", text)
    assert not js["ok"], "JSも読み込みエラーになるべき"


# === CSV ================================================================

def _csv_text(rows, header):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def test_csv_with_kind_column_matches(tmp_path):
    header = ["x", "y", "kind", "road_width_m", "wall_setback_m",
              "relaxation_kind", "relaxation_width_m", "ground_level_diff_m", "label"]
    rows = [
        {"x": 0, "y": 0, "kind": "road", "road_width_m": 6.0, "wall_setback_m": 1.5,
         "relaxation_kind": "", "relaxation_width_m": "", "ground_level_diff_m": "", "label": "南側道路"},
        {"x": 30, "y": 0, "kind": "adjacent", "road_width_m": "", "wall_setback_m": "",
         "relaxation_kind": "", "relaxation_width_m": "", "ground_level_diff_m": "", "label": ""},
        {"x": 30, "y": 20, "kind": "adjacent", "road_width_m": "", "wall_setback_m": "",
         "relaxation_kind": "water", "relaxation_width_m": 4.0, "ground_level_diff_m": "", "label": "水路に接する"},
        {"x": 0, "y": 20, "kind": "adjacent", "road_width_m": "", "wall_setback_m": "",
         "relaxation_kind": "", "relaxation_width_m": "", "ground_level_diff_m": "", "label": ""},
    ]
    text = _csv_text(rows, header)
    path = tmp_path / "site.csv"
    path.write_text(text, encoding="utf-8-sig")

    py = read_site_plan_csv(str(path))
    js = _run_js("csv", text)

    assert js["ok"], js.get("error")
    assert js["result"]["points"] == [list(p) for p in py.points]
    assert [_edge_dict(e) for e in js["result"]["edges"]] == [_py_edge_dict(e) for e in py.edges]


def test_csv_without_kind_column_matches(tmp_path):
    header = ["x", "y"]
    rows = [{"x": p[0], "y": p[1]} for p in SQUARE]
    text = _csv_text(rows, header)
    path = tmp_path / "site.csv"
    path.write_text(text, encoding="utf-8-sig")

    py = read_site_plan_csv(str(path))
    js = _run_js("csv", text)

    assert js["ok"], js.get("error")
    assert js["result"]["edges"] is None
    assert js["result"]["points"] == [list(p) for p in py.points]


@pytest.mark.parametrize("header,rows", [
    (["a", "b"], [{"a": 0, "b": 0}, {"a": 1, "b": 0}, {"a": 1, "b": 1}]),
    (["x", "y"], [{"x": 0, "y": 0}, {"x": 1, "y": 0}]),
    (["x", "y", "kind"], [{"x": 0, "y": 0, "kind": "road"},
                          {"x": 1, "y": 0, "kind": "adjacent"},
                          {"x": 1, "y": 1, "kind": "adjacent"}]),
])
def test_csv_rejects_invalid_input_on_both_sides(tmp_path, header, rows):
    text = _csv_text(rows, header)
    path = tmp_path / "site.csv"
    path.write_text(text, encoding="utf-8-sig")

    with pytest.raises(SiteImportError):
        read_site_plan_csv(str(path))
    js = _run_js("csv", text)
    assert not js["ok"], "JSも読み込みエラーになるべき"
