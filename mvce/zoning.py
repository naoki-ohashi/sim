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
# 住居系 4/10、その他 6/10。
FAR_ROAD_COEFFICIENT = {"residential": 0.4, "other": 0.6}
FAR_ROAD_WIDTH_THRESHOLD_M = 12.0  # これ以上の幅員なら指定容積率のまま

# 法52条2項は3号に分かれていて、括弧書きの「特定行政庁が指定する区域」で
# 係数が変わります。**変わる向きが号によって違う**ので、群（住居系／その他）
# だけでは足りません。
#
#   一号 低層住専・田園住居 …… 十分の四（括弧書き**なし**）
#   二号 中高層住専・1住居・2住居・準住居
#        …… 十分の四（指定区域では十分の六）        → 指定は**緩和**
#   三号 その他 …… 十分の六（指定区域では十分の四**又は**十分の八）
#                                                    → 指定は**緩和にも強化にもなる**
#
# 三号の 4/10 が問題です。指定を知らずに既定の 6/10 を使うと、実際の限度の
# 1.5倍を許してしまいます（**緩い側＝危険**）。原則G のとおり、指定は入力
# （`ZoningParams.far_road_coefficient_designated`）から受け取ります。

#: 法52条2項の号（1 / 2 / 3）→ 括弧書きで指定されうる係数。
#: 空タプルは括弧書きが無い号。
FAR_ROAD_DESIGNATED_COEFFICIENTS: dict[int, tuple[float, ...]] = {
    1: (),
    2: (0.6,),
    3: (0.4, 0.8),
}


def far_road_paragraph_2_item(zone_type: str) -> int:
    """用途地域 → 法52条2項の号（1 / 2 / 3）。"""
    if zone_type in LOW_RISE_ZONES:
        return 1
    if zone_type in MID_RISE_ZONES | OTHER_RESIDENTIAL_ZONES:
        return 2
    if zone_type in COMMERCIAL_ZONES | INDUSTRIAL_ZONES | UNSPECIFIED_ZONES:
        return 3
    raise ValueError(f"不明な用途地域: {zone_type!r}（有効な値: {sorted(ALL_ZONES)}）")


def far_road_coefficient(zone_type: str, designated: float | None = None) -> float:
    """法52条2項の低減係数。`designated` は括弧書きの指定区域の数値。

    指定が無ければ各号の本文の値（一号・二号 4/10、三号 6/10）です。
    """
    item = far_road_paragraph_2_item(zone_type)
    if designated is None:
        return FAR_ROAD_COEFFICIENT[zone_group(zone_type)]
    allowed = FAR_ROAD_DESIGNATED_COEFFICIENTS[item]
    if designated not in allowed:
        if not allowed:
            raise ValueError(
                f"{ZONE_LABELS_JA[zone_type]}は法52条2項第一号で、括弧書き"
                "（特定行政庁が指定する区域）がありません。係数は常に4/10です。"
                "far_road_coefficient_designated は指定しないでください"
            )
        raise ValueError(
            f"{ZONE_LABELS_JA[zone_type]}は法52条2項第{item}号なので、"
            f"指定区域の係数は {allowed} のいずれかです"
            f"（指定値: {designated}）"
        )
    return designated


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


# --- 別表第三 備考三 -------------------------------------------------
#
#     三　この表（い）欄一の項に掲げる第一種中高層住居専用地域若しくは
#     第二種中高層住居専用地域（第五十二条第一項第二号の規定により、容積率の
#     限度が十分の四十以上とされている地域に限る。）又は第一種住居地域、
#     第二種住居地域若しくは準住居地域のうち、特定行政庁が都道府県都市計画
#     審議会の議を経て指定する区域内の建築物については、（は）欄一の項中
#     「二十五メートル」とあるのは「二十メートル」と、「三十メートル」と
#     あるのは「二十五メートル」と、「三十五メートル」とあるのは
#     「三十メートル」と、（に）欄一の項中「一・二五」とあるのは
#     「一・五」とする。
#
# 距離が1段階短くなり、勾配が急になるので、**どちらも緩和**です。
# 対象は一の項のうち中高層住専（容積率40/10以上）と1住居・2住居・準住居だけ。
# **低層住専・田園住居は列挙されていない**ので対象外です。

