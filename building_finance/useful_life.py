"""法定耐用年数（減価償却資産の耐用年数等に関する省令）の判定.

構造・用途別の主な法定耐用年数と、中古資産を取得した場合の耐用年数の
見積り（簡便法）を扱う。

注意: ここに収録しているのは実務でよく使われる代表的な構造・用途の
組み合わせのみで、省令別表第一の全区分を網羅したものではない。
未収録の組み合わせや特殊な設備（建物附属設備等）は、実際の省令・
別表を確認して `useful_life_years_override` 等で個別に指定すること。
"""
from __future__ import annotations

from enum import Enum


class StructureType(Enum):
    """建物の構造・骨格材."""

    #: 鉄筋コンクリート造(RC造)・鉄骨鉄筋コンクリート造(SRC造)
    RC_SRC = "rc_src"
    #: 重量鉄骨造（骨格材の肉厚が4mm超）
    HEAVY_STEEL = "heavy_steel"
    #: 軽量鉄骨造（骨格材の肉厚3mm超4mm以下）
    LIGHT_STEEL = "light_steel"
    #: 木造・合成樹脂造
    WOOD = "wood"
    #: 木造モルタル造
    WOOD_MORTAR = "wood_mortar"


class BuildingUse(Enum):
    """建物の用途区分."""

    #: 住宅用（戸建て・共同住宅・マンション等）
    RESIDENTIAL = "residential"
    #: 事務所用
    OFFICE = "office"
    #: 店舗用・飲食店用
    STORE_RESTAURANT = "store_restaurant"
    #: ホテル・旅館用
    HOTEL_RYOKAN = "hotel_ryokan"
    #: 共同住宅・工場・倉庫用（重量鉄骨造の省令上の区分）
    APARTMENT_FACTORY_WAREHOUSE = "apartment_factory_warehouse"


#: 構造・用途別の法定耐用年数（年）
USEFUL_LIFE_TABLE: dict[StructureType, dict[BuildingUse, int]] = {
    StructureType.RC_SRC: {
        BuildingUse.RESIDENTIAL: 47,
        BuildingUse.OFFICE: 50,
        BuildingUse.STORE_RESTAURANT: 39,
        BuildingUse.HOTEL_RYOKAN: 39,
    },
    StructureType.HEAVY_STEEL: {
        BuildingUse.RESIDENTIAL: 34,
        BuildingUse.OFFICE: 38,
        BuildingUse.STORE_RESTAURANT: 31,
        BuildingUse.APARTMENT_FACTORY_WAREHOUSE: 34,
    },
    StructureType.LIGHT_STEEL: {
        BuildingUse.RESIDENTIAL: 27,
        BuildingUse.OFFICE: 30,
        BuildingUse.STORE_RESTAURANT: 25,
    },
    StructureType.WOOD: {
        BuildingUse.RESIDENTIAL: 22,
        BuildingUse.OFFICE: 24,
        BuildingUse.STORE_RESTAURANT: 20,
    },
    StructureType.WOOD_MORTAR: {
        BuildingUse.RESIDENTIAL: 20,
        BuildingUse.OFFICE: 22,
    },
}


def statutory_useful_life(structure: StructureType, use: BuildingUse) -> int:
    """構造・用途から法定耐用年数（年）を返す.

    未収録の組み合わせは ``KeyError`` を送出する。
    """
    try:
        return USEFUL_LIFE_TABLE[structure][use]
    except KeyError as exc:
        raise KeyError(
            f"法定耐用年数テーブルに未収録の組み合わせです: "
            f"structure={structure.value}, use={use.value}"
        ) from exc


def used_property_useful_life(statutory_years: int, elapsed_years: float) -> int:
    """中古資産の耐用年数を簡便法で見積もる.

    - 法定耐用年数の全部を経過している場合:
      ``法定耐用年数 × 0.2``（1年未満切捨て、最短2年）
    - 法定耐用年数の一部を経過している場合:
      ``(法定耐用年数 − 経過年数) + 経過年数 × 0.2``（1年未満切捨て、最短2年）

    Args:
        statutory_years: その構造・用途の法定耐用年数.
        elapsed_years: 取得時点で建築後経過している年数.
    """
    if statutory_years <= 0:
        raise ValueError("statutory_years は正の値を指定してください")
    if elapsed_years < 0:
        raise ValueError("elapsed_years は0以上の値を指定してください")

    if elapsed_years >= statutory_years:
        years = int(statutory_years * 0.2)
    else:
        years = int((statutory_years - elapsed_years) + elapsed_years * 0.2)
    return max(years, 2)
