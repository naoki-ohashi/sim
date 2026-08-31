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
# 原文は docs/mvce/statutes/建築基準法.md の別表第三。
#
# 表は5項あり、適用距離の刻みが3通りあります。用途地域を住居系／その他の
# 2群にまとめると、三の項（準工業・工業・工業専用）と五の項（無指定）に
# 二の項（近隣商業・商業）の刻みを当ててしまいます。三の項は上限が
# 35m なのに二の項は 50m まで伸びるので、同じ容積率でも距離が変わります。
# 適用距離を短く取ると道路斜線のかかる範囲が狭くなり、実際には通らない
# 建築物を適合と判定します。だから群ではなく項で持ちます。
@dataclass(frozen=True)
class RoadSlantTier:
    far_upper: float | None   # この容積率（比）以下に適用。None は上限なし
    applicable_distance_m: float
    slope: float | None       # None は「特定行政庁が定める」（五の項）


#: 用途地域 → 別表第三の項番号。
ROAD_SLANT_ROW_BY_ZONE: dict[str, int] = {
    # 一の項: 低層住専・中高層住専・田園住居・住居系
    "1low": 1, "2low": 1, "denen": 1, "1mid": 1, "2mid": 1,
    "1res": 1, "2res": 1, "quasi_res": 1,
    # 二の項: 近隣商業・商業
    "neighbor_commercial": 2, "commercial": 2,
    # 三の項: 準工業・工業・工業専用
    "quasi_industrial": 3, "industrial": 3, "industrial_exclusive": 3,
    # 四の項: 高層住居誘導地区（下記参照。用途地域ではないのでここには無い）
    # 五の項: 用途地域の指定のない区域
    "unspecified": 5,
}

#: 別表第三の項ごとの（容積率の上限, 適用距離, 勾配）。
#:
#: 四の項（高層住居誘導地区で住宅が延べ面積の2/3以上）は容積率による
#: 区分が無く 35m・1.5 の一段だけです。MVCE は高層住居誘導地区を入力
#: できないので今は到達しませんが、表の写しとして残しています。
ROAD_SLANT_TABLE: dict[int, list[RoadSlantTier]] = {
    1: [
        RoadSlantTier(2.0, 20.0, 1.25),
        RoadSlantTier(3.0, 25.0, 1.25),
        RoadSlantTier(4.0, 30.0, 1.25),
        RoadSlantTier(None, 35.0, 1.25),
    ],
    2: [
        RoadSlantTier(4.0, 20.0, 1.5),
        RoadSlantTier(6.0, 25.0, 1.5),
        RoadSlantTier(8.0, 30.0, 1.5),
        RoadSlantTier(10.0, 35.0, 1.5),
        RoadSlantTier(11.0, 40.0, 1.5),
        RoadSlantTier(12.0, 45.0, 1.5),
        RoadSlantTier(None, 50.0, 1.5),
    ],
    3: [
        RoadSlantTier(2.0, 20.0, 1.5),
        RoadSlantTier(3.0, 25.0, 1.5),
        RoadSlantTier(4.0, 30.0, 1.5),
        RoadSlantTier(None, 35.0, 1.5),
    ],
    4: [
        RoadSlantTier(None, 35.0, 1.5),
    ],
    5: [
        # 勾配は「一・二五又は一・五のうち特定行政庁が定めるもの」。
        # 敷地ごとに与えてもらうので None。
        RoadSlantTier(2.0, 20.0, None),
        RoadSlantTier(3.0, 25.0, None),
        RoadSlantTier(None, 30.0, None),
    ],
}

#: 別表第三 五の項で特定行政庁が選べる勾配。
#: 法55条1項: 低層住専・田園住居の絶対高さ制限（都市計画で定めるもの）
LOW_RISE_HEIGHT_LIMITS_M = (10.0, 12.0)

UNSPECIFIED_ROAD_SLANT_SLOPES = (1.25, 1.5)


class UndeterminedRegulation(ValueError):
    """自治体・特定行政庁の指定が無いと決まらない値を求められたとき。

    原則H に従い、既定値で埋めずに止めます。オーケストレータが入ったら
    `Verdict.UNDETERMINED` に翻訳する想定です。
    """


def road_slant_row(zone_type: str) -> int:
    """用途地域が別表第三のどの項に当たるか。"""
    row = ROAD_SLANT_ROW_BY_ZONE.get(zone_type)
    if row is None:
        raise ValueError(f"不明な用途地域: {zone_type!r}（有効な値: {sorted(ALL_ZONES)}）")
    return row


