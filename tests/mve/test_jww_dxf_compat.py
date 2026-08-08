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


def test_extents_describe_the_drawing(dxf):
    """図面の範囲($EXTMIN/$EXTMAX)が実際の図形に合っていること。

    読み込んだ側が「全体表示」で図面を画面に収められるようにするためです。
    既定のr12バックエンドはVPORT表を書かない（JW-CADが苦手なため）ので、
    範囲はヘッダで伝えます。
    """
    doc = ezdxf.readfile(str(dxf))
    lo, hi = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
    xs, ys = [], []
    for e in doc.modelspace():
        if e.dxftype() == "LINE":
            xs += [e.dxf.start.x, e.dxf.end.x]
            ys += [e.dxf.start.y, e.dxf.end.y]
        elif e.dxftype() == "TEXT":     # 要約の文字は敷地の下に置かれる
            xs.append(e.dxf.insert.x)
            ys.append(e.dxf.insert.y)
    assert lo[0] == pytest.approx(min(xs)) and lo[1] == pytest.approx(min(ys))
    assert hi[0] == pytest.approx(max(xs)) and hi[1] == pytest.approx(max(ys))
    assert hi[0] - lo[0] > 1000.0     # mm。実寸1m以上の図面になっている


def test_ezdxf_backend_still_zooms_its_viewport(tmp_path):
    """ezdxfバックエンドの方は、従来どおりVPORTで表示範囲を合わせる。"""
    from mve.io.drawing import write_dxf as w

    path = tmp_path / "ez.dxf"
    w(_result(), str(path), backend="ezdxf")
    vp = ezdxf.readfile(str(path)).viewports.get("*Active")[0]
    assert vp.dxf.height > 1000.0


def test_checker_accepts_our_output(dxf, capsys):
    """`tools/check_dxf.py` が、自分たちの出力を合格と判定すること。"""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from tools.check_dxf import main

    assert main([str(dxf)]) == 0
    assert "JWWで読めるはずです" in capsys.readouterr().out


def test_checker_rejects_the_old_broken_format(tmp_path, capsys):
    """以前の書式（R2010・LWPOLYLINE・m単位）はNGと判定されること。"""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from tools.check_dxf import main

    doc = ezdxf.new("R2010", setup=False)
    doc.layers.add("SITE")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (30, 0), (30, 20), (0, 20)], close=True, dxfattribs={"layer": "SITE"})
    path = tmp_path / "old.dxf"
    doc.saveas(str(path))

    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "LWPOLYLINE" in out
    assert "R12" in out


# --- 手書きR12ライター（外部ライブラリなし）------------------------------

def test_r12_backend_output_is_readable_and_equivalent(tmp_path):
    """`backend="r12"` の出力も、ezdxf版と同じ図面になること。"""
    from mve.io.drawing import write_dxf as w

    a, b = tmp_path / "r12.dxf", tmp_path / "ez.dxf"
    w(_result(), str(a), backend="r12")
    w(_result(), str(b), backend="ezdxf")

    def lines(path):
        return sorted(
            (round(e.dxf.start.x, 3), round(e.dxf.start.y, 3),
             round(e.dxf.end.x, 3), round(e.dxf.end.y, 3))
            for e in ezdxf.readfile(str(path)).modelspace() if e.dxftype() == "LINE")

    assert lines(a) == lines(b)


def test_r12_backend_avoids_what_jww_dislikes(tmp_path):
    """JW-CADが苦手な要素（小文字のテーブル名・ハンドル・余分な表）を出さない。"""
    from mve.io.drawing import write_dxf as w

    path = tmp_path / "r12.dxf"
    w(_result(), str(path), backend="r12")
    raw = path.read_bytes().decode("cp932")

    assert "CONTINUOUS" in raw and "Continuous" not in raw
    assert "STANDARD" in raw and "Standard" not in raw
    for table in ("VIEW", "UCS", "APPID", "DIMSTYLE", "VPORT"):
        assert f"  2\r\n{table}\r\n" not in raw, table
    import re
    assert not re.search(r"\r\n  5\r\n[0-9A-F]+\r\n", raw), "ハンドルが残っている"
    assert raw.endswith("  0\r\nEOF\r\n")


def test_r12_layer_names_are_uppercase_and_valid(tmp_path):
    """R12のレイヤ名は大文字・31文字以内・限られた文字だけ。"""
    from mve.io.dxf_r12 import R12Drawing

    pen = R12Drawing()
    pen.line((0, 0), (1, 1), "mve-plan-1")
    pen.line((0, 0), (1, 1), "変な/名前*です")
    names = [n for n in pen._layers]
    assert "MVE-PLAN-1" in names
    assert all(len(n) <= 31 for n in names)
    assert all(c.isalnum() or c in "$-_" for n in names for c in n)


def test_r12_writer_needs_no_ezdxf(monkeypatch, tmp_path):
    """ezdxf が無い環境でも書けること（外部ライブラリに依存しない）。"""
    import builtins
    from mve.io.dxf_r12 import R12Drawing

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("ezdxf"):
            raise ImportError("ezdxf は無い想定")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    pen = R12Drawing()
    pen.polyline([(0, 0), (10, 0), (10, 10)], "SITE")
    pen.text("日本語", (0, 0), 0.5, "SITE")
    path = tmp_path / "no_ezdxf.dxf"
    pen.save(str(path))
    assert path.stat().st_size > 0
    assert "日本語".encode("cp932") in path.read_bytes()
