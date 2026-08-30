"""`Room` のリストを、そのまま表に書ける行の並びに変換する。"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from .rooms import Room

NAME_HEADER = "部屋名"
LEVEL_HEADER = "階"
AREA_HEADER = "床面積 (㎡)"

#: 表に出す小数点以下の桁数。
DECIMALS = 2


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, DECIMALS)


def build_table(rooms: Iterable[Room]) -> tuple:
    """(見出しの行, データ行のリスト) を返す。

    * 行の並びは文書順です。階（グループ）が2つ以上ある場合だけ、階ごとに
      まとめて「◯◯ 小計」の行を挟みます。
    * どの部屋にも階が無い場合は「階」列そのものを出しません。
    * 最後に必ず「合計」の行を付けます。面積が取れなかった部屋は空欄に
      なり、小計・合計には含めません。
    """
    rooms = list(rooms)
    levels = [r.level for r in rooms if r.level]
    with_level = bool(levels)
    grouped = len(dict.fromkeys(levels)) > 1 and all(r.level for r in rooms)

    headers = [NAME_HEADER] + ([LEVEL_HEADER] if with_level else []) + [AREA_HEADER]

    def row(name: str, level: str, area: Optional[float]) -> list:
        return [name] + ([level] if with_level else []) + [_round(area)]

    body: list = []
    if grouped:
        order = list(dict.fromkeys(r.level for r in rooms))
        for level in order:
            members = [r for r in rooms if r.level == level]
            for room in members:
                body.append(row(room.name, room.level, room.floor_area_m2))
            subtotal = sum(
                r.floor_area_m2 for r in members if r.floor_area_m2 is not None
            )
            body.append(row(f"{level} 小計", level, subtotal))
    else:
        for room in rooms:
            body.append(row(room.name, room.level, room.floor_area_m2))

    total = sum(r.floor_area_m2 for r in rooms if r.floor_area_m2 is not None)
    body.append(row("合計", "", total))
    return headers, body


def is_summary_row(row: Sequence) -> bool:
    """「小計」「合計」の行かどうか（強調表示に使います）。"""
    name = row[0] if row else ""
    return isinstance(name, str) and (name == "合計" or name.endswith("小計"))
