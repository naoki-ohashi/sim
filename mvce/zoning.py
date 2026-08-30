"""用途地域と法定テーブル.

収録している表:

- 別表第三（法56条1項1号）… 道路斜線の適用距離と勾配
- 別表第四（法56条の2）… 日影規制の対象建築物・規制時間・測定面
- 隣地斜線（法56条1項2号）… 立上り高さと勾配
- 北側斜線（法56条1項3号）… 立上り高さと勾配
- 法52条2項の低減係数（住居系4/10・その他6/10）

**規制時間・測定面・容積率・建蔽率は都市計画と条例で決まります。**
ここにあるのは法の枠組みと代表的な値で、実際に適用される数値は必ず
その敷地の都市計画図と自治体の条例で確認してください
（`ShadowRegulationSpec` は数値を明示的に渡す設計にしてあります）。
"""
from __future__ import annotations

from dataclasses import dataclass

# --- 用途地域の区分 -------------------------------------------------
LOW_RISE_ZONES = {"1low", "2low", "denen"}          # 第一種/第二種低層住居専用・田園住居
MID_RISE_ZONES = {"1mid", "2mid"}                   # 第一種/第二種中高層住居専用
OTHER_RESIDENTIAL_ZONES = {"1res", "2res", "quasi_res"}  # 第一種/第二種住居・準住居
RESIDENTIAL_ZONES = LOW_RISE_ZONES | MID_RISE_ZONES | OTHER_RESIDENTIAL_ZONES
COMMERCIAL_ZONES = {"neighbor_commercial", "commercial"}
INDUSTRIAL_ZONES = {"quasi_industrial", "industrial", "industrial_exclusive"}
UNSPECIFIED_ZONES = {"unspecified"}

ALL_ZONES = RESIDENTIAL_ZONES | COMMERCIAL_ZONES | INDUSTRIAL_ZONES | UNSPECIFIED_ZONES

ZONE_LABELS_JA = {
    "1low": "第一種低層住居専用地域", "2low": "第二種低層住居専用地域", "denen": "田園住居地域",
    "1mid": "第一種中高層住居専用地域", "2mid": "第二種中高層住居専用地域",
    "1res": "第一種住居地域", "2res": "第二種住居地域", "quasi_res": "準住居地域",
    "neighbor_commercial": "近隣商業地域", "commercial": "商業地域",
    "quasi_industrial": "準工業地域", "industrial": "工業地域",
    "industrial_exclusive": "工業専用地域", "unspecified": "用途地域の指定なし",
}


def zone_group(zone_type: str) -> str:
    """'residential'（住居系）か 'other'（その他）か。"""
    if zone_type in RESIDENTIAL_ZONES:
        return "residential"
    if zone_type in COMMERCIAL_ZONES | INDUSTRIAL_ZONES | UNSPECIFIED_ZONES:
        return "other"
    raise ValueError(f"不明な用途地域: {zone_type!r}（有効な値: {sorted(ALL_ZONES)}）")


# --- 法52条2項: 前面道路幅員による容積率の低減係数 -------------------
# 住居系 4/10、その他 6/10。特定行政庁が定める場合の割増は考慮していない。
FAR_ROAD_COEFFICIENT = {"residential": 0.4, "other": 0.6}
FAR_ROAD_WIDTH_THRESHOLD_M = 12.0  # これ以上の幅員なら指定容積率のまま


# --- 別表第三: 道路斜線の適用距離と勾配 ------------------------------
@dataclass(frozen=True)
class RoadSlantTier:
    far_upper: float | None   # この容積率（比）以下に適用。None は上限なし
    applicable_distance_m: float
    slope: float


# ⚠ **危険側の誤りが残っています**（`docs/mvce/legal_basis.md` の食い違い Q）
#
# 別表第三は5項あり、適用距離の刻みが3通りあります。この表は2群しか持って
# いないため、準工業・工業・工業専用（三の項）と用途地域の指定のない区域
# （五の項）に、近隣商業・商業（二の項）の表を当ててしまっています。
#
#   準工業 400% … 条文は 30m、この表は 20m
#   工業   300% … 条文は 25m、この表は 20m
#   無指定 400% … 条文は 30m、この表は 20m（勾配も 1.25 の場合がある）
#
# 適用距離が短いと道路斜線のかかる範囲が狭くなるので、**実際には通らない
# 建築物を適合と判定します**。5項に分けるまで、これらの用途地域の結果は
# 信用できません。一の項（住居系）と二の項（近隣商業・商業）は条文と
# 完全に一致しています。
ROAD_SLANT_TABLE: dict[str, list[RoadSlantTier]] = {
    "residential": [
        RoadSlantTier(2.0, 20.0, 1.25),
        RoadSlantTier(3.0, 25.0, 1.25),
        RoadSlantTier(4.0, 30.0, 1.25),
        RoadSlantTier(None, 35.0, 1.25),
    ],
    "other": [
        RoadSlantTier(4.0, 20.0, 1.5),
        RoadSlantTier(6.0, 25.0, 1.5),
        RoadSlantTier(8.0, 30.0, 1.5),
        RoadSlantTier(10.0, 35.0, 1.5),
        RoadSlantTier(11.0, 40.0, 1.5),
        RoadSlantTier(12.0, 45.0, 1.5),
        RoadSlantTier(None, 50.0, 1.5),
    ],
}


