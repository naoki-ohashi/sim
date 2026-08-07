import pytest

from jwcad_volume.geometry import polygon_signed_area
from jwcad_volume.jwc import JwcLineSeg
from jwcad_volume.ring_builder import RingBuildError, build_ring


def _seg(p1, p2, color=1):
    return JwcLineSeg(x1=p1[0], y1=p1[1], x2=p2[0], y2=p2[1], color=color)


SQUARE_PTS = [(0, 0), (30, 0), (30, 20), (0, 20)]


def _square_segments(colors=(1, 2, 3, 2)):
    return [_seg(SQUARE_PTS[i], SQUARE_PTS[(i + 1) % 4], colors[i]) for i in range(4)]


def test_build_ring_from_ordered_segments():
    ring = build_ring(_square_segments())
    assert len(ring.points) == 4
    assert polygon_signed_area(ring.points) > 0  # CCW


def test_build_ring_from_shuffled_and_flipped_segments():
    segs = _square_segments()
    shuffled = [segs[2], segs[0], segs[3], segs[1]]
    # 向きを反転させた線分も混ぜる（作図方向はバラバラなのが普通）
    flipped = [_seg(s.p2, s.p1, s.color) if i % 2 else s for i, s in enumerate(shuffled)]
    ring = build_ring(flipped)
    assert len(ring.points) == 4
    assert set(ring.points) == set(SQUARE_PTS)


def test_ring_keeps_edge_color_correspondence():
    # 各辺に別々の色をつけ、並べ替え後も「点i->点i+1の辺の色」が保たれるか
    segs = [_seg(SQUARE_PTS[i], SQUARE_PTS[(i + 1) % 4], color=i + 1) for i in range(4)]
    ring = build_ring(list(reversed(segs)))
    n = len(ring.points)
    for i in range(n):
        p1 = ring.points[i]
        p2 = ring.points[(i + 1) % n]
        seg = ring.segments[i]
        assert {p1, p2} == {seg.p1, seg.p2}


def test_build_ring_snaps_endpoints_within_tolerance():
    # 角が1mmだけ離れている（作図誤差）
    segs = [
        _seg((0, 0), (30, 0)),
        _seg((30.001, 0), (30, 20)),
        _seg((30, 20), (0, 20)),
        _seg((0, 20), (0, 0)),
    ]
    ring = build_ring(segs, tolerance=0.01)
    assert len(ring.points) == 4


def test_build_ring_rejects_open_shape():
    segs = _square_segments()[:3]  # 1辺足りない
    with pytest.raises(RingBuildError, match="つながっています"):
        build_ring(segs)


def test_build_ring_rejects_too_few_segments():
    with pytest.raises(RingBuildError, match="3本以上"):
        build_ring([_seg((0, 0), (1, 0)), _seg((1, 0), (1, 1))])


def test_build_ring_rejects_two_separate_loops():
    far = [(100, 100), (130, 100), (130, 120), (100, 120)]
    segs = _square_segments() + [_seg(far[i], far[(i + 1) % 4]) for i in range(4)]
    with pytest.raises(RingBuildError, match="分かれています"):
        build_ring(segs)


def test_build_ring_rejects_branching_line():
    segs = _square_segments() + [_seg((0, 0), (-10, -10))]  # 余分な枝
    with pytest.raises(RingBuildError, match="3本つながっています"):
        build_ring(segs)


def test_build_ring_handles_non_rectangular_polygon():
    pts = [(0, 0), (40, 0), (40, 15), (20, 25), (0, 15)]
    segs = [_seg(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    ring = build_ring(segs)
    assert len(ring.points) == 5
    assert polygon_signed_area(ring.points) > 0
