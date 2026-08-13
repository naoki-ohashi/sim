import pytest

from mvce.north import NorthReference


def test_default_north_is_plan_up():
    n = NorthReference()
    assert n.north_vector == pytest.approx((0.0, 1.0), abs=1e-9)
    assert n.east_vector == pytest.approx((1.0, 0.0), abs=1e-9)


def test_rotated_north_vector():
    # 真北が図面の左を向く
    n = NorthReference(north_angle_deg=90.0)
    assert n.north_vector == pytest.approx((-1.0, 0.0), abs=1e-9)
    assert n.east_vector == pytest.approx((0.0, 1.0), abs=1e-9)


def test_azimuth_cardinal_directions_with_default_north():
    n = NorthReference()
    assert n.azimuth_of_vector((0, 1)) == pytest.approx(0.0)      # 北
    assert n.azimuth_of_vector((1, 0)) == pytest.approx(90.0)     # 東
    assert n.azimuth_of_vector((0, -1)) == pytest.approx(180.0)   # 南
    assert n.azimuth_of_vector((-1, 0)) == pytest.approx(270.0)   # 西


def test_azimuth_follows_rotated_north():
    n = NorthReference(north_angle_deg=90.0)
    # 図面の左が真北なので、図面の上(+Y)は真東になる
    assert n.azimuth_of_vector((-1, 0)) == pytest.approx(0.0)
    assert n.azimuth_of_vector((0, 1)) == pytest.approx(90.0)


def test_vector_for_azimuth_roundtrip():
    for angle in (0.0, 23.5, -40.0, 150.0):
        n = NorthReference(north_angle_deg=angle)
        for azimuth in (0.0, 45.0, 137.0, 300.0):
            v = n.vector_for_azimuth(azimuth)
            assert n.azimuth_of_vector(v) == pytest.approx(azimuth, abs=1e-6)


def test_azimuth_between_points():
    n = NorthReference()
    assert n.azimuth_between((0, 0), (10, 0)) == pytest.approx(90.0)


def test_faces_north_default_orientation():
    n = NorthReference()
    assert n.faces_north((0, 0), (10, 0), outward=(0, 1))       # 真北向き
    assert not n.faces_north((0, 0), (10, 0), outward=(0, -1))  # 真南向き


def test_faces_north_respects_rotated_north():
    n = NorthReference(north_angle_deg=90.0)  # 図面の左が真北
    assert n.faces_north((0, 0), (0, 10), outward=(-1, 0))
    assert not n.faces_north((0, 0), (0, 10), outward=(1, 0))
