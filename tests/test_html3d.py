import json
import re

import pytest

from jwcad_volume.envelope import compute_max_envelope
from jwcad_volume.output.html3d import build_viewer_html, write_viewer_html
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (30, 0), (30, 20), (0, 20)]
FAST = dict(n_layers=6, interval_m=10.0, n_azimuth=20, search_iterations=4, use_sky_ratio=False)


def _result():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    edges = [
        Boundary((0, 0), (30, 0), kind="road", road_width_m=6.0),
        Boundary((30, 0), (30, 20), kind="adjacent"),
        Boundary((30, 20), (0, 20), kind="north"),
        Boundary((0, 20), (0, 0), kind="adjacent"),
    ]
    return compute_max_envelope(Site(points=SQUARE, edges=edges, zoning=zoning), **FAST)


def _embedded_data(html: str) -> dict:
    match = re.search(r"JwcadVolumeViewer\.init\((\{.*\})\);\n", html)
    assert match, "埋め込みJSONが見つからない"
    return json.loads(match.group(1))


def test_html_is_self_contained_no_external_resources():
    html = build_viewer_html(_result())
    # CDN・外部ファイル参照が一切ないこと（オフラインで開けるのが要件）
    assert "http://" not in html
    assert "https://" not in html
    assert "<script src=" not in html
    assert "<link rel=\"stylesheet\"" not in html


def test_html_embeds_both_volume_sets():
    data = _embedded_data(build_viewer_html(_result()))
    assert data["final"], "最終ボリュームの面が空"
    assert data["baseline"], "斜線制限エンベロープの面が空"
    assert len(data["site"]) == 4


def test_embedded_faces_have_vertices_and_kind():
    data = _embedded_data(build_viewer_html(_result()))
    for face in data["final"]:
        assert len(face["v"]) >= 3
        assert all(len(vertex) == 3 for vertex in face["v"])
        assert face["k"] in {"wall", "top", "bottom"}


def test_geometry_is_recentred_on_the_site():
    # 敷地中心が原点に来ていないと、回転が敷地の外を軸に回ってしまう
    data = _embedded_data(build_viewer_html(_result()))
    xs = [p[0] for p in data["site"]]
    ys = [p[1] for p in data["site"]]
    assert (min(xs) + max(xs)) / 2 == pytest.approx(0.0, abs=1e-6)
    assert (min(ys) + max(ys)) / 2 == pytest.approx(0.0, abs=1e-6)
    assert data["radius"] > 0


def test_summary_is_japanese():
    data = _embedded_data(build_viewer_html(_result()))
    joined = "".join(data["summary"])
    assert "敷地面積" in joined
    assert "最高高さ" in joined


def test_title_is_used():
    html = build_viewer_html(_result(), title="テスト敷地")
    assert "<title>テスト敷地</title>" in html


def test_write_viewer_html_creates_utf8_file(tmp_path):
    path = tmp_path / "viewer.html"
    write_viewer_html(_result(), str(path))
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert "最大ボリューム" in text


def test_empty_result_still_produces_valid_html():
    zoning = ZoningParams(
        zone_type="1res", far_ratio=2.0, coverage_ratio=0.6, absolute_height_limit_m=0.0
    )
    edges = [Boundary(SQUARE[i], SQUARE[(i + 1) % 4], kind="none") for i in range(4)]
    result = compute_max_envelope(Site(points=SQUARE, edges=edges, zoning=zoning), **FAST)
    data = _embedded_data(build_viewer_html(result))
    assert data["final"] == []
    assert data["radius"] > 0  # ゼロ除算でスケール計算が壊れない