def road_slant_tier(zone_type: str, far_ratio: float) -> RoadSlantTier:
    for tier in ROAD_SLANT_TABLE[zone_group(zone_type)]:
        if tier.far_upper is None or far_ratio <= tier.far_upper:
            return tier
    raise AssertionError("到達しない: 最後の段は far_upper=None")


# --- 隣地斜線（法56条1項2号）----------------------------------------
# 低層住居専用・田園住居は絶対高さ制限（法55条）があるため隣地斜線の適用はない。
ADJACENT_SLANT_BY_GROUP: dict[str, tuple[float, float]] = {
    "residential": (20.0, 1.25),
    "other": (31.0, 2.5),
}


def adjacent_slant_params(zone_type: str) -> tuple[float, float] | None:
    """(立上り高さ, 勾配)。適用がない地域は None。"""
    if zone_type in LOW_RISE_ZONES:
        return None  # 絶対高さ制限が先に効くため隣地斜線の適用なし
    return ADJACENT_SLANT_BY_GROUP[zone_group(zone_type)]


# --- 北側斜線（法56条1項3号）----------------------------------------
NORTH_SLANT_ZONES: dict[str, tuple[float, float]] = {
    "1low": (5.0, 1.25), "2low": (5.0, 1.25), "denen": (5.0, 1.25),
    "1mid": (10.0, 1.25), "2mid": (10.0, 1.25),
}


def north_slant_params(zone_type: str) -> tuple[float, float] | None:
    return NORTH_SLANT_ZONES.get(zone_type)


# --- 別表第四: 日影規制の測定面と規制時間 ----------------------------
# 測定面は用途地域ごとに選択肢があり、どれになるかは条例で決まる。
#
# ⚠ 無指定（`unspecified`）に **6.5 が入っているのは誤り**です
# （食い違い R）。別表第四 四の項は イ=1.5m / ロ=4m の2択で、6.5m は
# ありません。測定面が高いほど日影は短く出るので危険側です。
ALLOWED_MEASUREMENT_HEIGHTS_M: dict[str, tuple[float, ...]] = {
    "1low": (1.5,), "2low": (1.5,), "denen": (1.5,),
    "1mid": (4.0, 6.5), "2mid": (4.0, 6.5),
    "1res": (4.0, 6.5), "2res": (4.0, 6.5), "quasi_res": (4.0, 6.5),
    "neighbor_commercial": (4.0, 6.5), "quasi_industrial": (4.0, 6.5),
    "unspecified": (1.5, 4.0, 6.5),
}
MEASUREMENT_HEIGHT_CHOICES_M = (1.5, 4.0, 6.5)

# 日影規制の対象となる建築物の基準（別表第四（ろ）欄）
#   低層住居専用・田園住居: 軒高7m超 または 地階を除く階数3以上
#   中高層住専・住居系・近隣商業・準工業: 高さ10m超
#   無指定: イ（軒高7m超 または 階数3以上）か ロ（高さ10m超）を条例で選ぶ
#
# ⚠ 未対応が2つあります（食い違い S）。どちらも危険側です。
#   1. 無指定を常に 10m 基準にしている。イの区域では 7m 基準
#   2. 「地階を除く階数が三以上」の**階数による基準**を見ていない。
#      軒高6mの3階建ては条文上は対象だが、この実装は対象外にする
SHADOW_TARGET_ZONES = set(ALLOWED_MEASUREMENT_HEIGHTS_M)
# 商業・工業・工業専用は日影規制の対象区域に指定できない
SHADOW_EXEMPT_ZONES = {"commercial", "industrial", "industrial_exclusive"}


def shadow_target_height_threshold_m(zone_type: str) -> float | None:
    """日影規制の対象になる建築物の高さ基準。対象外地域は None。"""
    if zone_type in SHADOW_EXEMPT_ZONES:
        return None
    if zone_type in LOW_RISE_ZONES:
        return 7.0   # 軒の高さ7m超（または地上3階以上）
    if zone_type in SHADOW_TARGET_ZONES:
        return 10.0  # 高さ10m超
    return None


@dataclass
class ZoningParams:
    """敷地に適用される用途地域と数値。"""

    zone_type: str
    far_ratio: float          # 都市計画で定められた容積率（比。200% なら 2.0）
    coverage_ratio: float     # 建蔽率（比。60% なら 0.6）
    absolute_height_limit_m: float | None = None  # 法55条の絶対高さ制限（10 or 12m）

    def __post_init__(self) -> None:
        if self.zone_type not in ALL_ZONES:
            raise ValueError(f"不明な用途地域: {self.zone_type!r}（有効: {sorted(ALL_ZONES)}）")
        if self.far_ratio <= 0:
            raise ValueError("far_ratio は正の値である必要があります")
        if not 0 < self.coverage_ratio <= 1.0:
            raise ValueError("coverage_ratio は 0 より大きく 1 以下である必要があります")
        if self.zone_type in LOW_RISE_ZONES and self.absolute_height_limit_m is None:
            # 低層住居専用・田園住居は法55条で10mまたは12mの制限が必ずある
            self.absolute_height_limit_m = 10.0

    @property
    def label_ja(self) -> str:
        return ZONE_LABELS_JA[self.zone_type]

    @property
    def group(self) -> str:
        return zone_group(self.zone_type)
