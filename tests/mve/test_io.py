"""敷地図の読み込みと図面・3D出力のテスト。"""
import ezdxf
import pytest

from mve.config import load_project
from mve.io.dxf_site import SiteImportError, read_site_plan
from mve.io.drawing import write_dxf
from mve.io.viewer3d import build_html, write_html
from mve.optimizer import OptimizeOptions, optimize
from mve.regulations.shadow import ShadowRegulationSpec
from mve.site import Site
from mve.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(**kwargs):
    specs = [{"kind": "road", "road_width_m": 6.0}, {"kind": "adjacent"},
             {"kind": "adjacent"}, {"kind": "adjacent"}]
    return Site.from_rings(SQUARE, specs, ZoningParams("1res", 2.0, 0.6), **kwargs)


def _result(site=None, shadow=False):
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0) if shadow else None
    return optimize(site or _site(), spec,
                    OptimizeOptions(cell_size_x_m=5.0, cell_size_y_m=5.0))


# === DXFの敷地図読み込み ==============================================

def _write_polyline_dxf(path, points, layer="敷地", closed=True):
    doc = ezdxf.new("R2010")
    doc.modelspace().add_lwpolyline(points, close=closed, dxfattribs={"layer": layer})
    doc.saveas(path)


def _write_lines_dxf(path, segments):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for p1, p2, layer in segments:
        msp.add_line(p1, p2, dxfattribs={"layer": layer})
    doc.saveas(path)


def test_read_closed_polyline(tmp_path):
    path = tmp_path / "site.dxf"
    _write_polyline_dxf(str(path), SQUARE)
    plan = read_site_plan(str(path))
    assert plan.points == SQUARE


def test_read_lines_and_infer_kind_from_layer(tmp_path):
    path = tmp_path / "site.dxf"
    _write_lines_dxf(str(path), [
        ((0, 0), (30, 0), "道路境界線"),
        ((30, 0), (30, 20), "隣地境界線"),
        ((30, 20), (0, 20), "隣地境界線"),
        ((0, 20), (0, 0), "隣地境界線"),
    ])
    plan = read_site_plan(str(path))
    assert len(plan.points) == 4
    assert [e.guess_kind() for e in plan.edges] == ["road", "adjacent", "adjacent", "adjacent"]


def test_edge_specs_carry_road_width_and_setback(tmp_path):
    path = tmp_path / "site.dxf"
    _write_lines_dxf(str(path), [
        ((0, 0), (30, 0), "road"), ((30, 0), (30, 20), "adjacent"),
        ((30, 20), (0, 20), "adjacent"), ((0, 20), (0, 0), "adjacent"),
    ])
    specs = read_site_plan(str(path)).edge_specs(default_road_width_m=8.0, wall_setback_m=2.0)
    assert specs[0]["road_width_m"] == 8.0
    assert all(s["wall_setback_m"] == 2.0 for s in specs)


def test_millimetre_drawing_is_scaled(tmp_path):
    path = tmp_path / "site_mm.dxf"
    _write_polyline_dxf(str(path), [(0, 0), (30000, 0), (30000, 20000), (0, 20000)])
    plan = read_site_plan(str(path), units_per_meter=1000.0)
    assert plan.points == SQUARE


def test_reversed_polyline_is_normalised_to_ccw(tmp_path):
    path = tmp_path / "cw.dxf"
    _write_polyline_dxf(str(path), list(reversed(SQUARE)))
    plan = read_site_plan(str(path))
    from mve.geometry import polygon_signed_area
    assert polygon_signed_area(plan.points) > 0


def test_open_shape_is_rejected(tmp_path):
    path = tmp_path / "open.dxf"
    _write_lines_dxf(str(path), [
        ((0, 0), (30, 0), "s"), ((30, 0), (30, 20), "s"), ((30, 20), (0, 20), "s"),
    ])
    with pytest.raises(SiteImportError, match="つながっています"):
        read_site_plan(str(path))


def test_empty_dxf_is_rejected(tmp_path):
    path = tmp_path / "empty.dxf"
    ezdxf.new("R2010").saveas(str(path))
    with pytest.raises(SiteImportError, match="見つかりませんでした"):
        read_site_plan(str(path))


def test_layer_filter_selects_the_right_outline(tmp_path):
    path = tmp_path / "two.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline(SQUARE, close=True, dxfattribs={"layer": "敷地"})
    msp.add_lwpolyline([(100, 100), (110, 100), (110, 110)], close=True,
                       dxfattribs={"layer": "建物"})
    doc.saveas(str(path))
    plan = read_site_plan(str(path), layer="敷地")
    assert plan.points == SQUARE


# === 図面出力 =========================================================

