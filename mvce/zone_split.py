"""敷地が用途地域の2以上にわたる場合（法52条7項・法53条2項・法56条5項・令135条の13）.

同じ「またがり」でも、条文によって**扱いがまったく違います**。ここを
取り違えると全部間違うので、まず対照表を置きます。

| 規制 | 条文 | またがったときの扱い |
|---|---|---|
| 容積率 | 法52条7項 | **面積按分**（各区域の限度 × 面積割合 の合計） |
| 建蔽率 | 法53条2項 | **面積按分**（同上） |
| 隣地斜線・北側斜線 | 法56条5項 | **按分しない。**「建築物」を「建築物の部分」と読み替え、部分ごとに判定 |
| 道路斜線 | 別表第三（い）欄 | **按分しない。**「建築物がある地域」ごと |
| 日影 | 令135条の13 | **按分しない。**各区域内にそれぞれ対象建築物があるものとして適用 |

    法52条7項
    ７　建築物の敷地が第一項及び第二項の規定による建築物の容積率に関する
    制限を受ける地域、地区又は区域の二以上にわたる場合においては、当該
    建築物の容積率は、第一項及び第二項の規定による当該各地域、地区又は
    区域内の建築物の容積率の限度にその敷地の当該地域、地区又は区域内に
    ある各部分の面積の敷地面積に対する割合を乗じて得たものの合計以下で
    なければならない。

    法53条2項
    ２　建築物の敷地が前項の規定による建築物の建蔽率に関する制限を受ける
    地域又は区域の二以上にわたる場合においては、当該建築物の建蔽率は、
    同項の規定による当該各地域又は区域内の建築物の建蔽率の限度にその敷地の
    当該地域又は区域内にある各部分の面積の敷地面積に対する割合を乗じて
    得たものの合計以下でなければならない。

    法56条5項
    ５　建築物が第一項第二号及び第三号の地域、地区又は区域の二以上にわたる
    場合においては、これらの規定中「建築物」とあるのは、「建築物の部分」と
    する。

    令135条の13
    第百三十五条の十三　（略）対象建築物が同項の規定による日影時間の制限の
    異なる区域の内外にわたる場合には当該対象建築物がある各区域内に、
    （略）それぞれ当該対象建築物があるものとして、同項の規定を適用する。

## 按分する側（実装済み）

`weighted_far_limit()` と `weighted_coverage_limit()` が面積按分を計算します。

容積率で注意が要るのは、**前面道路幅員による低減（法52条2項）の係数が
用途地域ごとに違う**ことです。前面道路の幅員は敷地に1つですが、住居系は
4/10、その他は 6/10 なので、区域ごとに別々に `min(指定容積率, 幅員×係数)`
を出してから按分します。法52条9項（特定道路）の加算は7項にも及ぶので、
按分に使う幅員も読み替え後の値です。

## 按分しない側（未実装 — 黙って片方の地域で計算しません）

斜線と日影は部分ごとの判定が要ります。いまの MVCE は敷地に1つの
`ZoningParams` を持つ作りなので、部分ごとの判定ができません。

**用途地域が2以上あるときに片方の値で計算すると、どちらに転ぶか分から
ない誤りになります**（厳しい側とは限りません）。なので黙って進めず、
`require_single_zone_type()` が `UndeterminedRegulation` で止めます。

部分ごとの判定を入れるときの設計は決まっています:

- 点で答える関数（`height_limit_at` 等）は、その点がどの区域にあるかで
  `ZoningParams` を選ぶ（法56条5項の「建築物の部分」そのもの）
- 辺で答える関数（`required_setback_for_height`）は辺に沿って区域が
  変わりうるので、その辺が接する区域すべての最大値を取る（安全側）
"""
from __future__ import annotations

from dataclasses import dataclass

from .zoning import (
    FAR_ROAD_WIDTH_THRESHOLD_M,
    UndeterminedRegulation,
    ZoningParams,
)

#: 面積の合計が敷地面積と一致しているとみなす相対誤差
AREA_TOLERANCE = 1e-6


@dataclass(frozen=True)
class ZonePart:
    """敷地のうち、1つの地域・地区・区域にある部分。"""

    zoning: ZoningParams
    area_m2: float
    label: str = ""

    def __post_init__(self) -> None:
        if self.area_m2 <= 0:
            raise ValueError(f"区域の面積は正の値が必要です: {self.area_m2}")


