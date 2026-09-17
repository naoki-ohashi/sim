"""定額法による減価償却の計算.

建物の減価償却は平成10年度税制改正以降、定額法に一本化されている。
償却率は「減価償却資産の耐用年数等に関する省令」別表第七のとおり、
``1 ÷ 耐用年数`` を小数点以下3桁に切り上げた値を用いる。
"""
from __future__ import annotations

import math

#: 残存簿価として残す備忘価額（円）。定額法では帳簿価額をこの金額まで償却する。
MEMORANDUM_VALUE = 1.0


def straight_line_rate(useful_life_years: int) -> float:
    """耐用年数から定額法の償却率を求める（1÷耐用年数を小数点3桁に切り上げ）."""
    if useful_life_years < 2:
        raise ValueError("useful_life_years は2以上を指定してください")
    return math.ceil(1000 / useful_life_years) / 1000


def depreciation_schedule(acquisition_cost: float, useful_life_years: int) -> list[float]:
    """取得価額・耐用年数から年ごとの減価償却費の一覧を返す（定額法）.

    最終年は帳簿価額が備忘価額（1円）に達するまでの残額とする。
    償却率が ``1/耐用年数`` を切り上げた値のため、耐用年数より
    早く償却が終わることがある。

    Args:
        acquisition_cost: 建物の取得価額（円）。土地を含めないこと。
        useful_life_years: 耐用年数（年）。
    """
    if acquisition_cost <= MEMORANDUM_VALUE:
        raise ValueError("acquisition_cost は備忘価額を上回る金額を指定してください")

    rate = straight_line_rate(useful_life_years)
    annual_amount = acquisition_cost * rate

    schedule: list[float] = []
    book_value = acquisition_cost
    while book_value > MEMORANDUM_VALUE:
        amount = min(annual_amount, book_value - MEMORANDUM_VALUE)
        schedule.append(amount)
        book_value -= amount
    return schedule
