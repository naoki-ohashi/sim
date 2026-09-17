"""建物ごとの年次収支（賃貸事業の損益・キャッシュフロー）計算.

法定耐用年数から求めた減価償却費を、賃貸収入・諸経費とあわせて
年次の収支に反映する。ローン返済（元金・利息）は対象外で、
NOI（営業純収益）ベースの簡易な収支・税引後キャッシュフローを求める。
"""
from __future__ import annotations

from dataclasses import dataclass

from .depreciation import depreciation_schedule
from .useful_life import (
    BuildingUse,
    StructureType,
    statutory_useful_life,
    used_property_useful_life,
)


@dataclass
class Building:
    """収支計算の対象となる建物（土地部分は含まない）."""

    name: str
    structure: StructureType
    use: BuildingUse
    #: 建物の取得価額（円）。土地は含めない。
    acquisition_cost: float
    #: 中古資産として取得したか
    is_used_property: bool = False
    #: 中古資産の場合、取得時点で建築後経過している年数
    elapsed_years_at_acquisition: float = 0.0
    #: 耐用年数を明示的に指定する場合（省略時は法定耐用年数／簡便法から自動算出）
    useful_life_years_override: int | None = None

    @property
    def useful_life_years(self) -> int:
        """減価償却に用いる耐用年数（年）."""
        if self.useful_life_years_override is not None:
            return self.useful_life_years_override

        statutory = statutory_useful_life(self.structure, self.use)
        if self.is_used_property:
            return used_property_useful_life(statutory, self.elapsed_years_at_acquisition)
        return statutory

    @property
    def depreciation_schedule(self) -> list[float]:
        """取得年を1年目とした年次の減価償却費一覧."""
        return depreciation_schedule(self.acquisition_cost, self.useful_life_years)


@dataclass
class AnnualIncomeExpense:
    """1年分の収支."""

    #: 取得年を1年目とした経過年数
    year: int
    gross_rent_income: float
    operating_expenses: float
    depreciation: float
    #: NOI（営業純収益） = 賃貸収入 − 諸経費（減価償却は含まない）
    noi: float
    #: 課税所得 = NOI − 減価償却費
    taxable_income: float
    income_tax: float
    #: 税引後キャッシュフロー = NOI − 法人税等（減価償却は非資金支出のため加算不要）
    net_cash_flow: float


def annual_income_expense(
    building: Building,
    year: int,
    gross_rent_income: float,
    operating_expenses: float = 0.0,
    tax_rate: float = 0.0,
) -> AnnualIncomeExpense:
    """指定した年（取得年を1年目とする）の収支を計算する.

    Args:
        building: 対象建物.
        year: 取得年からの経過年数（1年目=取得初年度）.
        gross_rent_income: その年の総賃貸収入（円）.
        operating_expenses: その年の諸経費（管理費・修繕費・固定資産税等、減価償却を除く）.
        tax_rate: 課税所得に対する実効税率（0〜1）。課税所得が赤字の場合は課税なし。
    """
    if year < 1:
        raise ValueError("year は1以上を指定してください")

    schedule = building.depreciation_schedule
    depreciation = schedule[year - 1] if year <= len(schedule) else 0.0

    noi = gross_rent_income - operating_expenses
    taxable_income = noi - depreciation
    income_tax = max(taxable_income, 0.0) * tax_rate
    net_cash_flow = noi - income_tax

    return AnnualIncomeExpense(
        year=year,
        gross_rent_income=gross_rent_income,
        operating_expenses=operating_expenses,
        depreciation=depreciation,
        noi=noi,
        taxable_income=taxable_income,
        income_tax=income_tax,
        net_cash_flow=net_cash_flow,
    )