#: 備考三の（は）欄の読み替え。20m はそのまま。
TABLE3_NOTE3_DISTANCE_M: dict[float, float] = {25.0: 20.0, 30.0: 25.0, 35.0: 30.0}
#: 備考三の（に）欄の読み替え
TABLE3_NOTE3_SLOPE = 1.5
#: 備考三が中高層住専にかかる容積率の下限（十分の四十）。
#: **これは「第五十二条第一項第二号の規定により」なので指定容積率**で、
#: （ろ）欄の「1項・2項・7項・9項による限度」とは別の値です。
TABLE3_NOTE3_MID_RISE_MIN_FAR = 4.0


def table3_note3_applies(zone_type: str, designated_far: float,
                         designated: bool) -> bool:
    """別表第三 備考三の指定区域に当たるか。

    `designated_far` は**指定容積率**（法52条1項2号の数値）です。
    """
    if not designated:
        return False
    if zone_type in MID_RISE_ZONES:
        return designated_far >= TABLE3_NOTE3_MID_RISE_MIN_FAR - 1e-9
    return zone_type in OTHER_RESIDENTIAL_ZONES


def road_slant_tier(
    zone_type: str,
    far_limit: float,
    unspecified_slope: float | None = None,
    note3_designated: bool = False,
    designated_far: float | None = None,
) -> RoadSlantTier:
    """別表第三から（適用距離, 勾配）を引く。

    `far_limit` は（ろ）欄の「**第五十二条第一項、第二項、第七項及び第九項の
    規定による容積率の限度**」です。指定容積率ではなく、前面道路幅員による
    低減などを反映した**実際に適用される限度**を渡してください
    （`far.effective_far_limit(site)`）。

    `unspecified_slope` は五の項（用途地域の指定のない区域）でのみ使います。
    条文が「一・二五又は一・五のうち特定行政庁が定めるもの」としており、
    どちらかを勝手に決められないためです。指定が無い無指定区域では
    `UndeterminedRegulation` を送出します。

    `note3_designated` は備考三の指定区域かどうか。`designated_far` は
    その判定に使う**指定容積率**で、省略すると `far_limit` を使います。
    """
    row = road_slant_row(zone_type)
    for tier in ROAD_SLANT_TABLE[row]:
        if tier.far_upper is None or far_limit <= tier.far_upper:
            break
    else:  # pragma: no cover - 各項の最後は far_upper=None
        raise AssertionError("到達しない: 最後の段は far_upper=None")

    if row == 1 and table3_note3_applies(
            zone_type,
            far_limit if designated_far is None else designated_far,
            note3_designated):
        return RoadSlantTier(
            tier.far_upper,
            TABLE3_NOTE3_DISTANCE_M.get(tier.applicable_distance_m,
                                        tier.applicable_distance_m),
            TABLE3_NOTE3_SLOPE)

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


