"""JW-CAD（JWW）がDXFを読めるための条件を固定するテスト.

以前、R2010・LWPOLYLINE・m単位で書き出していたため、JWWで読み込んでも
図面に何も表示されませんでした。同じことが起きないよう、書式そのものを
検証します。根拠は `mve/io/dxf_pen.py` の説明を参照。
"""
import ezdxf
import pytest

from mve.io.dxf_pen import JwwDrawing
from mve.io.drawing import write_dxf

from .test_io import _result  # 同じサンプル敷地を使う


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    path = tmp_path_factory.mktemp("jww") / "out.dxf"
    write_dxf(_result(), str(path))
    return path


def test_version_is_r12(dxf):
    """R2000以降はJWWが読めないことがある。"""
    assert ezdxf.readfile(str(dxf)).dxfversion == "AC1009"


def test_only_lines_and_text(dxf):
    """LWPOLYLINEはR14以降の要素で、JWWは読み飛ばす（＝図面が真っ白になる）。"""
    kinds = {e.dxftype() for e in ezdxf.readfile(str(dxf)).modelspace()}
    assert kinds <= {"LINE", "TEXT"}, kinds


def test_coordinates_are_millimetres(dxf):
    """JWWはmmで作図する。mのまま渡すと1/1000の大きさになり見えない。"""
    msp = ezdxf.readfile(str(dxf)).modelspace()
    site = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MVE-SITE"]
    xs = [v for e in site for v in (e.dxf.start.x, e.dxf.end.x)]
    # サンプル敷地は間口30m → 30000mm
    assert max(xs) - min(xs) == pytest.approx(30000.0)


def test_japanese_text_is_shift_jis(dxf):
    """cp1252のままだと \\U+XXXX に化けてJWWで読めない。"""
    raw = dxf.read_bytes()
    assert "敷地面積".encode("cp932") in raw
    assert b"\\U+" not in raw
    assert b"ANSI_932" in raw


def test_text_height_scales_with_units():
    """文字高さも図面単位に合わせて変換される（mで渡してmmで出る）。"""
    pen = JwwDrawing()
    pen.add_layer("T")
    pen.text("A", (0, 0), 0.5, "T")
    text = next(iter(pen.msp))
    assert text.dxf.height == pytest.approx(500.0)


def test_units_can_be_overridden_for_metre_drawings(tmp_path):
    """mで作図している図面に合わせたい場合は 1 を指定できる。"""
    path = tmp_path / "m.dxf"
    write_dxf(_result(), str(path), units_per_meter=1.0)
    msp = ezdxf.readfile(str(path)).modelspace()
    site = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MVE-SITE"]
    xs = [v for e in site for v in (e.dxf.start.x, e.dxf.end.x)]
    assert max(xs) - min(xs) == pytest.approx(30.0)


def test_closed_shapes_are_actually_closed(dxf):
    """折れ線をLINEに分解しても、閉じた形は閉じたままであること。"""
    msp = ezdxf.readfile(str(dxf)).modelspace()
    site = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MVE-SITE"]
    # 各頂点はちょうど2本の線に共有される＝閉じている
    counts: dict[tuple[float, float], int] = {}
    for e in site:
        for p in (e.dxf.start, e.dxf.end):
            key = (round(p.x, 6), round(p.y, 6))
            counts[key] = counts.get(key, 0) + 1
    assert all(n == 2 for n in counts.values()), counts


def test_view_is_zoomed_to_the_drawing(dxf):
    """開いた直後に図面全体が見えるよう、表示範囲を合わせてある。"""
    vp = ezdxf.readfile(str(dxf)).viewports.get("*Active")[0]
    assert vp.dxf.height > 1000.0     # mm。既定の420x297のままではない