def road_slant_tier(
    zone_type: str,
    far_ratio: float,
    unspecified_slope: float | None = None,
) -> RoadSlantTier:
    """別表第三から（適用距離, 勾配）を引く。

    `unspecified_slope` は五の項（用途地域の指定のない区域）でのみ使います。
    条文が「一・二五又は一・五のうち特定行政庁が定めるもの」としており、
    どちらかを勝手に決められないためです。指定が無い無指定区域では
    `UndeterminedRegulation` を送出します。
    """
    row = road_slant_row(zone_type)
    for tier in ROAD_SLANT_TABLE[row]:
        if tier.far_upper is None or far_ratio <= tier.far_upper:
            break
    else:  # pragma: no cover - 各項の最後は far_upper=None
        raise AssertionError("到達しない: 最後の段は far_upper=None")

    if tier.slope is not None:
        return tier

    # 五の項。勾配は特定行政庁の指定次第。
    if unspecified_slope is None:
        raise UndeterminedRegulation(
            "用途地域の指定のない区域の道路斜線勾配は、別表第三 五の項により "
            "1.25 か 1.5 のうち特定行政庁が定めるものです。どちらか分からない"
            "ため計算できません。ZoningParams.unspecified_road_slant_slope に "
            "1.25 または 1.5 を指定してください"
        )
    if unspecified_slope not in UNSPECIFIED_ROAD_SLANT_SLOPES:
        raise ValueError(
            f"無指定区域の道路斜線勾配は 1.25 か 1.5 です（指定値: {unspecified_slope}）"
        )
    return RoadSlantTier(tier.far_upper, tier.applicable_distance_m, unspecified_slope)


# --- 隣地斜線（法56条1項2号）----------------------------------------
# 原文は docs/mvce/statutes/建築基準法.md の第56条第1項第2号。
#
# 号は イ〜ニ に分かれ、それぞれ勾配を定めます。立上り高さは用途地域では
# なく**勾配で決まります** — 1.25 なら 20m、2.5 なら 31m。号の本文が
# 「イ又はニに定める数値が一・二五とされている建築物にあつては二十
# メートルを、イからニまでに定める数値が二・五とされている建築物にあつて
# は三十一メートルを加えたもの」と書いているとおりです。
#
# 低層住居専用・田園住居は**イ〜ニのどれにも列挙されていません**。
# したがって隣地斜線の適用がありません。絶対高さ制限（法55条）があるから
# 結果的にそうなる、という説明を見かけますが、条文上は単に列挙が無いだけ
# です。
ADJACENT_SLANT_ITEM_BY_ZONE: dict[str, str] = {
    # イ: 中高層住専・第一種住居・第二種住居・準住居
    "1mid": "i", "2mid": "i", "1res": "i", "2res": "i", "quasi_res": "i",
    # ロ: 近隣商業・準工業・商業・工業・工業専用
    "neighbor_commercial": "ro", "quasi_industrial": "ro",
    "commercial": "ro", "industrial": "ro", "industrial_exclusive": "ro",
    # ハ: 高層住居誘導地区（用途地域ではないのでここには無い）
    # ニ: 用途地域の指定のない区域
    "unspecified": "ni",
    # 低層住専・田園住居は列挙が無い（＝適用なし）ので載せない
}

#: 勾配 → 立上り高さ。号の本文が定める対応。
ADJACENT_SLANT_START_HEIGHT_M: dict[float, float] = {1.25: 20.0, 2.5: 31.0}

#: ニ（無指定）で特定行政庁が選べる勾配。
UNSPECIFIED_ADJACENT_SLANT_SLOPES = (1.25, 2.5)


def adjacent_slant_item(zone_type: str) -> str | None:
    """用途地域が法56条1項2号のどの号に当たるか。適用が無い地域は None。"""
    if zone_type not in ALL_ZONES:
        raise ValueError(f"不明な用途地域: {zone_type!r}（有効な値: {sorted(ALL_ZONES)}）")
    return ADJACENT_SLANT_ITEM_BY_ZONE.get(zone_type)


