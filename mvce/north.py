"""真北の扱い.

敷地図は測量座標や任意の向きで作られるため、図面の上方向（+Y）が真北とは
限りません。北側斜線制限（法56条1項3号）と日影規制（法56条の2）はどちらも
真北を基準に決まるので、図面座標と真北の関係を明示的に持ちます。

`north_angle_deg` は「**真北**が図面上でどちらを向いているか」を、+Y軸から
反時計回りの角度（度）で表します。座標北（平面直角座標系の +X 方向）では
ありません。両者は子午線収差角のぶんだけずれます（`crs.py`）。

    0   … 図面の上が真北（既定）
    90  … 図面の左が真北
    -15 … 真北が図面の上から時計回りに15度ずれている

方位角（azimuth）は本パッケージ共通で「真北から時計回り、0〜360度」です。

GIS 由来の敷地（JGD2011 平面直角座標系）では `resolve_north()` に
`CrsContext` を渡すと、子午線収差角から真北を自動で決められます。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .crs import CrsContext
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


#: 手入力の真北と、座標系から計算した真北の差がこれを超えたら注記を出す。
#: 子午線収差角は日本の各系で最大 0.9 度ほどなので、0.1 度あれば
#: 「入力ミス」と「収差角ぶんのずれ」を取り違えずに済みます。
NORTH_DISAGREEMENT_TOLERANCE_DEG = 0.1


def resolve_north(
    crs: Optional[CrsContext] = None,
    manual_north_angle_deg: Optional[float] = None,
) -> Tuple[NorthReference, List[str]]:
    """真北を決める。決めた根拠を注記として一緒に返す。

    - 座標系だけ与えられた場合、子午線収差角から真北を計算します。
    - 手入力の角度だけ与えられた場合、それをそのまま使います。
    - 両方与えられた場合、**手入力を優先**し、両者の差を注記に出します
      （基本設計 4.6）。図面の真北記号が測量成果より確からしいことも、
      その逆もあるため、engine 側で勝手に選びません。
    - どちらも無い場合、`north_angle_deg = 0`（図面の上が真北）に
      なりますが、それは仮定であることを注記に出します。

    真北の取り違えは北側斜線と日影規制に直接効きます。1度で 30m 先の
    52cm。黙って既定値を使わないための関数です。
    """
    notes: List[str] = []

    computed = crs.true_north_angle_deg() if crs is not None else None

    if manual_north_angle_deg is not None:
        angle = float(manual_north_angle_deg)
        if computed is not None:
            gap = angle - computed
            notes.append(
                f"真北は手入力値 {angle:+.4f}度 を採用しました。"
                f"{crs.zone.label} の子午線収差角から計算すると {computed:+.4f}度 で、"
                f"差は {gap:+.4f}度 です"
            )
            if abs(gap) > NORTH_DISAGREEMENT_TOLERANCE_DEG:
                notes.append(
                    f"手入力の真北と座標系から計算した真北が "
                    f"{NORTH_DISAGREEMENT_TOLERANCE_DEG}度 を超えてずれています。"
                    f"図面の真北記号が座標北を指している（収差角が未補正）か、"
                    f"敷地座標の系番号が違う可能性があります"
                )
        else:
            notes.append(f"真北は手入力値 {angle:+.4f}度 を採用しました")
        return NorthReference(angle), notes

    if computed is not None:
        notes.append(
            f"真北は {crs.zone.label} の子午線収差角から {computed:+.4f}度 と"
            f"しました（座標北ではありません）"
        )
        return NorthReference(computed), notes

    notes.append(
        "真北の指定が無いため、図面の +Y を真北と仮定しました。"
        "北側斜線と日影規制はこの仮定に依存します"
    )
    return NorthReference(0.0), notes
