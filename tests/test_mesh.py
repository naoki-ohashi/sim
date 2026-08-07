import math

import pytest
from shapely.geometry import Polygon

from jwcad_volume.massing import Block
from jwcad_volume.mesh import (
    Axonometric,
    Face,
    blocks_to_edges,
    blocks_to_faces,
    merge_identical_footprints,
    site_edges,
)

SQ10 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
SQ6 = Polygon([(2, 2), (8, 2), (8, 8), (2, 8)])


def test_merge_identical_footprints_collapses_contiguous_same_shape():
    blocks = [
        Block(footprint=SQ10, z_bottom=0.0, z_top=3.0),
        Block(footprint=SQ10, z_bottom=3.0, z_top=6.0),
        Block(footprint=SQ6, z_bottom=6.0, z_top=9.0),
    ]
    merged = merge_identical_footprints(blocks)
    assert len(merged) == 2
    assert (merged[0].z_bottom, merged[0].z_top) == pytest.approx((0.0, 6.0))
    assert merged[1].footprint.area == pytest.approx(36.0)


def test_merge_keeps_non_contiguous_blocks_separate():
    blocks = [
        Block(footprint=SQ10, z_bottom=0.0, z_top=3.0),
        Block(footprint=SQ10, z_bottom=5.0, z_top=8.0),  # 間が空いている
    ]
    assert len(merge_identical_footprints(blocks)) == 2


def test_merge_empty_list():
    assert merge_identical_footprints([]) == []


def test_blocks_to_faces_counts_walls_top_and_bottom():
    blocks = [Block(footprint=SQ10, z_bottom=0.0, z_top=5.0)]
    faces = blocks_to_faces(blocks)
    # 四角形なので側面4枚 + 上面1枚 + 底面1枚
    assert len(faces) == 6
    assert sum(1 for f in faces if f.kind == "wall") == 4
    assert sum(1 for f in faces if f.kind == "top") == 1


def test_face_normal_points_up_for_top_face():
    faces = blocks_to_faces([Block(footprint=SQ10, z_bottom=0.0, z_top=5.0)])
    top = next(f for f in faces if f.kind == "top")
    assert top.normal() == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)


def test_face_normal_points_down_for_bottom_face():
    faces = blocks_to_faces([Block(footprint=SQ10, z_bottom=0.0, z_top=5.0)])
    bottom = next(f for f in faces if f.kind == "bottom")
    assert bottom.normal() == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)


def test_wall_normals_point_outward():
    faces = blocks_to_faces([Block(footprint=SQ10, z_bottom=0.0, z_top=5.0)])
    for wall in (f for f in faces if f.kind == "wall"):
        nx, ny, nz = wall.normal()
        assert nz == pytest.approx(0.0, abs=1e-9)
        # 面の中心から法線方向へ進むと敷地の外へ出る＝外向き
        cx = sum(v[0] for v in wall.vertices) / len(wall.vertices)
        cy = sum(v[1] for v in wall.vertices) / len(wall.vertices)
        assert not SQ10.contains(
            __import__("shapely.geometry", fromlist=["Point"]).Point(cx + nx * 0.1, cy + ny * 0.1)
        )


def test_blocks_to_edges_has_outline_and_vertical_edges():
    edges = blocks_to_edges([Block(footprint=SQ10, z_bottom=0.0, z_top=5.0)])
    assert sum(1 for e in edges if e.kind == "outline") == 4
    assert sum(1 for e in edges if e.kind == "vertical") == 4


def test_site_edges_closes_the_ring():
    edges = site_edges([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert len(edges) == 4
    assert all(e.p1[2] == 0.0 and e.p2[2] == 0.0 for e in edges)
    assert edges[-1].p2 == (0.0, 0.0, 0.0)  # 最後が始点に戻る


# --- 軸測投影 ---------------------------------------------------------

def test_projection_at_zero_elevation_is_pure_elevation_view():
    axo = Axonometric(azimuth_deg=0.0, elevation_deg=0.0)
    # 真横から見るので、高さがそのまま画面の上下になる
    assert axo.project((0.0, 0.0, 7.0))[1] == pytest.approx(7.0)
    # 奥行き方向(+Y)は画面上では動かない
    assert axo.project((0.0, 5.0, 0.0))[1] == pytest.approx(0.0)


def test_projection_at_ninety_elevation_is_plan_view():
    axo = Axonometric(azimuth_deg=0.0, elevation_deg=90.0)
    # 真上から見るので平面図になる（高さは画面上の位置に影響しない）
    assert axo.project((3.0, 4.0, 0.0)) == pytest.approx((3.0, 4.0))
    assert axo.project((3.0, 4.0, 50.0)) == pytest.approx((3.0, 4.0))


def test_higher_points_are_nearer_when_looking_down():
    axo = Axonometric(azimuth_deg=225.0, elevation_deg=30.0)
    assert axo.depth((0.0, 0.0, 20.0)) < axo.depth((0.0, 0.0, 0.0))


def test_projection_preserves_vertical_lines_as_vertical():
    axo = Axonometric(azimuth_deg=225.0, elevation_deg=30.0)
    bottom = axo.project((5.0, 5.0, 0.0))
    top = axo.project((5.0, 5.0, 10.0))
    # 平行投影では鉛直線は画面上でも鉛直（建築の軸測図の性質）
    assert bottom[0] == pytest.approx(top[0])
    assert top[1] > bottom[1]


def test_project_edges_keeps_kind():
    edges = site_edges([(0, 0), (10, 0), (10, 10), (0, 10)])
    projected = Axonometric().project_edges(edges)
    assert len(projected) == 4
    assert all(kind == "site" for _, _, kind in projected)