def _item_i_allows_2_5(zone_type: str, far_ratio: float) -> bool:
    """イのただし書の 2.5 を指定できる地域か。

    条文は「第五十二条第一項第二号の規定により容積率の限度が十分の三十
    以下とされている第一種中高層住居専用地域及び第二種中高層住居専用地域
    **以外の地域**のうち、特定行政庁が（略）指定する区域」としています。
    つまり中高層住専で容積率が 30/10 以下の場合だけ対象外です。
    """
    return not (zone_type in MID_RISE_ZONES and far_ratio <= 3.0)


def adjacent_slant_params(
    zone_type: str,
    far_ratio: float | None = None,
    unspecified_slope: float | None = None,
    designated_2_5: bool = False,
) -> tuple[float, float] | None:
    """(立上り高さ, 勾配)。隣地斜線の適用が無い用途地域は None。

    `unspecified_slope` はニ（無指定）専用です。条文が「一・二五又は二・五
    のうち特定行政庁が定めるもの」としており、どちらかを勝手に決められ
    ません。指定が無い無指定区域では `UndeterminedRegulation` です（原則H）。

    `designated_2_5` はイのただし書。特定行政庁が指定する区域で 1.25 が
    2.5 に変わります。`far_ratio` はその適用可否の判定に要ります。
    """
    item = adjacent_slant_item(zone_type)
    if item is None:
        return None

    if item == "ro":
        slope = 2.5
    elif item == "ni":
        if unspecified_slope is None:
            raise UndeterminedRegulation(
                "用途地域の指定のない区域の隣地斜線勾配は、法56条1項2号ニにより "
                "1.25 か 2.5 のうち特定行政庁が定めるものです。どちらか分からない"
                "ため計算できません。ZoningParams.unspecified_adjacent_slant_slope に "
                "1.25 または 2.5 を指定してください"
            )
        if unspecified_slope not in UNSPECIFIED_ADJACENT_SLANT_SLOPES:
            raise ValueError(
                f"無指定区域の隣地斜線勾配は 1.25 か 2.5 です（指定値: {unspecified_slope}）"
            )
        slope = unspecified_slope
    else:  # イ
        slope = 1.25
        if designated_2_5:
            if far_ratio is None:
                raise ValueError(
                    "イのただし書（特定行政庁の指定で 2.5）の判定には far_ratio が要ります"
                )
            if not _item_i_allows_2_5(zone_type, far_ratio):
                raise ValueError(
                    f"{ZONE_LABELS_JA[zone_type]}で容積率の限度が 30/10 以下の場合、"
                    f"法56条1項2号イのただし書は適用できません"
                )
            slope = 2.5

    return ADJACENT_SLANT_START_HEIGHT_M[slope], slope


# --- 北側斜線（法56条1項3号）----------------------------------------
#
#   三　第一種低層住居専用地域、第二種低層住居専用地域若しくは田園住居地域内
#   又は第一種中高層住居専用地域若しくは第二種中高層住居専用地域（**次条
#   第一項の規定に基づく条例で別表第四の二の項に規定する（一）、（二）又は
#   （三）の号が指定されているものを除く。以下この号及び第七項第三号に
#   おいて同じ。**）内においては、（略）
#
# **中高層住専に日影規制の指定があれば、北側斜線はかかりません。**
# 括弧書きが付いているのは中高層住専だけで、低層住専・田園住居には
# 付いていません（「又は」の前に列挙されている）。
#
# 「第七項第三号において同じ」なので、**天空率の北側の算定位置も無くなります**
# （`regulations/sky_positions.py`）。
NORTH_SLANT_ZONES: dict[str, tuple[float, float]] = {
    "1low": (5.0, 1.25), "2low": (5.0, 1.25), "denen": (5.0, 1.25),
    "1mid": (10.0, 1.25), "2mid": (10.0, 1.25),
}

#: 法56条1項3号の括弧書きで除かれうる用途地域（中高層住専のみ）
NORTH_SLANT_EXCLUDABLE_ZONES = frozenset({"1mid", "2mid"})


def north_slant_params(
    zone_type: str, shadow_designated: bool = False
) -> tuple[float, float] | None:
    """(立上り高さ, 勾配)。北側斜線の適用が無い用途地域は None。

    `shadow_designated` は、その敷地が法56条の2第1項の条例で別表第四
    二の項の（一）〜（三）号が指定された区域にあるか。**中高層住専で
    True なら北側斜線は適用されません**（法56条1項3号の括弧書き）。
    低層住専・田園住居には括弧書きが無いので影響しません。
    """
    if shadow_designated and zone_type in NORTH_SLANT_EXCLUDABLE_ZONES:
        return None
    return NORTH_SLANT_ZONES.get(zone_type)


