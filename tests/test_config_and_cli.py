import ezdxf

from jwcad_volume.cli import main
from jwcad_volume.config import load_project

FAST_YAML = """
site:
  points:
    - [0, 0]
    - [30, 0]
    - [30, 30]
    - [0, 30]
  edges:
    - kind: road
      road_width_m: 6.0
    - kind: adjacent
    - kind: none
    - kind: none
  zoning:
    zone_type: 1res
    far_ratio: 2.0
    coverage_ratio: 0.6

envelope:
  n_layers: 6
  interval_m: 10.0
  n_azimuth: 30
  use_sky_ratio: true
  search_iterations: 8

output:
  dxf_path: {dxf_path}
"""


def test_load_project_parses_yaml(tmp_path):
    config_path = tmp_path / "site.yaml"
    config_path.write_text(FAST_YAML.format(dxf_path=str(tmp_path / "out.dxf")))
    project = load_project(str(config_path))
    assert project.site.zoning.zone_type == "1res"
    assert project.site.area_m2 == 900.0
    assert project.envelope.n_layers == 6
    assert project.shadow is None
    assert project.output.dxf_path == str(tmp_path / "out.dxf")


def test_cli_end_to_end_writes_dxf(tmp_path, capsys):
    dxf_path = tmp_path / "out.dxf"
    config_path = tmp_path / "site.yaml"
    config_path.write_text(FAST_YAML.format(dxf_path=str(dxf_path)))

    rc = main([str(config_path)])
    assert rc == 0
    assert dxf_path.exists()

    captured = capsys.readouterr()
    assert "volume:" in captured.out
    assert f"wrote {dxf_path}" in captured.out

    doc = ezdxf.readfile(str(dxf_path))
    assert any(e.dxftype() == "LWPOLYLINE" for e in doc.modelspace())


def test_cli_html_out_writes_viewer(tmp_path, capsys):
    dxf_path = tmp_path / "out.dxf"
    html_path = tmp_path / "viewer.html"
    config_path = tmp_path / "site.yaml"
    config_path.write_text(FAST_YAML.format(dxf_path=str(dxf_path)))

    rc = main([str(config_path), "--html-out", str(html_path)])
    assert rc == 0
    assert html_path.exists()
    assert "敷地面積" in html_path.read_text(encoding="utf-8")
    assert f"wrote {html_path}" in capsys.readouterr().out


def test_cli_html_path_from_config(tmp_path):
    dxf_path = tmp_path / "out.dxf"
    html_path = tmp_path / "from_config.html"
    config_path = tmp_path / "site.yaml"
    config_path.write_text(
        FAST_YAML.format(dxf_path=str(dxf_path)) + f"  html3d_path: {html_path}\n"
    )

    assert main([str(config_path)]) == 0
    assert html_path.exists()


def test_cli_dxf_out_override(tmp_path):
    dxf_path = tmp_path / "configured.dxf"
    override_path = tmp_path / "override.dxf"
    config_path = tmp_path / "site.yaml"
    config_path.write_text(FAST_YAML.format(dxf_path=str(dxf_path)))

    rc = main([str(config_path), "--dxf-out", str(override_path)])
    assert rc == 0
    assert override_path.exists()
    assert not dxf_path.exists()
