"""外部変形エントリポイントのテスト。

JWWが渡してくるであろう JWC_TEMP.TXT を模したファイルを作り、
読み取り→計算→書き戻しまでを通しで確認します。実機JWWでの検証では
ないため、書式そのものの正しさは保証しません（docs/jww_integration.md）。
"""
import pytest

from jwcad_volume.gaihen import (
    GaihenParams,
    load_gaihen_params,
    main,
    run,
    site_from_jwc,
)
from jwcad_volume.jwc import parse_jwc
from jwcad_volume.ring_builder import RingBuildError
from jwcad_volume.zoning import ZoningParams

# 30m x 20m、南に道路(線色1)、東西が隣地(線色2)、北が北側境界(線色3)
SITE_JWC = """# jw_win
lc1
0 0 30000 0
lc2
30000 0 30000 20000
lc3
30000 20000 0 20000
lc2
0 20000 0 0
"""

PARAMS_YAML = """
boundary_colors:
  road: 1
  adjacent: 2
  north: 3
road_width_m: 6.0
floor_height_m: 3.2
units_per_meter: 1000.0
zoning:
  zone_type: 1res
  far_ratio: 2.0
  coverage_ratio: 0.6
envelope:
  n_layers: 5
  interval_m: 10.0
  n_azimuth: 20
  use_sky_ratio: false
  search_iterations: 4
"""


def _write(tmp_path, name, content, encoding="shift_jis"):
    path = tmp_path / name
    path.write_text(content, encoding=encoding)
    return path


def _params(tmp_path):
    return load_gaihen_params(str(_write(tmp_path, "gaihen_params.yaml", PARAMS_YAML, "utf-8")))


def test_load_gaihen_params_defaults_and_overrides(tmp_path):
    params = _params(tmp_path)
    assert params.boundary_colors == {"road": 1, "adjacent": 2, "north": 3}
    assert params.road_width_m == 6.0
    assert params.zoning.zone_type == "1res"
    assert params.envelope.n_layers == 5
    assert params.shadow is None  # セクション無しなら日影チェックなし


def test_site_from_jwc_maps_colors_to_boundary_kinds(tmp_path):
    temp = _write(tmp_path, "JWC_TEMP.TXT", SITE_JWC)
    site = site_from_jwc(str(temp), _params(tmp_path))

    assert site.area_m2 == pytest.approx(600.0)  # 30m x 20m
    kinds = sorted(e.kind for e in site.edges)
    assert kinds == ["adjacent", "adjacent", "north", "road"]

    road_edge = next(e for e in site.edges if e.kind == "road")
    assert road_edge.road_width_m == pytest.approx(6.0)
    # 道路は南側(y=0)の辺
    assert road_edge.p1[1] == pytest.approx(0.0)
    assert road_edge.p2[1] == pytest.approx(0.0)


def test_site_from_jwc_unmapped_color_becomes_none(tmp_path):
    jwc = SITE_JWC.replace("lc3", "lc9")  # 割り当てのない線色
    temp = _write(tmp_path, "JWC_TEMP.TXT", jwc)
    site = site_from_jwc(str(temp), _params(tmp_path))
    assert sorted(e.kind for e in site.edges) == ["adjacent", "adjacent", "none", "road"]


def test_site_from_jwc_respects_units_per_meter(tmp_path):
    # m単位で作図している図面（units_per_meter: 1）
    yaml_m = PARAMS_YAML.replace("units_per_meter: 1000.0", "units_per_meter: 1.0")
    params = load_gaihen_params(str(_write(tmp_path, "p.yaml", yaml_m, "utf-8")))
    jwc = "lc1\n0 0 30 0\nlc2\n30 0 30 20\nlc3\n30 20 0 20\nlc2\n0 20 0 0\n"
    temp = _write(tmp_path, "JWC_TEMP.TXT", jwc)
    site = site_from_jwc(str(temp), params)
    assert site.area_m2 == pytest.approx(600.0)


def test_site_from_jwc_rejects_drawing_with_no_lines(tmp_path):
    temp = _write(tmp_path, "JWC_TEMP.TXT", "# jw_win\nci 0 0 1000\n")
    with pytest.raises(RingBuildError, match="線分が見つかりません"):
        site_from_jwc(str(temp), _params(tmp_path))


def test_run_overwrites_temp_file_with_result(tmp_path):
    temp = _write(tmp_path, "JWC_TEMP.TXT", SITE_JWC)
    params_path = _write(tmp_path, "gaihen_params.yaml", PARAMS_YAML, "utf-8")

    summary = run(str(temp), str(params_path))
    assert "敷地600.0m2" in summary

    written = temp.read_text(encoding="shift_jis")
    doc = parse_jwc(written)
    assert len(doc.lines) > 4  # 敷地 + 各段の輪郭
    assert any(line.startswith("ch ") for line in doc.unknown)  # サマリー文字


def test_main_returns_zero_and_writes_result(tmp_path):
    temp = _write(tmp_path, "JWC_TEMP.TXT", SITE_JWC)
    params_path = _write(tmp_path, "gaihen_params.yaml", PARAMS_YAML, "utf-8")
    rc = main([str(temp), "--params", str(params_path)])
    assert rc == 0
    assert "lc" in temp.read_text(encoding="shift_jis")


def test_main_reports_error_without_corrupting_output(tmp_path, capsys):
    # 開いた形状（1辺欠け）→ エラーになるが、JWWへは壊れた図形を返さない
    broken = "\n".join(SITE_JWC.splitlines()[:-1])
    temp = _write(tmp_path, "JWC_TEMP.TXT", broken)
    params_path = _write(tmp_path, "gaihen_params.yaml", PARAMS_YAML, "utf-8")

    rc = main([str(temp), "--params", str(params_path)])
    assert rc == 1

    written = temp.read_text(encoding="shift_jis")
    assert "jwcad-volume error" in written
    assert parse_jwc(written).lines == []  # 図形は1本も返さない
    assert "エラー" in capsys.readouterr().err


def test_main_reports_missing_params_file(tmp_path):
    temp = _write(tmp_path, "JWC_TEMP.TXT", SITE_JWC)
    rc = main([str(temp), "--params", str(tmp_path / "存在しない.yaml")])
    assert rc == 1
    assert "error" in temp.read_text(encoding="shift_jis")
