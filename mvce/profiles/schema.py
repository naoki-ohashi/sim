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

    #: 天空率の区域分割方式（令135条の6第3項・令135条の9第3項）。
    #: 方式を定めた文書を持っていないので、`None` 以外は受け付けません。
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
        if self.sky_region_split_method is not None:
            raise UndeterminedRegulation(
                f"天空率の区域分割方式 {self.sky_region_split_method!r} は"
                "実装していません。令135条の6第3項・令135条の9第3項が求める"
                "区域ごとの比較は、方式（東京都方式・JCBA方式等）によって"
                "切り方が違い、その方式を定めた文書を取得できていません。"
                "推測で実装しないため、前面道路が2以上ある敷地の天空率は"
                "判定できません。"
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
        lines.extend(f"  {n}" for n in self.notes)
        return lines


#: 条文だけから決まる既定。行政庁の運用も選択規定も使わない保守側。
STATUTORY_PROFILE = ComplianceProfile(name="statutory")
