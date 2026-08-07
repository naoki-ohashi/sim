import pytest

from jwcad_volume.envelope import compute_max_envelope
from jwcad_volume.output.isometric import default_origin, isometric_segments
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


def test_segments_include_all_three_kinds():
    kinds = {kind for _, _, kind in isometric_segments(_result())}
    assert kinds == {"site", "outline", "vertical"}


def test_site_ring_produces_four_segments():
    segments = isometric_segments(_result())
    assert sum(1 for _, _, k in segments if k == "site") == 4


def test_vertical_edges_stay_vertical_on_paper():
    # 平行投影では鉛直線は紙の上でも鉛直になる（軸測図として読める条件）
    for p1, p2, kind in isometric_segments(_result()):
        if kind == "vertical":
            assert p1[0] == pytest.approx(p2[0], abs=1e-9)


def test_origin_places_drawing_bottom_left_at_given_point():
    segments = isometric_segments(_result(), origin=(100.0, 50.0))
    xs = [c for s in segments for c in (s[0][0], s[1][0])]
    ys = [c for s in segments for c in (s[0][1], s[1][1])]
    assert min(xs) == pytest.approx(100.0)
    assert min(ys) == pytest.approx(50.0)


def test_default_origin_is_clear_of_the_plan():
    result = _result()
    ox, _ = default_origin(result)
    assert ox > max(p[0] for p in result.site.points)


def test_include_baseline_adds_more_segments():
    result = _result()
    without = isometric_segments(result, include_baseline=False)
    with_base = isometric_segments(result, include_baseline=True)
    assert len(with_base) > len(without)


def test_changing_view_angle_changes_projection():
    a = isometric_segments(_result(), azimuth_deg=225.0)
    b = isometric_segments(_result(), azimuth_deg=45.0)
    assert a != b


def test_top_down_view_reproduces_the_plan_outline():
    # 仰角90度は真上から見た図＝平面図と同じ形になるはず
    result = _result()
    segments = isometric_segments(result, azimuth_deg=0.0, elevation_deg=90.0)
    site = [(p1, p2) for p1, p2, k in segments if k == "site"]
    projected = {(round(p[0], 6), round(p[1], 6)) for pair in site for p in pair}
    expected = {(float(x), float(y)) for x, y in result.site.points}
    assert projected == expected


def test_empty_result_returns_no_segments_gracefully():
    zoning = ZoningParams(
        zone_type="1res", far_ratio=2.0, coverage_ratio=0.6, absolute_height_limit_m=0.0
    )
    edges = [Boundary(SQUARE[i], SQUARE[(i + 1) % 4], kind="none") for i in range(4)]
    result = compute_max_envelope(Site(points=SQUARE, edges=edges, zoning=zoning), **FAST)
    segments = isometric_segments(result)
    # ボリュームが無くても敷地の輪郭は描かれる
    assert all(kind == "site" for _, _, kind in segments)
