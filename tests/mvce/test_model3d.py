"""MVCE3 3Dモデル化（mvce/model3d/）のテスト。

FreeCAD・Blenderはこの環境にインストールされていないため、そちらの
バックエンドは「使えないときに正しく `Model3DBackendUnavailable` を
送出すること」だけを検証します（`model3d/__init__.py` のdocstring参照）。
`mesh` バックエンドは実際に書き出しまで検証します。
"""
import math

import pytest
from shapely.geometry import Polygon

from mvce.floors import FloorSlab
from mvce.model3d import BACKENDS, Model3DBackendUnavailable, build_model3d
from mvce.model3d.mesh_backend import build_obj
from mvce.model3d.solid import triangulate_simple_polygon
from mvce.solvers.optimizer import OptimizeOptions, optimize
from mvce.site import Site
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(far=2.0, coverage=0.6, zone="1res", road_width=6.0):
    specs = [
        {"kind": "road", "road_width_m": road_width},
        {"kind": "adjacent"},
        {"kind": "adjacent"},
        {"kind": "adjacent"},
    ]
    return Site.from_rings(SQUARE, specs, ZoningParams(zone, far, coverage))


def _result():
    return optimize(_site(), None, OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))


def _polygon_area_by_triangles(ring, triangles):
    def tri_area(a, b, c):
        return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2.0

    return sum(tri_area(ring[i], ring[j], ring[k]) for i, j, k in triangles)


# === 耳切り法（solid.py） =============================================

def test_triangulate_square_gives_two_triangles_with_full_area():
    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    tris = triangulate_simple_polygon(ring)
    assert len(tris) == 2
    assert _polygon_area_by_triangles(ring, tris) == pytest.approx(100.0)


def test_triangulate_concave_l_shape_covers_the_full_area():
    # L字型（凹多角形）。面積は 6x6 の正方形から 3x3 を欠いた 27。
    ring = [(0, 0), (6, 0), (6, 3), (3, 3), (3, 6), (0, 6)]
    poly = Polygon(ring)
    tris = triangulate_simple_polygon(ring)
    assert len(tris) == len(ring) - 2
    assert _polygon_area_by_triangles(ring, tris) == pytest.approx(poly.area)


def test_triangulate_accepts_clockwise_ring_too():
    ring_ccw = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    ring_cw = list(reversed(ring_ccw))
    tris = triangulate_simple_polygon(ring_cw)
    assert len(tris) == 2
    assert _polygon_area_by_triangles(ring_cw, tris) == pytest.approx(100.0)


def test_triangulate_degenerate_inputs_return_no_triangles():
    assert triangulate_simple_polygon([]) == []
    assert triangulate_simple_polygon([(0, 0), (1, 0)]) == []


# === mesh バックエンド =================================================

def test_mesh_backend_writes_obj_with_expected_vertex_and_face_counts(tmp_path):
    footprint = Polygon([(0, 0), (10, 0), (10, 8), (0, 8)])
    floor = FloorSlab(level=0, z_bottom=0.0, z_top=3.2, footprints=[footprint])
    out = tmp_path / "model.obj"

    stats = build_obj([floor], str(out))

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    v_lines = [l for l in text.splitlines() if l.startswith("v ")]
    f_lines = [l for l in text.splitlines() if l.startswith("f ")]
    # 4隅 x (下端+上端) = 8頂点
    assert len(v_lines) == 8
    assert stats.vertex_count == 8
    # 底面2三角形 + 天端2三角形 + 側面4四角形 = 8行
    assert len(f_lines) == 8
    assert stats.holes_ignored == 0


def test_mesh_backend_counts_holes_but_still_writes_exterior(tmp_path):
    footprint = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]],
    )
    floor = FloorSlab(level=0, z_bottom=0.0, z_top=3.0, footprints=[footprint])
    out = tmp_path / "with_hole.obj"

    stats = build_obj([floor], str(out))

    assert stats.holes_ignored == 1
    assert out.exists()
    # 中抜きを無視して外周だけの4頂点×2段=8頂点になっている
    assert stats.vertex_count == 8


def test_build_model3d_mesh_backend_end_to_end(tmp_path):
    result = _result()
    out = tmp_path / "building.obj"
    stats = build_model3d(result, str(out), backend="mesh")
    assert out.exists()
    assert stats["backend"] == "mesh"
    assert stats["floor_count"] > 0
    assert math.isfinite(stats["vertex_count"])


def test_build_model3d_rejects_unknown_backend():
    with pytest.raises(ValueError):
        build_model3d(_result(), "x.obj", backend="sketchup")


# === FreeCAD / Blender: 未導入時のガード ==============================
#
# このリポジトリの実行環境にはFreeCAD・Blenderが入っていないため、ここで
# 検証できるのは「無いときに Model3DBackendUnavailable が正しく送出される
# こと」だけです。実際のFreeCAD/Blenderでの動作は model3d/__init__.py の
# docstringのとおり未検証です。


def test_freecad_backend_unavailable_guard():
    import sys
    if "FreeCAD" in sys.modules:
        pytest.skip("FreeCADが読み込まれている環境では未導入ガードを検証できない")
    with pytest.raises(Model3DBackendUnavailable):
        build_model3d(_result(), "x.FCStd", backend="freecad")


def test_blender_backend_unavailable_guard():
    import sys
    if "bpy" in sys.modules:
        pytest.skip("bpyが読み込まれている環境では未導入ガードを検証できない")
    with pytest.raises(Model3DBackendUnavailable):
        build_model3d(_result(), "x.blend", backend="blender")


def test_backends_tuple_lists_all_three():
    assert set(BACKENDS) == {"mesh", "freecad", "blender"}
