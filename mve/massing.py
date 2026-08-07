"""建物ボリュームの表現.

`Block` は「平面形状 × 高さ範囲」の水平スラブです。建物全体は Block の
リストで表します。MVEのボクセル最適化（`optimizer.py`）では、メッシュの
各セルを積み上げた柱が Block の集まりになります。
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon


@dataclass
class Block:
    footprint: Polygon
    z_bottom: float
    z_top: float

    def __post_init__(self) -> None:
        if self.z_top <= self.z_bottom:
            raise ValueError("z_top は z_bottom より大きい必要があります")
        if self.footprint.is_empty:
            raise ValueError("平面形状が空です")

    @property
    def height(self) -> float:
        return self.z_top - self.z_bottom

    @property
    def volume(self) -> float:
        return self.footprint.area * self.height


def total_volume(blocks: list[Block]) -> float:
    return sum(b.volume for b in blocks)


def max_height(blocks: list[Block]) -> float:
    return max((b.z_top for b in blocks), default=0.0)


def footprint_area(blocks: list[Block]) -> float:
    """建築面積（最下層の水平投影面積）.

    正確には全ブロックの水平投影の和集合ですが、下層ほど大きい積み方
    （建築物として自然な形）では最下層の面積と一致します。
    """
    if not blocks:
        return 0.0
    lowest = min(b.z_bottom for b in blocks)
    ground = [b.footprint for b in blocks if abs(b.z_bottom - lowest) < 1e-9]
    if not ground:
        return 0.0
    union = ground[0]
    for poly in ground[1:]:
        union = union.union(poly)
    return union.area


def total_floor_area(blocks: list[Block], floor_height_m: float) -> float:
    """延床面積（概算）.

    体積 ÷ 階高 として求めます。ブロックの刻み方に依存しない値になります
    （容積率算定床面積の各種不算入は考慮していません）。
    """
    return total_volume(blocks) / floor_height_m
