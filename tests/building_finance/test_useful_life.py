import pytest

from building_finance.useful_life import (
    BuildingUse,
    StructureType,
    statutory_useful_life,
    used_property_useful_life,
)


@pytest.mark.parametrize(
    "structure, use, expected",
    [
        (StructureType.RC_SRC, BuildingUse.RESIDENTIAL, 47),
        (StructureType.RC_SRC, BuildingUse.OFFICE, 50),
        (StructureType.RC_SRC, BuildingUse.STORE_RESTAURANT, 39),
        (StructureType.RC_SRC, BuildingUse.HOTEL_RYOKAN, 39),
        (StructureType.HEAVY_STEEL, BuildingUse.RESIDENTIAL, 34),
        (StructureType.HEAVY_STEEL, BuildingUse.OFFICE, 38),
        (StructureType.HEAVY_STEEL, BuildingUse.STORE_RESTAURANT, 31),
        (StructureType.HEAVY_STEEL, BuildingUse.APARTMENT_FACTORY_WAREHOUSE, 34),
        (StructureType.LIGHT_STEEL, BuildingUse.RESIDENTIAL, 27),
        (StructureType.LIGHT_STEEL, BuildingUse.OFFICE, 30),
        (StructureType.LIGHT_STEEL, BuildingUse.STORE_RESTAURANT, 25),
        (StructureType.WOOD, BuildingUse.RESIDENTIAL, 22),
        (StructureType.WOOD, BuildingUse.OFFICE, 24),
        (StructureType.WOOD, BuildingUse.STORE_RESTAURANT, 20),
        (StructureType.WOOD_MORTAR, BuildingUse.RESIDENTIAL, 20),
        (StructureType.WOOD_MORTAR, BuildingUse.OFFICE, 22),
    ],
)
def test_statutory_useful_life_table(structure, use, expected):
    assert statutory_useful_life(structure, use) == expected


def test_statutory_useful_life_unknown_combination_raises():
    with pytest.raises(KeyError):
        statutory_useful_life(StructureType.WOOD_MORTAR, BuildingUse.HOTEL_RYOKAN)


def test_used_property_fully_elapsed():
    # 築25年の木造住宅（法定22年）→ 22 * 0.2 = 4.4 → 4年
    assert used_property_useful_life(22, 25) == 4


def test_used_property_partially_elapsed():
    # 築20年のRC造マンション（法定47年）→ (47-20) + 20*0.2 = 31年
    assert used_property_useful_life(47, 20) == 31


def test_used_property_useful_life_has_floor_of_two_years():
    # 法定耐用年数が短い資産が全部経過していても、最短2年を下回らない
    assert used_property_useful_life(5, 20) == 2


def test_used_property_useful_life_rejects_invalid_input():
    with pytest.raises(ValueError):
        used_property_useful_life(0, 1)
    with pytest.raises(ValueError):
        used_property_useful_life(10, -1)