def test_dxf_output_has_expected_layers(tmp_path):
    result = _result(shadow=True)
    path = tmp_path / "out.dxf"
    write_dxf(result, str(path))

    msp = ezdxf.readfile(str(path)).modelspace()
    layers = {e.dxf.layer for e in msp}
    for expected in ("MVE-SITE", "MVE-ROAD", "MVE-OUTLINE", "MVE-MESH",
                     "MVE-NORTH", "MVE-SUMMARY", "MVE-SHADOW-5M", "MVE-SHADOW-10M"):
        assert expected in layers, expected


def test_dxf_draws_the_road_band(tmp_path):
    result = _result()
    path = tmp_path / "out.dxf"
    write_dxf(result, str(path))
    msp = ezdxf.readfile(str(path)).modelspace()
    roads = [e for e in msp if e.dxf.layer == "MVE-ROAD" and e.dxftype() == "LINE"]
    assert roads
    # 6m 道路が敷地の外（y<0）に描かれている。図面はmmなので -6000。
    ys = [v for e in roads for v in (e.dxf.start.y, e.dxf.end.y)]
    assert min(ys) == pytest.approx(-6000.0)


def test_dxf_floor_labels_can_be_disabled(tmp_path):
    result = _result()
    with_labels = tmp_path / "a.dxf"
    without = tmp_path / "b.dxf"
    write_dxf(result, str(with_labels), draw_floor_labels=True)
    write_dxf(result, str(without), draw_floor_labels=False)

    def count(path):
        return sum(1 for e in ezdxf.readfile(str(path)).modelspace()
                   if e.dxf.layer == "MVE-FLOORS")

    assert count(with_labels) > 0
    assert count(without) == 0


def test_dxf_has_one_layer_per_floor(tmp_path):
    result = _result()
    path = tmp_path / "out.dxf"
    write_dxf(result, str(path))
    msp = ezdxf.readfile(str(path)).modelspace()
    plan_layers = {e.dxf.layer for e in msp if e.dxf.layer.startswith("MVE-PLAN-")}
    assert len(plan_layers) == int(result.floors.max())


# === 3D出力 ===========================================================

def test_html_is_self_contained(tmp_path):
    html = build_html(_result())
    assert "http://" not in html and "https://" not in html
    assert "<script src=" not in html
    assert "JwcadVolumeViewer.init(" in html


def test_html_contains_japanese_summary(tmp_path):
    path = tmp_path / "v.html"
    write_html(_result(shadow=True), str(path))
    text = path.read_text(encoding="utf-8")
    assert "達成容積率" in text
    assert "敷地面積" in text


# === 設定ファイル =====================================================

SAMPLE_YAML = """
site:
  points: [[0, 0], [30, 0], [30, 20], [0, 20]]
  north_angle_deg: 15
  wall_setback_m: 1.0
  edges:
    - {{kind: road, road_width_m: 6.0}}
    - {{kind: adjacent}}
    - {{kind: adjacent, relaxation: {{kind: water, width_m: 4.0}}}}
    - {{kind: adjacent}}
  zoning: {{zone_type: 1res, far_ratio: 200, coverage_ratio: 60}}
mesh: {{cell_size_x_m: 5.0, cell_size_y_m: 5.0}}
shadow:
  measurement_height_m: 4.0
  line_5m_max_hours: 5.0
  line_10m_max_hours: 3.0
  time_step_minutes: 30.0
  sample_interval_m: 6.0
output: {{dxf_path: {dxf}, html_path: {html}}}
"""


def test_load_project_parses_everything(tmp_path):
    config = tmp_path / "p.yaml"
    config.write_text(SAMPLE_YAML.format(dxf=tmp_path / "o.dxf", html=tmp_path / "o.html"),
                      encoding="utf-8")
    project = load_project(str(config))
    assert project.site.area_m2 == pytest.approx(600.0)
    assert project.site.north.north_angle_deg == 15
    assert project.site.edges[0].road_width_m == 6.0
    assert project.site.edges[0].wall_setback_m == 1.0
    assert project.site.edges[2].relaxation.kind.value == "water"
    assert project.shadow.measurement_height_m == 4.0
    assert project.options.cell_size_x_m == 5.0


def test_percentages_are_converted_to_ratios(tmp_path):
    config = tmp_path / "p.yaml"
    config.write_text(SAMPLE_YAML.format(dxf=tmp_path / "o.dxf", html=tmp_path / "o.html"),
                      encoding="utf-8")
    zoning = load_project(str(config)).site.zoning
    assert zoning.far_ratio == pytest.approx(2.0)
    assert zoning.coverage_ratio == pytest.approx(0.6)


