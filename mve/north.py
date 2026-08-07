"""真北の扱い.

敷地図は測量座標や任意の向きで作られるため、図面の上方向（+Y）が真北とは
限りません。北側斜線制限（法56条1項3号）と日影規制（法56条の2）はどちらも
真北を基準に決まるので、図面座標と真北の関係を明示的に持ちます。

`north_angle_deg` は「真北が図面上でどちらを向いているか」を、+Y軸から
反時計回りの角度（度）で表します。

    0   … 図面の上が真北（既定）
    90  … 図面の左が真北
    -15 … 真北が図面の上から時計回りに15度ずれている

方位角（azimuth）は本パッケージ共通で「真北から時計回り、0〜360度」です。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import Point


@dataclass(frozen=True)
class NorthReference:
    """図面座標と真北の関係。"""

    north_angle_deg: float = 0.0

    @property
    def north_vector(self) -> Point:
        """図面座標での真北の単位ベクトル。"""
        a = math.radians(self.north_angle_deg)
        # +Y から反時計回りに north_angle_deg 回した向き
        return (-math.sin(a), math.cos(a))

    @property
    def east_vector(self) -> Point:
        """真北に対する真東の単位ベクトル（図面座標）。"""
        nx, ny = self.north_vector
        return (ny, -nx)

    def azimuth_of_vector(self, vector: Point) -> float:
        """図面座標のベクトルの方位角（真北から時計回り、0〜360度）。"""
        nx, ny = self.north_vector
        ex, ey = self.east_vector
        north_comp = vector[0] * nx + vector[1] * ny
        east_comp = vector[0] * ex + vector[1] * ey
        azimuth = math.degrees(math.atan2(east_comp, north_comp)) % 360.0
        # atan2 の丸めで -1e-14 のような値が入ると % 360 が 360.0 に張り付く
        return 0.0 if azimuth >= 360.0 - 1e-9 else azimuth

    def azimuth_between(self, p_from: Point, p_to: Point) -> float:
        return self.azimuth_of_vector((p_to[0] - p_from[0], p_to[1] - p_from[1]))

    def vector_for_azimuth(self, azimuth_deg: float) -> Point:
        """方位角（真北から時計回り）に対応する図面座標の単位ベクトル。"""
        a = math.radians(azimuth_deg)
        nx, ny = self.north_vector
        ex, ey = self.east_vector
        return (nx * math.cos(a) + ex * math.sin(a), ny * math.cos(a) + ey * math.sin(a))

    def faces_north(self, p1: Point, p2: Point, outward: Point, tolerance_deg: float = 90.0) -> bool:
        """辺（外向き法線 `outward`）が真北側を向いているか。

        北側斜線をどの辺に適用するかの判定に使います。既定の許容90度は
        「真北成分が少しでもあれば北側とみなす」という保守側の判定です。
        """
        azimuth = self.azimuth_of_vector(outward)
        delta = min(azimuth, 360.0 - azimuth)  # 真北(0度)からのずれ
        return delta < tolerance_deg
