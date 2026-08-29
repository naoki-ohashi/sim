"""敷地図のJSON/CSV読み込みのテスト。"""
import json

import pytest

from mvce.config import load_project
from mvce.io.dxf_site import SiteImportError
from mvce.io.site_csv import read_site_plan_csv
from mvce.io.site_json import read_site_plan_json

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


# === JSON =============================================================

def test_read_json_site_with_points_and_edges(tmp_path):
    path = tmp_path / "site.json"
    path.write_text(json.dumps({
        "points": [list(p) for p in SQUARE],
        "edges": [
            {"kind": "road", "road_width_m": 6.0, "wall_setback_m": 1.5},
            {"kind": "adjacent"},
            {"kind": "adjacent", "relaxation": {"kind": "water", "width_m": 4.0}},
            {"kind": "adjacent"},
        ],
    }), encoding="utf-8")
    plan = read_site_plan_json(str(path))
    assert plan.points == SQUARE
    specs = plan.edge_specs()
    assert specs[0]["kind"] == "road"
    assert specs[0]["road_width_m"] == 6.0
    assert specs[0]["wall_setback_m"] == 1.5
    assert specs[2]["relaxation"] == {"kind": "water", "width_m": 4.0}


def test_read_json_site_without_edges_defaults_to_none_kind(tmp_path):
    path = tmp_path / "site.json"
    path.write_text(json.dumps({"points": [list(p) for p in SQUARE]}), encoding="utf-8")
    plan = read_site_plan_json(str(path))
    assert plan.points == SQUARE
    assert [e.guess_kind() for e in plan.edges] == ["none"] * 4
    assert any("edges" in n for n in plan.notes)


def test_json_site_rejects_missing_points(tmp_path):
    path = tmp_path / "site.json"
    path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    with pytest.raises(SiteImportError, match="points"):
        read_site_plan_json(str(path))


def test_json_site_rejects_too_few_points(tmp_path):
    path = tmp_path / "site.json"
    path.write_text(json.dumps({"points": [[0, 0], [1, 0]]}), encoding="utf-8")
    with pytest.raises(SiteImportError, match="3点以上"):
        read_site_plan_json(str(path))


def test_json_site_rejects_road_edge_without_width(tmp_path):
    path = tmp_path / "site.json"
    path.write_text(json.dumps({
        "points": [list(p) for p in SQUARE],
        "edges": [{"kind": "road"}, {"kind": "adjacent"},
                  {"kind": "adjacent"}, {"kind": "adjacent"}],
    }), encoding="utf-8")
    with pytest.raises(SiteImportError, match="road_width_m"):
        read_site_plan_json(str(path))


def test_json_site_rejects_bad_json(tmp_path):
    path = tmp_path / "site.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SiteImportError, match="形式が正しくありません"):
        read_site_plan_json(str(path))


def test_json_site_scales_units(tmp_path):
    path = tmp_path / "site_mm.json"
    path.write_text(json.dumps({
        "points": [[0, 0], [30000, 0], [30000, 20000], [0, 20000]],
        "units_per_meter": 1000,
    }), encoding="utf-8")
    plan = read_site_plan_json(str(path))
    assert plan.points == SQUARE


# === CSV ===============================================================

CSV_WITH_KIND = """x,y,kind,road_width_m,wall_setback_m,relaxation_kind,relaxation_width_m,ground_level_diff_m,label
0,0,road,6.0,1.5,,,,南側道路
30,0,adjacent,,,,,,
30,20,adjacent,,,water,4.0,,水路に接する
0,20,adjacent,,,,,,
"""

CSV_POINTS_ONLY = """x,y
0,0
30,0
30,20
0,20
"""


def test_read_csv_site_with_optional_columns(tmp_path):
    path = tmp_path / "site.csv"
    path.write_text(CSV_WITH_KIND, encoding="utf-8")
    plan = read_site_plan_csv(str(path))
    assert plan.points == SQUARE
    specs = plan.edge_specs()
    assert specs[0]["kind"] == "road"
    assert specs[0]["road_width_m"] == 6.0
    assert specs[0]["wall_setback_m"] == 1.5
    assert specs[2]["relaxation"] == {"kind": "water", "width_m": 4.0}
    assert plan.edges[0].label == "南側道路"


def test_read_csv_site_points_only(tmp_path):
    path = tmp_path / "site.csv"
    path.write_text(CSV_POINTS_ONLY, encoding="utf-8")
    plan = read_site_plan_csv(str(path))
    assert plan.points == SQUARE
    assert [e.guess_kind() for e in plan.edges] == ["none"] * 4
    assert any("kind列が無い" in n for n in plan.notes)