@dataclass(frozen=True)
class ZoneSplit:
    """敷地の用途地域による区分。

    面積だけを持ち、形は持ちません。容積率・建蔽率の按分（法52条7項・
    法53条2項）は面積割合しか使わないからです。斜線・日影を部分ごとに
    判定するには形が要りますが、そちらは未実装です（モジュール docstring）。
    """

    parts: tuple[ZonePart, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("区分が1つもありません")

    @property
    def total_area_m2(self) -> float:
        return sum(p.area_m2 for p in self.parts)

    @property
    def is_single(self) -> bool:
        return len(self.parts) == 1

    @property
    def zone_types(self) -> tuple[str, ...]:
        return tuple(p.zoning.zone_type for p in self.parts)

    @property
    def distinct_zone_types(self) -> tuple[str, ...]:
        seen: list[str] = []
        for z in self.zone_types:
            if z not in seen:
                seen.append(z)
        return tuple(seen)

    def fractions(self) -> tuple[float, ...]:
        """各部分の面積が敷地面積に占める割合。"""
        total = self.total_area_m2
        return tuple(p.area_m2 / total for p in self.parts)

    def largest(self) -> ZonePart:
        return max(self.parts, key=lambda p: p.area_m2)

    def check_total_area(self, site_area_m2: float) -> None:
        """各部分の面積の合計が敷地面積と合っているか。

        条文の按分は「敷地面積に対する割合」なので、合計がずれていると
        按分そのものが狂います。黙って正規化せずに弾きます。
        """
        total = self.total_area_m2
        if abs(total - site_area_m2) > AREA_TOLERANCE * max(site_area_m2, 1.0):
            raise ValueError(
                f"区分の面積の合計 {total:.4f} m2 が敷地面積 {site_area_m2:.4f} m2 と"
                "一致しません。法52条7項・法53条2項の按分は「敷地面積に対する割合」"
                "なので、合計が合っていないと按分が狂います。"
            )


# === 法52条7項（容積率の按分）========================================

def far_limit_for(zoning: ZoningParams, road_width_m: float) -> float:
    """1つの区域内の容積率の限度（法52条1項・2項）。

    `road_width_m` は法52条2項に使う幅員（法52条9項の加算後）。
    幅員は敷地に1つですが、乗ずる係数は用途地域ごとに違います。
    """
    if road_width_m <= 0 or road_width_m >= FAR_ROAD_WIDTH_THRESHOLD_M:
        return zoning.far_ratio
    # 係数は法52条2項各号の括弧書き（指定区域）を反映したもの
    return min(zoning.far_ratio, road_width_m * zoning.far_road_coefficient())


def weighted_far_limit(split: ZoneSplit, road_width_m: float) -> tuple[float, list[str]]:
    """法52条7項の按分後の容積率。`(限度, 説明)` を返す。"""
    total = split.total_area_m2
    notes: list[str] = []
    if split.is_single:
        return far_limit_for(split.parts[0].zoning, road_width_m), notes

    notes.append(
        f"法52条7項: 敷地が容積率の制限の異なる{len(split.parts)}区域に"
        "わたるため、各区域の限度を面積割合で按分します。"
    )
    value = 0.0
    for part in split.parts:
        limit = far_limit_for(part.zoning, road_width_m)
        fraction = part.area_m2 / total
        value += limit * fraction
        label = part.label or part.zoning.zone_type
        notes.append(
            f"  {label}: 限度 {limit * 100:.0f}% × 面積割合 {fraction * 100:.1f}%"
            f"（{part.area_m2:.1f} m2 / {total:.1f} m2）= {limit * fraction * 100:.1f}%"
        )
    notes.append(f"  合計 = {value * 100:.1f}%")
    return value, notes


# === 法53条2項（建蔽率の按分）========================================

def weighted_coverage_limit(split: ZoneSplit) -> tuple[float | None, list[str]]:
    """法53条2項の按分後の建蔽率。`(限度, 説明)` を返す。

    限度が `None` なら**制限なし**（法53条6項1号の適用除外）です。

    **3項の加算は按分より先です。** 3項は「前二項の規定の適用については…
    第一項各号に定める数値に十分の一を加えたものをもつて当該各号に定める
    数値とし」なので、1項の数値を読み替えてから2項で按分します。順番を
    逆にすると答えが変わります。

    区域のどれかが6項1号の適用除外に当たる場合は、条文が「前各項の規定は
    （略）適用しない」としているので、按分せず制限なしとします。
    """
    total = split.total_area_m2
    notes: list[str] = []

    limits = [p.zoning.coverage_limit() for p in split.parts]
    if any(limit is None for limit in limits):
        exempt = [p.label or p.zoning.zone_type
                  for p, limit in zip(split.parts, limits) if limit is None]
        notes.append(
            f"法53条6項1号: {('・'.join(exempt))} が建蔽率の適用除外"
            "（建蔽率の限度が8/10とされている地域の防火地域内の耐火建築物等）"
            "に当たるため、建蔽率の制限はありません。"
        )
        return None, notes

    if split.is_single:
        return limits[0], notes

    notes.append(
        f"法53条2項: 敷地が建蔽率の制限の異なる{len(split.parts)}区域に"
        "わたるため、各区域の限度を面積割合で按分します。"
    )
    value = 0.0
    for part, limit in zip(split.parts, limits):
        fraction = part.area_m2 / total
        value += limit * fraction
        label = part.label or part.zoning.zone_type
        bonus = limit - part.zoning.coverage_ratio
        tail = f"（法53条3項で +{bonus * 100:.0f}%）" if bonus > 1e-9 else ""
        notes.append(
            f"  {label}: 限度 {limit * 100:.0f}%{tail} × 面積割合 {fraction * 100:.1f}%"
            f" = {limit * fraction * 100:.1f}%"
        )
    notes.append(f"  合計 = {value * 100:.1f}%")
    return value, notes


# === 按分しない側のガード ============================================

def require_single_zone_type(split: ZoneSplit | None, regulation_ja: str) -> None:
    """按分しない規制の前で、用途地域が1つであることを確かめる。

    2以上あるときは `UndeterminedRegulation`。片方の値で黙って計算すると
    どちらに転ぶか分からない誤りになるので、止めます。
    """
    if split is None or len(split.distinct_zone_types) <= 1:
        return
    zones = "・".join(split.distinct_zone_types)
    raise UndeterminedRegulation(
        f"敷地が用途地域の2以上（{zones}）にわたっています。"
        f"{regulation_ja}は面積按分ではなく**部分ごと**の判定です"
        "（隣地・北側は法56条5項、道路は別表第三（い）欄、日影は令135条の13）。"
        "MVCE はまだ部分ごとの判定に対応していないため、片方の用途地域の値で"
        "計算すると誤った結果になります。容積率・建蔽率（法52条7項・法53条2項）"
        "の按分は zone_split で計算できます。"
    )