# --- 別表第四: 日影規制の対象建築物と測定面 --------------------------
# 原文は docs/mvce/statutes/建築基準法.md の別表第四。
#
# （ろ）欄が対象建築物、（は）欄が測定面（平均地盤面からの高さ）です。
# 規制時間（（に）欄の（一）〜（三））は条例が号を選ぶので、
# `ShadowRegulationSpec` に入力として渡してもらいます。
#
# 対象建築物の条件は2つの形があります。
#   軒高型 … 軒の高さが7mを超える、**または**地階を除く階数が3以上
#   高さ型 … 高さが10mを超える
# 「または」なので、軒高6mの3階建ても軒高型では対象です。高さだけを
# 見ていると取りこぼします。

#: 別表第四（ろ）欄の対象建築物の判定方法。
EAVES_OR_STOREYS = "eaves_or_storeys"   # 軒高7m超 または 地階を除く階数3以上
TOTAL_HEIGHT = "total_height"           # 高さ10m超

SHADOW_EAVES_THRESHOLD_M = 7.0
SHADOW_STOREYS_THRESHOLD = 3
SHADOW_HEIGHT_THRESHOLD_M = 10.0


@dataclass(frozen=True)
class ShadowTableRow:
    """別表第四の1項。"""

    criterion: str                       # EAVES_OR_STOREYS か TOTAL_HEIGHT
    measurement_heights_m: tuple[float, ...]   # （は）欄の選択肢
    time_options: tuple[str, ...]        # （に）欄で条例が選べる号


#: 用途地域 → 別表第四の項。
#: 商業・工業・工業専用は（い）欄に無いので、そもそも対象区域に指定できません。
SHADOW_TABLE: dict[str, ShadowTableRow] = {
    # 一の項
    "1low": ShadowTableRow(EAVES_OR_STOREYS, (1.5,), ("一", "二", "三")),
    "2low": ShadowTableRow(EAVES_OR_STOREYS, (1.5,), ("一", "二", "三")),
    "denen": ShadowTableRow(EAVES_OR_STOREYS, (1.5,), ("一", "二", "三")),
    # 二の項
    "1mid": ShadowTableRow(TOTAL_HEIGHT, (4.0, 6.5), ("一", "二", "三")),
    "2mid": ShadowTableRow(TOTAL_HEIGHT, (4.0, 6.5), ("一", "二", "三")),
    # 三の項。（三）が無いので2択。
    "1res": ShadowTableRow(TOTAL_HEIGHT, (4.0, 6.5), ("一", "二")),
    "2res": ShadowTableRow(TOTAL_HEIGHT, (4.0, 6.5), ("一", "二")),
    "quasi_res": ShadowTableRow(TOTAL_HEIGHT, (4.0, 6.5), ("一", "二")),
    "neighbor_commercial": ShadowTableRow(TOTAL_HEIGHT, (4.0, 6.5), ("一", "二")),
    "quasi_industrial": ShadowTableRow(TOTAL_HEIGHT, (4.0, 6.5), ("一", "二")),
}

#: 四の項（用途地域の指定のない区域）。イかロかは条例が選びます。
#: ロの測定面は **4m のみ**で、6.5m はありません。
SHADOW_TABLE_UNSPECIFIED: dict[str, ShadowTableRow] = {
    "i": ShadowTableRow(EAVES_OR_STOREYS, (1.5,), ("一", "二", "三")),
    "ro": ShadowTableRow(TOTAL_HEIGHT, (4.0,), ("一", "二", "三")),
}

#: 別表第四（い）欄に現れない用途地域。日影の対象区域に指定できません。
SHADOW_EXEMPT_ZONES = {"commercial", "industrial", "industrial_exclusive"}

#: 全用途地域を通じた測定面の選択肢。入力の粗い検証にだけ使ってください。
#: 用途地域が分かっているなら `shadow_table_row()` を使うほうが正確です。
MEASUREMENT_HEIGHT_CHOICES_M = (1.5, 4.0, 6.5)