def adjacent_slant_setback_applies(zone_type: str, designated_2_5: bool = False) -> bool:
    """法56条1項2号の後退距離の加算があるか。

    号の本文の括弧書き:

        イからニまでに定める数値が二・五とされている建築物（**ロ及びハに
        掲げる建築物で、特定行政庁が都道府県都市計画審議会の議を経て
        指定する区域内にあるものを除く。**以下この号及び第七項第二号に
        おいて同じ。）で高さが三十一メートルを超える部分を有するもの
        にあつては、それぞれその部分から隣地境界線までの水平距離のうち
        最小のものに相当する距離を**加えたもの**に、（略）

    括弧書きが付いているのは「後退距離を加える建築物」を指す名詞句なので、
    **ロ・ハの指定区域では後退距離の加算をしません**。

    ## 「以下この号において同じ」をどこまで及ぼすか

    括弧書きは「以下この号及び第七項第二号において同じ」と続きます。同じ
    名詞句は号の末尾（「二・五とされている建築物にあつては**三十一メートル**を
    加えたもの」）にも、法56条7項2号（天空率の基準線 12.4m）にも出てきます。

    **文字どおり及ぼすと成り立ちません。** ロの指定区域の建築物は
    「1.25 とされている建築物」でも「2.5 とされている建築物」でもなくなり、
    立上りが 20m でも 31m でもない＝**立上り無し**になります。隣地境界線上で
    高さ0という、明らかに法の趣旨に反する結果です。7項2号でも基準線が
    16m でも 12.4m でもなくなり、天空率が使えなくなります。

    したがって、括弧書きが実際に効くのは**後退距離の加算だけ**と読みました。
    立上り 31m と 7項2号の基準線 12.4m はそのまま適用します。

    ## 指定は `designated_2_5` と同じもの

    イのただし書も本文の括弧書きも「特定行政庁が都道府県都市計画審議会の議を
    経て指定する区域」で、同じ文言です。同じ指定とみて1つの入力で扱います。
    その区域では、イの地域は 1.25 → 2.5 になり、ロ・ハの地域は後退距離の
    加算が外れます。
    """
    if not designated_2_5:
        return True
    # ハ（高層住居誘導地区）は用途地域ではないので `ADJACENT_SLANT_ITEM_BY_ZONE`
    # に入っていません。MVCE は高層住居誘導地区を扱っていないので、実際に
    # 効くのはロだけです。扱うようになったらここにハを足してください。
    return adjacent_slant_item(zone_type) != "ro" 


# --- 建蔽率の緩和・適用除外（法53条3項・6項・7項・8項）----------------
#
# 1項の数値は都市計画で決まる入力（`ZoningParams.coverage_ratio`）です。
# ここで扱うのは、そこに加算する / 制限を外す規定です。
#
#   3項 … 1号（防火地域＋耐火建築物等 / 準防火地域＋耐火・準耐火建築物等）
#          または 2号（角地等の指定）で **+1/10**、両方で **+2/10**
#   6項1号 … 建蔽率の限度が8/10とされている地域の防火地域内の耐火建築物等は
#          **制限そのものが適用されない**
#   7項 … 敷地が防火地域の内外にわたり、建築物の全部が耐火建築物等なら
#          全て防火地域内とみなす
#   8項 … 敷地が準防火地域と（防火・準防火以外）にわたり、建築物の全部が
#          耐火建築物等または準耐火建築物等なら全て準防火地域内とみなす
#
# 3項は「**前二項の規定の適用については**」なので、加算は1項の数値に対して
# 行い、**そのうえで2項の按分**をします。順番を逆にすると答えが変わります。

#: 防火地域等の指定。7項・8項のみなしを表現するため、またがりも値に持ちます。
FIRE_ZONES = (
    "none",                # 防火地域でも準防火地域でもない
    "fire",                # 防火地域
    "quasi_fire",          # 準防火地域
    "fire_partial",        # 防火地域の内外にわたる（法53条7項）
    "quasi_fire_partial",  # 準防火地域と防火・準防火以外にわたる（法53条8項）
)

#: 建築物の防火性能。法53条3項1号のイ・ロ。
FIREPROOF_GRADES = (
    "none",
    "quasi_fireproof",  # ロ: 準耐火建築物等
    "fireproof",        # イ: 耐火建築物等
)

#: 法53条3項の加算（1つ該当で 1/10、2つで 2/10）
COVERAGE_BONUS_PER_ITEM = 0.1

#: 法53条1項2号〜4号の地域（3項1号・6項1号の「8/10とされている地域」の母集団）
COVERAGE_ITEM_2_TO_4_ZONES = frozenset({
    # 二号
    "1res", "2res", "quasi_res", "quasi_industrial",
    # 三号
    "neighbor_commercial",
    # 四号
    "commercial",
})

#: 「建蔽率の限度が十分の八とされている」の判定値
COVERAGE_EIGHT_TENTHS = 0.8