def test_csv_site_rejects_missing_xy_columns(tmp_path):
    path = tmp_path / "site.csv"
    path.write_text("a,b\n0,0\n1,0\n1,1\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="必須列"):
        read_site_plan_csv(str(path))


def test_csv_site_rejects_unknown_kind_value(tmp_path):
    path = tmp_path / "site.csv"
    path.write_text("x,y,kind\n0,0,foo\n30,0,adjacent\n30,20,adjacent\n0,20,adjacent\n",
                     encoding="utf-8")
    with pytest.raises(SiteImportError, match="road/adjacent/none"):
        read_site_plan_csv(str(path))


def test_csv_site_rejects_road_without_width(tmp_path):
    path = tmp_path / "site.csv"
    path.write_text("x,y,kind\n0,0,road\n30,0,adjacent\n30,20,adjacent\n0,20,adjacent\n",
                     encoding="utf-8")
    with pytest.raises(SiteImportError, match="road_width_m"):
        read_site_plan_csv(str(path))


def test_csv_site_rejects_too_few_rows(tmp_path):
    path = tmp_path / "site.csv"
    path.write_text("x,y\n0,0\n1,0\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="3点以上"):
        read_site_plan_csv(str(path))


def test_csv_site_shift_jis_encoding(tmp_path):
    path = tmp_path / "site_sjis.csv"
    path.write_bytes(CSV_WITH_KIND.encode("shift_jis"))
    plan = read_site_plan_csv(str(path), encoding="shift_jis")
    assert plan.points == SQUARE
    assert plan.edges[0].label == "南側道路"


def test_csv_site_bad_encoding_gives_helpful_error(tmp_path):
    path = tmp_path / "site_sjis.csv"
    path.write_bytes(CSV_WITH_KIND.encode("shift_jis"))
    with pytest.raises(SiteImportError, match="shift_jis"):
        read_site_plan_csv(str(path), encoding="utf-8")


def test_csv_site_scales_units(tmp_path):
    path = tmp_path / "site_mm.csv"
    path.write_text("x,y\n0,0\n30000,0\n30000,20000\n0,20000\n", encoding="utf-8")
    plan = read_site_plan_csv(str(path), units_per_meter=1000.0)
    assert plan.points == SQUARE


# === mvce/config.py 統合 =================================================

ZONING_YAML = "zoning: {zone_type: 1res, far_ratio: 200, coverage_ratio: 60}\n"


def test_load_project_with_json_site(tmp_path):
    json_path = tmp_path / "site.json"
    json_path.write_text(json.dumps({
        "points": [list(p) for p in SQUARE],
        "edges": [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
                  {"kind": "adjacent"}, {"kind": "adjacent"}],
    }), encoding="utf-8")
    config = tmp_path / "p.yaml"
    config.write_text(f"""
site:
  json: {{path: {json_path}}}
  {ZONING_YAML.replace(chr(10), chr(10) + '  ')}
""", encoding="utf-8")
    project = load_project(str(config))
    assert project.site.area_m2 == pytest.approx(600.0)
    assert project.site.edges[0].road_width_m == 6.0


def test_load_project_with_csv_site(tmp_path):
    csv_path = tmp_path / "site.csv"
    csv_path.write_text(CSV_WITH_KIND, encoding="utf-8")
    config = tmp_path / "p.yaml"
    config.write_text(f"""
site:
  csv: {{path: {csv_path}}}
  {ZONING_YAML.replace(chr(10), chr(10) + '  ')}
""", encoding="utf-8")
    project = load_project(str(config))
    assert project.site.area_m2 == pytest.approx(600.0)
    assert project.site.edges[0].road_width_m == 6.0
    assert project.site.edges[2].relaxation.kind.value == "water"


def test_load_project_yaml_edges_override_json_edges(tmp_path):
    json_path = tmp_path / "site.json"
    json_path.write_text(json.dumps({
        "points": [list(p) for p in SQUARE],
        "edges": [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
                  {"kind": "adjacent"}, {"kind": "adjacent"}],
    }), encoding="utf-8")
    config = tmp_path / "p.yaml"
    config.write_text(f"""
site:
  json: {{path: {json_path}}}
  edges:
    - {{kind: road, road_width_m: 8.0}}
    - {{kind: adjacent}}
    - {{kind: adjacent}}
    - {{kind: adjacent}}
  {ZONING_YAML.replace(chr(10), chr(10) + '  ')}
""", encoding="utf-8")
    project = load_project(str(config))
    # YAML側のedgesが優先され、JSON側のroad_width_m(6.0)ではなく8.0になる
    assert project.site.edges[0].road_width_m == 8.0