def shadow_table_row(zone_type: str, unspecified_row: str | None = None) -> ShadowTableRow | None:
    """別表第四の該当項。対象区域に指定できない用途地域は None。

    無指定区域はイとロで対象建築物も測定面も違うので、`unspecified_row` に
    `"i"` / `"ro"` が要ります。無いと `UndeterminedRegulation` です（原則H）。
    """
    if zone_type not in ALL_ZONES:
        raise ValueError(f"不明な用途地域: {zone_type!r}（有効な値: {sorted(ALL_ZONES)}）")
    if zone_type in SHADOW_EXEMPT_ZONES:
        return None
    if zone_type == "unspecified":
        if unspecified_row is None:
            raise UndeterminedRegulation(
                "用途地域の指定のない区域の日影規制は、別表第四 四の項の "
                "イ（軒高7m超 または 地階を除く階数3以上・測定面1.5m）か "
                "ロ（高さ10m超・測定面4m）かを条例が指定します。どちらか"
                "分からないため判定できません。"
                "ZoningParams.unspecified_shadow_row に 'i' か 'ro' を指定してください"
            )
        return SHADOW_TABLE_UNSPECIFIED[unspecified_row]
    return SHADOW_TABLE[zone_type]


def allowed_measurement_heights_m(
    zone_type: str, unspecified_row: str | None = None
) -> tuple[float, ...]:
    """別表第四（は）欄の測定面の選択肢。対象外の用途地域は空。"""
    row = shadow_table_row(zone_type, unspecified_row)
    return () if row is None else row.measurement_heights_m


def validate_measurement_height(
    zone_type: str, measurement_height_m: float, unspecified_row: str | None = None
) -> None:
    """測定面が別表第四（は）欄の選択肢に入っているか検べる。

    用途地域が分かっている場所で呼んでください。`ShadowRegulationSpec` 単体は
    用途地域を知らないので 1.5 / 4 / 6.5 の粗い検証しかできませんが、
    ここでは項ごとの選択肢で見ます。無指定にロが指定されているとき 6.5m を
    弾けるのはこちらだけです。
    """
    allowed = allowed_measurement_heights_m(zone_type, unspecified_row)
    if not allowed:
        raise ValueError(
            f"{ZONE_LABELS_JA[zone_type]}は別表第四（い）欄に無く、"
            f"日影規制の対象区域に指定できません"
        )
    if measurement_height_m not in allowed:
        choices = " / ".join(f"{h}m" for h in allowed)
        raise ValueError(
            f"{ZONE_LABELS_JA[zone_type]}の測定面は別表第四（は）欄により "
            f"{choices} です（指定値: {measurement_height_m}m）"
        )


def is_shadow_target(
    zone_type: str,
    *,
    max_height_m: float,
    eaves_height_m: float | None = None,
    storeys_above_ground: int | None = None,
    unspecified_row: str | None = None,
) -> bool:
    """別表第四（ろ）欄の対象建築物に当たるか。

    軒高型（一の項・四の項イ）は「軒の高さが7mを超える**または**地階を
    除く階数が3以上」です。どちらか一方しか分からない場合、分かるほうだけ
    で判定します（両方 None なら高さで代用せず False を返さないよう、
    `eaves_height_m` に最高高さを渡すか階数を渡してください）。
    """
    row = shadow_table_row(zone_type, unspecified_row)
    if row is None:
        return False
    if row.criterion == TOTAL_HEIGHT:
        return max_height_m > SHADOW_HEIGHT_THRESHOLD_M
    by_eaves = eaves_height_m is not None and eaves_height_m > SHADOW_EAVES_THRESHOLD_M
    by_storeys = (
        storeys_above_ground is not None
        and storeys_above_ground >= SHADOW_STOREYS_THRESHOLD
    )
    return by_eaves or by_storeys