def effective_fire_zone(fire_zone: str, fireproof: str) -> str:
    """法53条7項・8項のみなしを適用したあとの防火地域等。

        ７　建築物の敷地が防火地域の内外にわたる場合において、その敷地内の
        建築物の全部が耐火建築物等であるときは、その敷地は、全て防火地域内に
        あるものとみなして、第三項第一号又は前項第一号の規定を適用する。

        ８　建築物の敷地が準防火地域と防火地域及び準防火地域以外の区域とに
        わたる場合において、その敷地内の建築物の全部が耐火建築物等又は
        準耐火建築物等であるときは、その敷地は、全て準防火地域内にあるものと
        みなして、第三項第一号の規定を適用する。

    みなしの条件を満たさなければ、またがりのままでは3項1号・6項1号の
    「（準）防火地域内にある」に当たらないので `none` として扱います。
    """
    if fire_zone not in FIRE_ZONES:
        raise ValueError(f"fire_zone は {FIRE_ZONES} のいずれかです（指定値: {fire_zone!r}）")
    if fireproof not in FIREPROOF_GRADES:
        raise ValueError(
            f"fireproof は {FIREPROOF_GRADES} のいずれかです（指定値: {fireproof!r}）")

    if fire_zone == "fire_partial":
        return "fire" if fireproof == "fireproof" else "none"
    if fire_zone == "quasi_fire_partial":
        return "quasi_fire" if fireproof in ("fireproof", "quasi_fireproof") else "none"
    return fire_zone


def _is_eight_tenths_zone(zone_type: str, coverage_ratio: float) -> bool:
    """法53条1項2号〜4号により建蔽率の限度が 8/10 とされている地域か。"""
    return (zone_type in COVERAGE_ITEM_2_TO_4_ZONES
            and abs(coverage_ratio - COVERAGE_EIGHT_TENTHS) < 1e-9)


def coverage_fire_bonus_applies(
    zone_type: str, coverage_ratio: float, fire_zone: str, fireproof: str
) -> bool:
    """法53条3項1号に当たるか。

        一　防火地域（第一項第二号から第四号までの規定により建蔽率の限度が
        十分の八とされている地域を除く。）内にあるイに該当する建築物
        又は準防火地域内にあるイ若しくはロのいずれかに該当する建築物

    イ＝耐火建築物等、ロ＝準耐火建築物等。**準防火地域では準耐火建築物等でも
    対象**です（旧法にはありませんでした）。
    """
    effective = effective_fire_zone(fire_zone, fireproof)
    if effective == "fire":
        if _is_eight_tenths_zone(zone_type, coverage_ratio):
            return False        # 6項1号の側（適用除外）
        return fireproof == "fireproof"
    if effective == "quasi_fire":
        return fireproof in ("fireproof", "quasi_fireproof")
    return False


def coverage_is_exempt(
    zone_type: str, coverage_ratio: float, fire_zone: str, fireproof: str
) -> bool:
    """法53条6項1号に当たるか（建蔽率の制限そのものが適用されない）。

        一　防火地域（第一項第二号から第四号までの規定により建蔽率の限度が
        十分の八とされている地域に限る。）内にある耐火建築物等
    """
    if not _is_eight_tenths_zone(zone_type, coverage_ratio):
        return False
    return (effective_fire_zone(fire_zone, fireproof) == "fire"
            and fireproof == "fireproof")


