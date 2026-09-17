import pytest

from building_finance.cashflow import Building, annual_income_expense
from building_finance.depreciation import straight_line_rate
from building_finance.useful_life import BuildingUse, StructureType


def test_useful_life_years_from_statutory_table():
    building = Building(
        name="RCマンション",
        structure=StructureType.RC_SRC,
        use=BuildingUse.RESIDENTIAL,
        acquisition_cost=100_000_000.0,
    )
    assert building.useful_life_years == 47


def test_useful_life_years_for_used_property():
    building = Building(
        name="築20年RCマンション",
        structure=StructureType.RC_SRC,
        use=BuildingUse.RESIDENTIAL,
        acquisition_cost=100_000_000.0,
        is_used_property=True,
        elapsed_years_at_acquisition=20,
    )
    assert building.useful_life_years == 31


def test_useful_life_years_override_takes_precedence():
    building = Building(
        name="任意指定",
        structure=StructureType.RC_SRC,
        use=BuildingUse.RESIDENTIAL,
        acquisition_cost=100_000_000.0,
        useful_life_years_override=10,
    )
    assert building.useful_life_years == 10


def test_annual_income_expense_first_year():
    cost = 50_000_000.0
    building = Building(
        name="木造アパート",
        structure=StructureType.WOOD,
        use=BuildingUse.RESIDENTIAL,
        acquisition_cost=cost,
    )
    result = annual_income_expense(
        building,
        year=1,
        gross_rent_income=6_000_000.0,
        operating_expenses=1_500_000.0,
        tax_rate=0.3,
    )

    expected_depreciation = cost * straight_line_rate(22)
    expected_noi = 6_000_000.0 - 1_500_000.0
    expected_taxable_income = expected_noi - expected_depreciation
    expected_tax = expected_taxable_income * 0.3

    assert result.depreciation == pytest.approx(expected_depreciation)
    assert result.noi == pytest.approx(expected_noi)
    assert result.taxable_income == pytest.approx(expected_taxable_income)
    assert result.income_tax == pytest.approx(expected_tax)
    assert result.net_cash_flow == pytest.approx(expected_noi - expected_tax)


def test_annual_income_expense_no_tax_when_taxable_income_is_negative():
    building = Building(
        name="小規模建物",
        structure=StructureType.WOOD,
        use=BuildingUse.RESIDENTIAL,
        acquisition_cost=50_000_000.0,
    )
    result = annual_income_expense(
        building,
        year=1,
        gross_rent_income=1_000_000.0,
        operating_expenses=900_000.0,
        tax_rate=0.3,
    )

    assert result.taxable_income < 0
    assert result.income_tax == 0.0
    assert result.net_cash_flow == pytest.approx(result.noi)


def test_annual_income_expense_after_full_depreciation_has_no_depreciation_expense():
    building = Building(
        name="償却済み建物",
        structure=StructureType.WOOD,
        use=BuildingUse.RESIDENTIAL,
        acquisition_cost=50_000_000.0,
    )
    schedule_length = len(building.depreciation_schedule)
    result = annual_income_expense(
        building,
        year=schedule_length + 1,
        gross_rent_income=6_000_000.0,
        operating_expenses=1_500_000.0,
    )
    assert result.depreciation == 0.0


def test_annual_income_expense_rejects_invalid_year():
    building = Building(
        name="建物",
        structure=StructureType.WOOD,
        use=BuildingUse.RESIDENTIAL,
        acquisition_cost=50_000_000.0,
    )
    with pytest.raises(ValueError):
        annual_income_expense(building, year=0, gross_rent_income=1.0)