@dataclass
class ZoningParams:
    """敷地に適用される用途地域と数値。"""

    zone_type: str
    far_ratio: float          # 都市計画で定められた容積率（比。200% なら 2.0）
    coverage_ratio: float     # 建蔽率（比。60% なら 0.6）
    #: 法55条1項の絶対高さ制限。低層住専・田園住居では**必須**で、
    #: 10.0 か 12.0 のどちらかです（都市計画で定められたもの）。
    #: それ以外の用途地域では None。
    absolute_height_limit_m: float | None = None

    #: 別表第三 五の項。用途地域の指定のない区域の道路斜線勾配。
    #: 「一・二五又は一・五のうち特定行政庁が定めるもの」なので、
    #: 無指定区域ではこれを与えないと道路斜線が計算できません。
    unspecified_road_slant_slope: float | None = None

    #: 別表第四 四の項。用途地域の指定のない区域で条例が指定するのは
    #: イ（軒高7m超 または 地階を除く階数3以上・測定面1.5m）か
    #: ロ（高さ10m超・測定面4m）か。`"i"` / `"ro"` で指定します。
    unspecified_shadow_row: str | None = None

    #: 法56条1項2号ニ。用途地域の指定のない区域の隣地斜線勾配。
    #: 「一・二五又は二・五のうち特定行政庁が定めるもの」なので、
    #: 無指定区域ではこれを与えないと隣地斜線が計算できません。
    unspecified_adjacent_slant_slope: float | None = None

    #: 法56条の2第1項の条例で、別表第四 二の項の（一）〜（三）号が指定された
    #: 区域にあるか。**中高層住専で True なら北側斜線が適用されません**
    #: （法56条1項3号の括弧書き。天空率の北側算定位置も無くなります）。
    #: 既定 False は北側斜線を適用する側で、保守側です。
    shadow_ordinance_designated: bool = False

    #: 法56条1項2号イのただし書。特定行政庁が指定する区域では、イの
    #: 1.25 が 2.5 になります（立上りも 20m → 31m）。中高層住専で容積率の
    #: 限度が 30/10 以下の場合は対象外です。
    adjacent_slant_2_5_designated: bool = False

    def __post_init__(self) -> None:
        if self.zone_type not in ALL_ZONES:
            raise ValueError(f"不明な用途地域: {self.zone_type!r}（有効: {sorted(ALL_ZONES)}）")
        if self.far_ratio <= 0:
            raise ValueError("far_ratio は正の値である必要があります")
        if not 0 < self.coverage_ratio <= 1.0:
            raise ValueError("coverage_ratio は 0 より大きく 1 以下である必要があります")
        if (self.unspecified_road_slant_slope is not None
                and self.unspecified_road_slant_slope not in UNSPECIFIED_ROAD_SLANT_SLOPES):
            raise ValueError(
                "unspecified_road_slant_slope は 1.25 か 1.5 です"
                f"（指定値: {self.unspecified_road_slant_slope}）"
            )
        if self.unspecified_shadow_row not in (None, "i", "ro"):
            raise ValueError(
                f"unspecified_shadow_row は 'i' か 'ro' です（指定値: {self.unspecified_shadow_row!r}）"
            )
        if (self.unspecified_adjacent_slant_slope is not None
                and self.unspecified_adjacent_slant_slope
                not in UNSPECIFIED_ADJACENT_SLANT_SLOPES):
            raise ValueError(
                "unspecified_adjacent_slant_slope は 1.25 か 2.5 です"
                f"（指定値: {self.unspecified_adjacent_slant_slope}）"
            )
        if self.zone_type in LOW_RISE_ZONES:
            # 法55条1項:
            #   第一種低層住居専用地域、第二種低層住居専用地域又は田園住居地域
            #   内においては、建築物の高さは、**十メートル又は十二メートルの
            #   うち当該地域に関する都市計画において定められた**建築物の高さの
            #   限度を超えてはならない。
            #
            # どちらかは都市計画が定めるもので、条文に既定値はありません。
            # 以前は黙って 10.0 を入れていました（原則H 違反）。10m は
            # 厳しい側なので危険ではありませんでしたが、12m の地域で
            # 2m ぶん小さい答えを黙って出していたことになります。
            if self.absolute_height_limit_m is None:
                raise UndeterminedRegulation(
                    f"{ZONE_LABELS_JA[self.zone_type]}には法55条1項の絶対高さ制限が"
                    "必ずありますが、10mか12mかは都市計画で定められたものです。"
                    "absolute_height_limit_m に 10.0 か 12.0 を指定してください"
                    "（都市計画図で確認できます）。法55条2項の緩和（10mの地域で"
                    "空地と敷地面積の要件を満たし特定行政庁が認めるもの）で"
                    "12mになる場合も 12.0 を指定します。"
                )
            if self.absolute_height_limit_m not in LOW_RISE_HEIGHT_LIMITS_M:
                raise ValueError(
                    "法55条1項の絶対高さ制限は10mか12mです"
                    f"（指定値: {self.absolute_height_limit_m}）"
                )

    @property
    def label_ja(self) -> str:
        return ZONE_LABELS_JA[self.zone_type]

    @property
    def group(self) -> str:
        return zone_group(self.zone_type)