def test_cli_end_to_end(tmp_path, capsys):
    from mve.cli import main
    dxf, html = tmp_path / "o.dxf", tmp_path / "o.html"
    config = tmp_path / "p.yaml"
    config.write_text(SAMPLE_YAML.format(dxf=dxf, html=html), encoding="utf-8")

    assert main([str(config)]) == 0
    assert dxf.exists() and html.exists()
    out = capsys.readouterr().out
    assert "達成容積率" in out


def test_cli_no_shadow_flag(tmp_path, capsys):
    from mve.cli import main
    config = tmp_path / "p.yaml"
    config.write_text(SAMPLE_YAML.format(dxf=tmp_path / "o.dxf", html=tmp_path / "o.html"),
                      encoding="utf-8")
    assert main([str(config), "--no-shadow"]) == 0
    assert "測定線" not in capsys.readouterr().out


def test_cli_reports_bad_config(tmp_path, capsys):
    from mve.cli import main
    config = tmp_path / "bad.yaml"
    config.write_text("site: {}\n", encoding="utf-8")
    assert main([str(config)]) == 1
    assert "設定の読み込みに失敗" in capsys.readouterr().err


# === 逆日影パターン（屋根越し／棟状）のDXF ================================

def _result_with_roof(pattern="ridge", far=3.0, road=8.0):
    zoning = ZoningParams("1res", far, 0.6)
    site = Site.from_rings(
        SQUARE,
        [{"kind": "road", "road_width_m": road}, {"kind": "adjacent"},
         {"kind": "adjacent"}, {"kind": "adjacent"}],
        zoning,
    )
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    return optimize(site, spec, OptimizeOptions(
        cell_size_x_m=3.0, cell_size_y_m=3.0, envelope_family=pattern))


def test_dxf_draws_the_ridge_line_when_roof_pattern_is_used(tmp_path):
    result = _result_with_roof("ridge")
    assert result.roof_spec is not None, "この条件では屋根形状が使われるはず"
    path = tmp_path / "out.dxf"
    write_dxf(result, str(path))

    msp = ezdxf.readfile(str(path)).modelspace()
    ridge_lines = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MVE-RIDGE"]
    ridge_texts = [e for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "MVE-RIDGE"]
    assert ridge_lines and ridge_texts


def test_dxf_has_no_ridge_line_for_voxel_family(tmp_path):
    zoning = ZoningParams("1res", 3.0, 0.6)
    site = Site.from_rings(
        SQUARE, [{"kind": "road", "road_width_m": 8.0}, {"kind": "adjacent"},
                {"kind": "adjacent"}, {"kind": "adjacent"}], zoning)
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    result = optimize(site, spec, OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))
    assert result.roof_spec is None

    path = tmp_path / "out.dxf"
    write_dxf(result, str(path))
    msp = ezdxf.readfile(str(path)).modelspace()
    assert not [e for e in msp if e.dxf.layer == "MVE-RIDGE"]


# === 逆日影パターン（envelope_family）の設定・CLI ==========================

def test_load_project_reads_envelope_family(tmp_path):
    config = tmp_path / "p.yaml"
    text = SAMPLE_YAML.format(dxf=tmp_path / "o.dxf", html=tmp_path / "o.html")
    text = text.replace("mesh: {cell_size_x_m: 5.0, cell_size_y_m: 5.0}",
                        "mesh: {cell_size_x_m: 5.0, cell_size_y_m: 5.0, envelope_family: ridge}")
    config.write_text(text, encoding="utf-8")
    project = load_project(str(config))
    assert project.options.envelope_family == "ridge"


def test_envelope_family_defaults_to_voxel(tmp_path):
    config = tmp_path / "p.yaml"
    config.write_text(SAMPLE_YAML.format(dxf=tmp_path / "o.dxf", html=tmp_path / "o.html"),
                      encoding="utf-8")
    project = load_project(str(config))
    assert project.options.envelope_family == "voxel"


def test_cli_envelope_flag_selects_roof_pattern(tmp_path, capsys):
    from mve.cli import main
    dxf, html = tmp_path / "o.dxf", tmp_path / "o.html"
    config = tmp_path / "p.yaml"
    config.write_text(SAMPLE_YAML.format(dxf=dxf, html=html), encoding="utf-8")

    assert main([str(config), "--envelope", "lean_to"]) == 0
    assert "逆日影" in capsys.readouterr().out


def test_cli_rejects_unknown_envelope(tmp_path, capsys):
    """argparse の choices が弾く（0以外の終了コードで止まる）。"""
    from mve.cli import main
    config = tmp_path / "p.yaml"
    config.write_text(SAMPLE_YAML.format(dxf=tmp_path / "o.dxf", html=tmp_path / "o.html"),
                      encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(config), "--envelope", "hip"])
    assert exc.value.code != 0
