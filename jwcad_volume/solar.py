"""Solar position (altitude/azimuth) as a function of true solar time.

日影規制 (shadow regulation) measurement hours (e.g. "8:00-16:00") are
specified in *true solar time* (真太陽時) at the site, i.e. the time base
where solar noon is exactly 12:00 by definition. That means the standard
hour-angle formula can be used directly against the given hour, with no
timezone / equation-of-time / longitude correction needed -- this module
never touches clock time at all, only true solar hours.
"""
from __future__ import annotations

import datetime
import math


def day_of_year(month: int, day: int) -> int:
    return datetime.date(2001, month, day).timetuple().tm_yday  # non-leap reference year


def solar_declination_deg(day_of_year_: int) -> float:
    """Cooper's equation approximation (accurate to within ~1 degree)."""
    return 23.45 * math.sin(math.radians(360.0 / 365.0 * (284 + day_of_year_)))


def solar_position_deg(latitude_deg: float, declination_deg: float, true_solar_hour: float) -> tuple[float, float]:
    """Returns (altitude_deg, azimuth_deg). Azimuth is compass bearing from
    true north, clockwise, matching this package's geometry convention.
    Altitude may be negative (sun below horizon)."""
    phi = math.radians(latitude_deg)
    delta = math.radians(declination_deg)
    H = math.radians(15.0 * (true_solar_hour - 12.0))

    sin_alt = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(H)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.asin(sin_alt)

    cos_alt = math.cos(alt)
    if cos_alt < 1.0e-9:
        # sun at zenith or exactly at horizon pole case; azimuth undefined, use south
        return math.degrees(alt), 180.0
    cos_gamma = (math.sin(alt) * math.sin(phi) - math.sin(delta)) / (cos_alt * math.cos(phi))
    cos_gamma = max(-1.0, min(1.0, cos_gamma))
    gamma = math.acos(cos_gamma)  # azimuth from south, unsigned
    if H < 0:
        gamma = -gamma  # morning: sun east of south
    azimuth_from_north = (180.0 + math.degrees(gamma)) % 360.0
    return math.degrees(alt), azimuth_from_north
