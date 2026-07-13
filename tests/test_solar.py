import pytest

from jwcad_volume.solar import day_of_year, solar_declination_deg, solar_position_deg

TOKYO_LAT = 35.7


def test_day_of_year_reference_dates():
    assert day_of_year(1, 1) == 1
    assert day_of_year(12, 31) == 365
    assert day_of_year(12, 22) in (355, 356)


def test_declination_near_solstices():
    summer = solar_declination_deg(day_of_year(6, 21))
    winter = solar_declination_deg(day_of_year(12, 22))
    assert summer == pytest.approx(23.45, abs=0.5)
    assert winter == pytest.approx(-23.45, abs=0.5)


def test_declination_near_equinox_is_near_zero():
    spring = solar_declination_deg(day_of_year(3, 20))
    assert spring == pytest.approx(0.0, abs=1.5)


def test_solar_noon_altitude_winter_solstice_tokyo():
    delta = solar_declination_deg(day_of_year(12, 22))
    alt, az = solar_position_deg(TOKYO_LAT, delta, 12.0)
    # expected altitude at solar noon = 90 - (lat - declination)
    expected = 90.0 - (TOKYO_LAT - delta)
    assert alt == pytest.approx(expected, abs=0.1)
    assert az == pytest.approx(180.0, abs=0.1)  # due south at solar noon


def test_solar_noon_altitude_summer_solstice_tokyo():
    delta = solar_declination_deg(day_of_year(6, 21))
    alt, az = solar_position_deg(TOKYO_LAT, delta, 12.0)
    expected = 90.0 - (TOKYO_LAT - delta)
    assert alt == pytest.approx(expected, abs=0.1)
    assert az == pytest.approx(180.0, abs=0.1)


def test_morning_sun_is_east_of_south_afternoon_west():
    delta = solar_declination_deg(day_of_year(12, 22))
    _, az_morning = solar_position_deg(TOKYO_LAT, delta, 9.0)
    _, az_afternoon = solar_position_deg(TOKYO_LAT, delta, 15.0)
    assert az_morning < 180.0  # east of south
    assert az_afternoon > 180.0  # west of south
    # symmetric around noon
    assert (180.0 - az_morning) == pytest.approx(az_afternoon - 180.0, abs=0.5)


def test_altitude_below_horizon_before_sunrise_or_after_sunset():
    delta = solar_declination_deg(day_of_year(12, 22))
    alt, _ = solar_position_deg(TOKYO_LAT, delta, 0.0)  # midnight, true solar time
    assert alt < 0.0
