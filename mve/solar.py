"""太陽位置（真太陽時ベース）.

日影規制の測定時間は**真太陽時**（法56条の2、令135条の12）で定められて
います。真太陽時は「太陽が南中する時刻を12時とする」時刻系なので、
時差・均時差・経度補正は不要で、時角の式をそのまま使えます。本モジュールは
時計時刻を一切扱いません。

冬至日の測定時間帯:
    一般地域   真太陽時 8時〜16時
    北海道     真太陽時 9時〜15時（法56条の2別表第四の備考）
"""
from __future__ import annotations

import datetime
import math

WINTER_SOLSTICE = (12, 22)
HOKKAIDO_HOURS = (9.0, 15.0)
STANDARD_HOURS = (8.0, 16.0)


def day_of_year(month: int, day: int) -> int:
    return datetime.date(2001, month, day).timetuple().tm_yday  # 平年を基準にする


def solar_declination_deg(doy: int) -> float:
    """クーパーの式による太陽赤緯の近似（誤差は概ね1度以内）。"""
    return 23.45 * math.sin(math.radians(360.0 / 365.0 * (284 + doy)))


def winter_solstice_declination_deg() -> float:
    return solar_declination_deg(day_of_year(*WINTER_SOLSTICE))


def solar_position_deg(
    latitude_deg: float, declination_deg: float, true_solar_hour: float
) -> tuple[float, float]:
    """(高度, 方位角) を度で返す。

    方位角は真北から時計回り（本パッケージ共通の取り方）。高度は日の出前・
    日没後は負になります。
    """
    phi = math.radians(latitude_deg)
    delta = math.radians(declination_deg)
    hour_angle = math.radians(15.0 * (true_solar_hour - 12.0))

    sin_alt = (math.sin(phi) * math.sin(delta)
               + math.cos(phi) * math.cos(delta) * math.cos(hour_angle))
    altitude = math.asin(max(-1.0, min(1.0, sin_alt)))

    cos_alt = math.cos(altitude)
    if cos_alt < 1.0e-9:
        return math.degrees(altitude), 180.0
    cos_gamma = ((math.sin(altitude) * math.sin(phi) - math.sin(delta))
                 / (cos_alt * math.cos(phi)))
    gamma = math.acos(max(-1.0, min(1.0, cos_gamma)))
    if hour_angle < 0:
        gamma = -gamma  # 午前は東寄り
    return math.degrees(altitude), (180.0 + math.degrees(gamma)) % 360.0
