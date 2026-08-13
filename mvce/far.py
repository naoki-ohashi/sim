"""容積率の算定（法52条1項・2項）.

前面道路の幅員が12m未満のときは、指定容積率（都市計画で定めた容積率）と
「前面道路の幅員 × 低減係数」の**小さい方**が上限になります（法52条2項）。

    低減係数: 住居系 4/10、その他 6/10

前面道路が2以上ある場合は、**最大幅員**の道路で判定します。
（特定行政庁が定める場合の割増、特定道路による緩和（法52条9項）などは
未対応です。該当しそうな場合は `notes` に注意書きが出ます。）
"""
from __future__ import annotations

from dataclasses import dataclass

from .zoning import FAR_ROAD_COEFFICIENT, FAR_ROAD_WIDTH_THRESHOLD_M, zone_group


@dataclass
class FarResult:
    designated_far: float          # 都市計画で定められた容積率（比）
    road_far: float | None         # 前面道路幅員による上限（比）。12m以上なら None
    effective_far: float           # 実際に適用される容積率（比）
    max_road_width_m: float
    coefficient: float | None
    notes: list[str]

    @property
    def limited_by_road(self) -> bool:
        return self.road_far is not None and self.road_far < self.designated_far


def compute_far(site) -> FarResult:
    """敷地に適用される容積率を求める。"""
    designated = site.zoning.far_ratio
    max_width = site.max_road_width_m
    notes: list[str] = []

    if max_width <= 0:
        notes.append(
            "前面道路が設定されていません。法52条2項の判定ができないため"
            "指定容積率をそのまま使っています（接道義務の確認も別途必要です）。"
        )
        return FarResult(designated, None, designated, 0.0, None, notes)

    if max_width >= FAR_ROAD_WIDTH_THRESHOLD_M:
        notes.append(
            f"前面道路の最大幅員が{max_width:.1f}mで12m以上のため、"
            "法52条2項による低減はありません。"
        )
        return FarResult(designated, None, designated, max_width, None, notes)

    coefficient = FAR_ROAD_COEFFICIENT[zone_group(site.zoning.zone_type)]
    road_far = max_width * coefficient
    effective = min(designated, road_far)

    notes.append(
        f"法52条2項: 前面道路の最大幅員{max_width:.1f}m × {coefficient:.1f} "
        f"= {road_far * 100:.0f}%（指定容積率 {designated * 100:.0f}%）"
    )
    if road_far < designated:
        notes.append(
            f"→ 前面道路幅員により容積率が {effective * 100:.0f}% に制限されます。"
        )
    if len(site.road_edges) > 1:
        notes.append(
            f"前面道路が{len(site.road_edges)}本あるため、最大幅員"
            f"{max_width:.1f}mで判定しています。"
        )
    notes.append(
        "特定道路による緩和（法52条9項）や特定行政庁が定める割増は未対応です。"
        "該当する可能性がある場合は別途確認してください。"
    )
    return FarResult(designated, road_far, effective, max_width, coefficient, notes)


def effective_far_ratio(site) -> float:
    return compute_far(site).effective_far
