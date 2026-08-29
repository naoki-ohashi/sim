"""ブラウザ版DXF書き出し（web/mvce/dxf.js）がJW-CAD（JWW）で読めることの検証.

Python版の検証（test_jww_dxf_compat.py）と同じ観点を、Node.jsで実際に
web/mvce/dxf.jsを走らせた出力に対して確認する。CP932への変換は
cp932_table.js（Python cp932コーデックから生成した変換テーブル）を使うため、
実際にPython側のcp932コーデックと一致しているかもここで確認する。
"""
import json
import shutil
import subprocess
from pathlib import Path

import ezdxf
import pytest

from mvce.regulations.shadow import ShadowRegulationSpec

from .test_js_parity import _js_shadow, _js_site, _site

RUNNER = Path(__file__).parent / "js_dxf_runner.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js が無い環境ではスキップ")


def _build_dxf(tmp_path, payload, name="out.dxf"):
    path = tmp_path / name
    result = subprocess.run(["node", str(RUNNER), str(path)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssertionError(f"JS実行に失敗:\n{result.stderr}")
    return path


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("js_dxf")
    site = _site(far=4.0)
    spec = ShadowRegulationSpec(
        measurement_height_m=4.0, line_5m_max_hours=5.0, line_10m_max_hours=3.0,
        time_step_minutes=30.0, sample_interval_m=6.0)
    payload = {
        "site": _js_site(site), "shadowSpec": _js_shadow(spec),
        "meshOptions": {"cellSizeXM": 5.0, "cellSizeYM": 5.0, "coverageThreshold": 0.5},
        "isochroneLevels": [2.0, 3.0], "isochroneIntervalM": 4.0, "isochroneMarginM": 12.0,
    }
    return _build_dxf(tmp_path, payload)


@pytest.fixture(scope="module")
def dxf_no_shadow(tmp_path_factory):
    """日影規制なしの敷地（MVE-SITEレイヤに、みなし境界線の重複が乗らない）。"""
    tmp_path = tmp_path_factory.mktemp("js_dxf_no_shadow")
    payload = {
        "site": _js_site(_site()),
        "meshOptions": {"cellSizeXM": 5.0, "cellSizeYM": 5.0, "coverageThreshold": 0.5},
    }
    return _build_dxf(tmp_path, payload, "no_shadow.dxf")


def test_version_is_r12(dxf):
    assert ezdxf.readfile(str(dxf)).dxfversion == "AC1009"


def test_only_lines_and_text(dxf):
    kinds = {e.dxftype() for e in ezdxf.readfile(str(dxf)).modelspace()}
    assert kinds <= {"LINE", "TEXT"}, kinds


def test_coordinates_are_millimetres(dxf):
    msp = ezdxf.readfile(str(dxf)).modelspace()
    site = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MVE-SITE"]
    xs = [v for e in site for v in (e.dxf.start.x, e.dxf.end.x)]
    # SQUARE敷地は間口30m → 30000mm
    assert max(xs) - min(xs) == pytest.approx(30000.0)


def test_japanese_text_is_shift_jis(dxf):
    raw = dxf.read_bytes()
    assert "敷地面積".encode("cp932") in raw
    assert "時間".encode("cp932") in raw   # 等時間日影図のラベル
    assert b"\\U+" not in raw
    assert b"ANSI_932" in raw


def test_closed_shapes_are_actually_closed(dxf_no_shadow):
    """日影のみなし境界線が同じMVE-SITEレイヤに重ねて描かれるため、
    このテストは日影規制なしの図面で確認する（Python版と同じ前提）。
    """
    msp = ezdxf.readfile(str(dxf_no_shadow)).modelspace()
    site = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MVE-SITE"]
    counts: dict[tuple[float, float], int] = {}
    for e in site:
        for p in (e.dxf.start, e.dxf.end):
            key = (round(p.x, 6), round(p.y, 6))
            counts[key] = counts.get(key, 0) + 1
    assert all(n == 2 for n in counts.values()), counts


def test_extents_describe_the_drawing(dxf):
    doc = ezdxf.readfile(str(dxf))
    lo, hi = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
    xs, ys = [], []
    for e in doc.modelspace():
        if e.dxftype() == "LINE":
            xs += [e.dxf.start.x, e.dxf.end.x]
            ys += [e.dxf.start.y, e.dxf.end.y]
        elif e.dxftype() == "TEXT":
            xs.append(e.dxf.insert.x)
            ys.append(e.dxf.insert.y)
    assert lo[0] == pytest.approx(min(xs)) and lo[1] == pytest.approx(min(ys))
    assert hi[0] == pytest.approx(max(xs)) and hi[1] == pytest.approx(max(ys))


def test_layer_names_are_uppercase_and_valid(dxf):
    names = [layer.dxf.name for layer in ezdxf.readfile(str(dxf)).layers]
    assert "MVE-ISOCHRONE-2H" in names
    assert "MVE-ISOCHRONE-3H" in names
    assert all(len(n) <= 31 for n in names)
    assert all(c.isalnum() or c in "$-_" for n in names for c in n)


def test_units_can_be_overridden_for_metre_drawings(tmp_path):
    site = _site()
    payload = {"site": _js_site(site),
              "meshOptions": {"cellSizeXM": 5.0, "cellSizeYM": 5.0, "coverageThreshold": 0.5},
              "unitsPerMeter": 1.0}
    path = _build_dxf(tmp_path, payload, "m.dxf")
    msp = ezdxf.readfile(str(path)).modelspace()
    site_lines = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MVE-SITE"]
    xs = [v for e in site_lines for v in (e.dxf.start.x, e.dxf.end.x)]
    assert max(xs) - min(xs) == pytest.approx(30.0)


def test_checker_accepts_our_output(dxf, capsys):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.check_dxf import main

    assert main([str(dxf)]) == 0
    assert "JWWで読めるはずです" in capsys.readouterr().out


def test_cp932_table_matches_python_codec():
    """cp932_table.js の変換テーブルが、生成元のPythonコーデックと一致していること。"""
    table_path = Path(__file__).resolve().parents[2] / "web" / "mvce" / "cp932_table.js"
    raw = table_path.read_text(encoding="utf-8")
    marker = "CP932_ENCODE_TABLE = {"
    start = raw.index(marker) + len(marker)
    end = raw.index("\n};", start)
    # 素朴な "数値:数値,数値:数値,..." の並びなのでJSONではなく直接パースする
    table = {}
    for entry in raw[start:end].strip().split(","):
        k, v = entry.split(":")
        table[k] = int(v)

    # 全件確認すると重いので、あちこちからサンプリングして照合する
    import random
    random.seed(0)
    keys = random.sample(list(table.keys()), 500)
    for key in keys:
        cp = int(key)
        expected = chr(cp).encode("cp932")
        value = table[key]
        if value > 255:
            actual = bytes([(value >> 8) & 0xFF, value & 0xFF])
        else:
            actual = bytes([value])
        assert actual == expected, (cp, key)