def coverage_limit(
    zone_type: str,
    coverage_ratio: float,
    fire_zone: str = "none",
    fireproof: str = "none",
    corner_lot_designated: bool = False,
) -> float | None:
    """法53条1項・3項・6項1号による建蔽率の限度。

    `None` は**制限なし**（6項1号の適用除外）です。0 ではありません。

    2項の按分は呼び出し側（`zone_split`）が、この関数で区域ごとの値を
    出してから行います。3項が「前二項の規定の適用については」＝1項の数値を
    読み替える規定なので、**加算が先、按分が後**です。
    """
    if coverage_is_exempt(zone_type, coverage_ratio, fire_zone, fireproof):
        return None
    bonus = 0.0
    if coverage_fire_bonus_applies(zone_type, coverage_ratio, fire_zone, fireproof):
        bonus += COVERAGE_BONUS_PER_ITEM
    if corner_lot_designated:
        bonus += COVERAGE_BONUS_PER_ITEM
    return min(1.0, coverage_ratio + bonus)


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

    #: 防火地域等の指定（法53条3項1号・6項1号）。`FIRE_ZONES` の値。
    #: 敷地がまたがる場合は `fire_partial` / `quasi_fire_partial` を使うと、
    #: 法53条7項・8項のみなしを engine 側で当てはめます。
    fire_zone: str = "none"

    #: 建築物の防火性能（法53条3項1号のイ・ロ）。`FIREPROOF_GRADES` の値。
    #: **建築物の属性**なので本来は用途地域の情報ではありませんが、建蔽率の
    #: 限度を出すのに要るのでここに置いています。
    fireproof: str = "none"

    #: 法53条3項2号。街区の角にある敷地等で特定行政庁が指定するもの。
    corner_lot_designated: bool = False

    #: 法56条の2第1項の条例で、別表第四 二の項の（一）〜（三）号が指定された
    #: 区域にあるか。**中高層住専で True なら北側斜線が適用されません**
    #: （法56条1項3号の括弧書き。天空率の北側算定位置も無くなります）。
    #: 既定 False は北側斜線を適用する側で、保守側です。
    shadow_ordinance_designated: bool = False

    #: 法56条1項2号イのただし書。特定行政庁が指定する区域では、イの
    #: 1.25 が 2.5 になります（立上りも 20m → 31m）。中高層住専で容積率の
    #: 限度が 30/10 以下の場合は対象外です。
    adjacent_slant_2_5_designated: bool = False

    #: 法52条2項各号の括弧書き。「特定行政庁が都道府県都市計画審議会の議を
    #: 経て指定する区域」で定められた低減係数です。指定が無ければ None。
    #:
    #: **三号（近隣商業・商業・準工業・工業・工業専用・無指定）では 4/10 も
    #: ありえます。** 本文は 6/10 なので、指定を知らずに既定で計算すると
    #: 実際の限度の**1.5倍**を許してしまいます（緩い側）。指定区域かどうかは
    #: 都市計画図で確認してください。
    far_road_coefficient_designated: float | None = None

    #: 別表第三 備考三の指定区域か。中高層住専（**指定**容積率 40/10 以上）と
    #: 1住居・2住居・準住居が対象で、低層住専・田園住居は対象外です。
    #: True にすると道路斜線の適用距離が1段階短くなり、勾配が 1.25 → 1.5 に
    #: なります。**どちらも緩和**なので、既定 False は厳しい側です。
    road_slant_note3_designated: bool = False

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
        if self.fire_zone not in FIRE_ZONES:
            raise ValueError(
                f"fire_zone は {FIRE_ZONES} のいずれかです（指定値: {self.fire_zone!r}）")
        if self.fireproof not in FIREPROOF_GRADES:
            raise ValueError(
                f"fireproof は {FIREPROOF_GRADES} のいずれかです"
                f"（指定値: {self.fireproof!r}）")
        # 号ごとに許される値が違うので、ここで弾いておく（法52条2項各号）
        far_road_coefficient(self.zone_type, self.far_road_coefficient_designated)
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

    def road_slant_tier(self, far_limit: float) -> RoadSlantTier:
        """別表第三の段。`far_limit` は（ろ）欄の容積率の限度。

        呼び出し側が `far.effective_far_limit(site)` を渡します。備考三の
        判定に使う**指定**容積率はこちらが持っているので、ここで渡します。
        """
        return road_slant_tier(
            self.zone_type, far_limit, self.unspecified_road_slant_slope,
            note3_designated=self.road_slant_note3_designated,
            designated_far=self.far_ratio)

    def far_road_coefficient(self) -> float:
        """法52条2項の低減係数（括弧書きの指定を反映したもの）。"""
        return far_road_coefficient(self.zone_type,
                                    self.far_road_coefficient_designated)

    def coverage_limit(self) -> float | None:
        """法53条1項・3項・6項1号によるこの区域の建蔽率の限度。

        `None` は制限なし（6項1号の適用除外）です。
        """
        return coverage_limit(
            self.zone_type, self.coverage_ratio,
            self.fire_zone, self.fireproof, self.corner_lot_designated)

    @property
    def group(self) -> str:
        return zone_group(self.zone_type)
