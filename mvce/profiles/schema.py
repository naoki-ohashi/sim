"""`ComplianceProfile` — 運用差と解釈の選択を1か所にまとめる（原則A・F・G）.

条文が特定行政庁・条例に委ねている値と、条文が決めていない点の解釈は、
コードの `if` ではなくデータで持ちます。同じ敷地でも行政庁が違えば答えが
変わるので、**どの運用でその数字を出したのか**が残らないと、あとから
検証できません。

プロファイルが持つのは次の3種類です。

1. **特定行政庁の運用** … 条文が「特定行政庁が…認めるとき」等としていて、
   行政庁ごとに違うもの
2. **選択規定** … 条文が「…によることができる」としていて、申請者が
   選べるもの
3. **条文が決めていない点の解釈** … 文言だけでは一意に決まらず、実務の
   通説や方式（東京都方式・JCBA方式など）で分かれるもの

## 出典が要ります（原則F）

既定（`statutory`）以外のプロファイルには `source` を必須にしています。
「どの行政庁の、いつ確認した、どの文書か」に答えられない運用値は、
事業判断の根拠にできません。

## 方式（東京都方式・JCBA方式等）はまだ入っていません

天空率の区域分割（令135条の6第3項）や高低差区分区域の切り方は方式で
分かれますが、**方式を定めた文書を取得できていないので実装していません。**
`sky_region_split_method` に `None` 以外を入れると、その方式の内容を
持っていないことを理由に `UndeterminedRegulation` で止まります。
推測で方式を書くくらいなら、止めるほうが安全です。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from ..sources import SourceRef
from ..zoning import UndeterminedRegulation

#: 令2条2項の「平均の高さ」の取り方
GROUND_AVERAGE_METHODS = ("length_weighted", "simple_mean")

#: 令132条の出隅敷地の区域の切り方（JCBA 報告書 平成22年）
CORNER_REGION_METHODS = ("perpendicular", "arc")
#: そのうち実装を持っているもの
SUPPORTED_CORNER_REGION_METHODS = ("perpendicular",)

#: 実装を持っている天空率の区域分割方式（いまは「分割しない＝止まる」だけ）
SUPPORTED_SKY_REGION_SPLIT_METHODS: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComplianceProfile:
    """審査機関・特定行政庁ごとの運用と、解釈の選択。"""

    name: str
    source: Optional[SourceRef] = None

    # --- 特定行政庁の運用 -------------------------------------------
    #: 令135条の3第1項1号（隣地斜線の緩和）に線路敷を含めるか。
    #: 条文は「公園（都市公園を除く）、広場、水面その他これらに類するもの」で
    #: 線路敷を列挙していません。含める運用の行政庁に合わせるときだけ True。
    railway_is_adjacent_relaxation: bool = False

    #: 令135条の12第3項1号（日影のみなし境界線）に公園・広場を含めるか。
    #: 条文は「道路、水面、線路敷その他これらに類するもの」で公園を
    #: 列挙していません。
    park_is_deemed_boundary: bool = False

    # --- 選択規定 ---------------------------------------------------
    #: 令134条2項。「第百三十二条第一項の規定によらないで…よることができる」
    #: という選択規定。既定 False は令132条1項によるということで保守側。
    apply_article_134_2: bool = False

    # --- 条文が決めていない点の解釈 ---------------------------------
    #: 令2条2項の「平均の高さ」。`length_weighted` は接地線に沿った長さ
    #: 加重平均（実務の通説）、`simple_mean` は接地位置の単純平均。
    ground_average_method: str = "length_weighted"

    #: 令132条の出隅敷地における「2Aかつ35m」の区域の切り方。
    #: JCBA 報告書（平成22年）は2つの運用を挙げ「いずれの運用も可能とする」
    #: としています。
    #:   `perpendicular` … 広い道路に垂直に区域区分（街区主義。アンケートで
    #:                      2/3、「基準総則・集団規定の適用事例」も同じ）
    #:   `arc`           … 敷地の角地を起点に円弧状に区域区分（敷地主義）
    #: `arc` は未実装で、指定すると `UndeterminedRegulation` で止まります。
    corner_region_method: str = "perpendicular"

    #: 屈曲道路を「一の道路」とみなす屈曲角度のしきい値（度）。
    #: JCBA 報告書（平成22年）は「敷地側からみて屈曲角度が120°を超える道路が
    #: 連担する範囲を一の道路として取り扱う。屈曲角度は道路中心線の屈曲角度」
    #: としつつ、「特定行政庁の判断に委ねられる」としています。
    #: アンケートでは約6割が角度基準を使っていません。
    #: `None` は角度で判断しない（＝入力された辺をそのまま前面道路とする）。
    #:
    #: **MVCE はまだ辺の併合をしません。** 一の道路として扱いたい辺は、
    #: 利用者が1つの `Boundary` にまとめて入力してください。この値は
    #: いまのところ記録用です。
    one_road_angle_deg: Optional[float] = None

    #: 隣地境界線を「連続した一の隣地境界線」として敷地を区分せずに扱うか。
    #: JCBA 報告書（平成22年）が挙げる運用で、「特定行政庁の判断に委ねられる」
    #: ものです。MVCE は辺ごとに算定位置を作る「敷地区分方式」で、
    #: `True` は未実装です。
    continuous_adjacent_boundary: bool = False

    #: 高低差区分区域（令135条の7第3項等）の切り方。JCBA 報告書（平成22年）は
    #: 隣地斜線を「敷地境界線に直交する線」、北側斜線を「南北方向に平行する線」
    #: としつつ、法文上の明確な規定がないことを認めています。
    #: MVCE は高低差区分区域そのものが未実装なので、`None` 以外は
    #: `UndeterminedRegulation` で止まります。
    level_region_split_method: Optional[str] = None

    #: 天空率の区域分割方式（令135条の6第3項・令135条の9第3項）。
    #: 区域の切り方そのものは `regulations/road_regions.py` が条文どおりに
    #: 実装し、天空率にも通しました（2026-08-31）。このフィールドは、それと
    #: 違う方式を名指しで指定したいとき用の受け口です。実装を持っている方式が
    #: 無いので `None` 以外は受け付けません。
    sky_region_split_method: Optional[str] = None

    # --- 精度（法規ではなく計算の細かさ）----------------------------
    #: 適合建築物の階段状近似の層数。多いほど真の包絡形に近づきます。
    sky_reference_layers: int = 20

    #: 天空率の方位の分割数。
    sky_azimuth_count: int = 72

    #: 天空率の測定点の間隔(m)。`None` なら条文の間隔（令135条の9〜11）。
    #: 値を入れるとそこまで細かくできますが、条文より粗くはできません。
    sky_measurement_interval_m: Optional[float] = None

    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("プロファイルには name が必要です")
        if self.ground_average_method not in GROUND_AVERAGE_METHODS:
            raise ValueError(
                f"ground_average_method は {GROUND_AVERAGE_METHODS} のいずれかです"
                f"（指定値: {self.ground_average_method!r}）"
            )
        if self.sky_reference_layers < 1:
            raise ValueError("sky_reference_layers は1以上にしてください")
        if self.sky_azimuth_count < 4:
            raise ValueError("sky_azimuth_count は4以上にしてください")
        if (self.sky_measurement_interval_m is not None
                and self.sky_measurement_interval_m <= 0):
            raise ValueError("sky_measurement_interval_m は正の値にしてください")
        if self.corner_region_method not in CORNER_REGION_METHODS:
            raise ValueError(
                f"corner_region_method は {CORNER_REGION_METHODS} のいずれかです"
                f"（指定値: {self.corner_region_method!r}）"
            )
        if self.corner_region_method not in SUPPORTED_CORNER_REGION_METHODS:
            raise UndeterminedRegulation(
                f"出隅敷地の区域の切り方 {self.corner_region_method!r} は"
                "実装していません。JCBA 報告書（平成22年）は「広い道路に垂直」と"
                "「敷地の角地を起点に円弧状」の2つを挙げ、いずれも可としていますが、"
                "MVCE が実装しているのは垂直（街区主義）のほうだけです。"
            )
        if self.one_road_angle_deg is not None and not 0 < self.one_road_angle_deg < 360:
            raise ValueError("one_road_angle_deg は0より大きく360未満にしてください")
        if self.continuous_adjacent_boundary:
            raise UndeterminedRegulation(
                "「連続した一の隣地境界線」として敷地を区分しない運用は"
                "実装していません。MVCE は辺ごとに算定位置を作る"
                "「敷地区分方式」です（JCBA 報告書 平成22年 3.一の隣地境界線）。"
            )
        if self.level_region_split_method is not None:
            raise UndeterminedRegulation(
                f"高低差区分区域の切り方 {self.level_region_split_method!r} を"
                "指定されましたが、MVCE は高低差区分区域そのものを実装して"
                "いません（令135条の7第3項等）。JCBA 報告書（平成22年）も"
                "「建築物から敷地境界線まで間の区分の方法については法文上の"
                "明確な規定がない」と認めています。"
            )
        if self.sky_region_split_method is not None:
            raise UndeterminedRegulation(
                f"天空率の区域分割方式 {self.sky_region_split_method!r} は"
                "実装していません。令135条の6第3項・令135条の9第3項が求める"
                "区域ごとの比較は、条文どおりの令132条の区域"
                "（regulations/road_regions.py）で実装しました。方式を"
                "名指しで切り替えたい場合は、その方式を定めた文書が要ります。"
            )
        if self.name != "statutory" and self.source is None:
            raise ValueError(
                f"プロファイル {self.name!r} には source が必要です（原則F）。"
                "どの行政庁の、いつ確認した、どの文書に基づく運用かを"
                "書いてください。"
            )

    @property
    def ground_weighted(self) -> bool:
        """`ground.average_ground_level()` の `weighted` 引数。"""
        return self.ground_average_method == "length_weighted"

    def with_(self, **changes: Any) -> "ComplianceProfile":
        return replace(self, **changes)

    def describe_ja(self) -> list[str]:
        lines = [f"プロファイル: {self.name}"]
        if self.source is not None:
            lines.append(f"  出典: {self.source}")
        lines.append(
            "  隣地斜線の線路敷: "
            + ("緩和対象に含める" if self.railway_is_adjacent_relaxation
               else "含めない（条文の列挙どおり）")
        )
        lines.append(
            "  日影のみなし境界線の公園・広場: "
            + ("含める" if self.park_is_deemed_boundary
               else "含めない（条文の列挙どおり）")
        )
        lines.append(
            "  令134条2項（選択規定）: "
            + ("使う" if self.apply_article_134_2 else "使わない（令132条1項による）")
        )
        lines.append(
            "  令2条2項の平均の高さ: "
            + ("接地線に沿った長さ加重平均" if self.ground_weighted
               else "接地位置の単純平均")
        )
        lines.append(
            "  令132条の出隅の区域: "
            + ("広い道路に垂直（街区主義）" if self.corner_region_method == "perpendicular"
               else self.corner_region_method)
        )
        if self.one_road_angle_deg is not None:
            lines.append(
                f"  一の道路とみなす屈曲角度: {self.one_road_angle_deg:.0f}度超"
                "（記録のみ。辺の併合は利用者が入力で行う）"
            )
        lines.extend(f"  {n}" for n in self.notes)
        return lines


#: 条文だけから決まる既定。行政庁の運用も選択規定も使わない保守側。
STATUTORY_PROFILE = ComplianceProfile(name="statutory")
