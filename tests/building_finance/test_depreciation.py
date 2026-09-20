import pytest

from building_finance.depreciation import depreciation_schedule, straight_line_rate


@pytest.mark.parametrize(
    "useful_life_years, expected_rate",
    [
        (20, 0.050),
        (22, 0.046),
        (24, 0.042),
        (25, 0.040),
        (27, 0.038),
        (30, 0.034),
        (31, 0.033),
        (34, 0.030),
        (38, 0.027),
        (39, 0.026),
        (47, 0.022),
        (50, 0.020),
    ],
)
def test_straight_line_rate_matches_official_table(useful_life_years, expected_rate):
    assert straight_line_rate(useful_life_years) == pytest.approx(expected_rate)


def test_straight_line_rate_rejects_too_short_life():
    with pytest.raises(ValueError):
        straight_line_rate(1)


def test_depreciation_schedule_fully_depreciates_to_memorandum_value():
    cost = 10_000_000.0
    schedule = depreciation_schedule(cost, 22)

    assert sum(schedule) == pytest.approx(cost - 1.0)
    # 償却率(0.046)は1/22を切り上げているため、22年より早く償却が終わる
    assert len(schedule) <= 22
    # 最終年以外は毎年同額
    assert schedule[0] == pytest.approx(cost * 0.046)


def test_depreciation_schedule_rejects_cost_below_memorandum_value():
    with pytest.raises(ValueError):
        depreciation_schedule(1.0, 22)
