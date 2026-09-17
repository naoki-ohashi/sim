"""階別の床（MVCE3 基本設計書 3.1節）.

`solvers/optimizer.py` の `_floors_to_blocks` は、同じ階に属するマスを
1つ以上の多角形にまとめた `Block` のリストを返します
（`Block.z_bottom == level * floor_height_m`、`z_top - z_bottom ==
floor_height_m` が常に成り立ちます — `envelope_family` が
voxel / lean_to / ridge のいずれでも、最終的な `floors` 配列は
「マスごとの階数」という同じ形なので、このモジュールは全ての
`envelope_family` にそのまま使えます）。

このモジュールは**新しい計算を何もしません**。同じ階の `Block` をまとめて
「階」という単位に組み直すだけです。床面積は、その階に属する `Block` の
`footprint` 面積の合計です。

**用途別内訳・容積率不算入部分は持っていません。** 令2条1項4号（吹抜け・
共同住宅の共用廊下等）、令2条3項（自動車車庫等の緩和）といった不算入は
実装されていないので、ここでの「床面積」は最大ボリューム計算の外郭線を
そのまま床の輪郭とみなした近似値です（`docs/mvce/design_spec.md` 6.1節と
同じ限界。確認申請の床面積表としてはそのまま使えません）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon

from .massing import Block


@dataclass
class FloorSlab:
    """1つの階にまとめた床。分棟等で複数の多角形に分かれることがあります。"""

    level: int                       # 0始まりの階番号（0 = 1階）
    z_bottom: float
    z_top: float
    footprints: list[Polygon] = field(default_factory=list)

    @property
    def label_ja(self) -> str:
        return f"{self.level + 1}階"

    @property
    def area_m2(self) -> float:
        return sum(p.area for p in self.footprints)

    @property
    def has_holes(self) -> bool:
        """階の輪郭に中抜き（内側の穴）があるか。

        メッシュの周囲だけが採用されて内側が不採用になった場合などに
        起こり得ます。3Dモデル化（`model3d/`）で扱いが変わるため、
        床面積表にも注記を出します。
        """
        return any(len(p.interiors) > 0 for p in self.footprints)


def floors_from_blocks(blocks: list[Block], floor_height_m: float) -> list[FloorSlab]:
    """`Block` のリストを階ごとにまとめる。

    `level = round(z_bottom / floor_height_m)`。浮動小数の一致比較を避け、
    丸め誤差に強くするため四捨五入で階番号を求めます。
    """
    if floor_height_m <= 0:
        raise ValueError("floor_height_m は正の値にしてください")

    by_level: dict[int, list[Polygon]] = {}
    for b in blocks:
        level = round(b.z_bottom / floor_height_m)
        by_level.setdefault(level, []).append(b.footprint)

    floors: list[FloorSlab] = []
    for level in sorted(by_level):
        floors.append(FloorSlab(
            level=level,
            z_bottom=level * floor_height_m,
            z_top=(level + 1) * floor_height_m,
            footprints=by_level[level],
        ))
    return floors


def total_floor_area_m2(floors: list[FloorSlab]) -> float:
    """全階の床面積の合計。

    `OptimizeResult.total_floor_area_m2`（体積 ÷ 階高）と数学的に一致します
    （`_floors_to_blocks` が作る各 `Block` の高さは必ず `floor_height_m` の
    ため）。`tests/mvce/test_floors.py` がこの一致を検証しています。
    """
    return sum(f.area_m2 for f in floors)
