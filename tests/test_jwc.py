import pytest

from jwcad_volume.jwc import JwcWriter, parse_jwc


def test_parse_line_converts_mm_to_meters():
    doc = parse_jwc("0 0 30000 0")
    assert len(doc.lines) == 1
    seg = doc.lines[0]
    assert (seg.x1, seg.y1, seg.x2, seg.y2) == pytest.approx((0.0, 0.0, 30.0, 0.0))


def test_parse_applies_state_lines_to_following_entities():
    text = "\n".join(["lc1", "0 0 1000 0", "lc2", "1000 0 1000 1000", "ly3", "0 0 0 1000"])
    doc = parse_jwc(text)
    assert [s.color for s in doc.lines] == [1, 2, 2]
    assert [s.layer for s in doc.lines] == [0, 0, 3]


def test_parse_collects_header_and_unknown_lines():
    text = "\n".join(["# jw_win", "0 0 1000 0", "ci 500 500 250", "何かの行"])
    doc = parse_jwc(text)
    assert doc.header == ["# jw_win"]
    assert len(doc.lines) == 1
    assert "ci 500 500 250" in doc.unknown
    assert "何かの行" in doc.unknown


def test_parse_unrecognized_single_token_goes_to_unknown():
    doc = parse_jwc("\n".join(["lc2", "sl", "0 0 1000 0"]))
    assert "sl" in doc.unknown
    assert doc.lines[0].color == 2  # 直前の状態は保たれる


def test_parse_hex_layer_group():
    doc = parse_jwc("\n".join(["lgA", "0 0 1000 0"]))
    assert doc.lines[0].layer_group == 10


def test_lines_by_color_groups_segments():
    text = "\n".join(["lc1", "0 0 1000 0", "lc3", "1000 0 1000 1000"])
    doc = parse_jwc(text)
    grouped = doc.lines_by_color()
    assert set(grouped) == {1, 3}
    assert len(grouped[1]) == 1


def test_writer_emits_state_only_when_changed():
    w = JwcWriter()
    w.set_attributes(color=2)
    w.add_line((0, 0), (1, 0))
    w.set_attributes(color=2)  # unchanged -> no new state line
    w.add_line((1, 0), (1, 1))
    out = w.getvalue().splitlines()
    assert out.count("lc2") == 1


def test_writer_roundtrip_through_parser():
    w = JwcWriter()
    w.set_attributes(color=5, layer=2)
    w.add_polyline([(0, 0), (10, 0), (10, 20)], close=True)
    doc = parse_jwc(w.getvalue())
    assert len(doc.lines) == 3  # closed triangle
    assert all(s.color == 5 and s.layer == 2 for s in doc.lines)
    assert doc.lines[0].p1 == pytest.approx((0.0, 0.0))
    assert doc.lines[-1].p2 == pytest.approx((0.0, 0.0))


def test_writer_uses_crlf_and_shift_jis(tmp_path):
    w = JwcWriter()
    w.add_comment("最大ボリューム")
    w.add_line((0, 0), (1, 1))
    path = tmp_path / "JWC_TEMP.TXT"
    w.save(str(path))
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert "最大ボリューム".encode("shift_jis") in raw
