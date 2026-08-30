"""審査機関別プロファイル — 天空率の方式差を外部化する仕組み。

基本設計の原則A: 天空率の適合建築物・算定位置の生成には統一見解が
存在しない部分があり、同じ敷地でも東京都方式・JCBA方式・新JCBA方式・
JCBO方式で結果が変わります。方式差はコードの `if` ではなく
`ComplianceProfile` のフィールドとして外部化します。

**2026-08-30 に骨組みを実装しました**（`schema.py` / `loader.py` /
`builtin/statutory.yaml`）。いま持っているのは次の3種類です。

1. 特定行政庁の運用（隣地斜線の線路敷、日影のみなし境界線の公園）
2. 選択規定（令134条2項）
3. 条文が決めていない点の解釈（令2条2項の「平均の高さ」の取り方）

ほかに計算の細かさ（適合建築物の層数・方位の分割数・測定点の間隔）も
ここで持ちます。

**東京都方式・JCBA方式などの「方式」はまだ入っていません。** 天空率の
区域分割（令135条の6第3項）や高低差区分区域の切り方は方式で分かれますが、
方式を定めた文書を取得できていないので実装していません。
`sky_region_split_method` に値を入れると `UndeterminedRegulation` で
止まります。推測で方式を書くくらいなら止めるほうが安全です。

既定は条文だけの `statutory` で、行政庁の運用も選択規定も使わない保守側
です。行政庁に合わせるプロファイルには `source` が必須です（原則F）。
"""

from .loader import builtin_names, load_profile, profile_from_dict
from .schema import STATUTORY_PROFILE, ComplianceProfile

__all__ = [
    "ComplianceProfile", "STATUTORY_PROFILE",
    "builtin_names", "load_profile", "profile_from_dict",
]
