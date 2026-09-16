"""各階床面積表（mvce/reports/floor_area_table.py）のテスト。"""
import pytest

openpyxl = pytest.importorskip("openpyxl")

from mvce.reports.floor_area_table import build_floor_area_table, write_floor_area_table_xlsx
from mvce.solvers.optimizer import OptimizeOptions, optimize
from mvce.site import Site
from mvce.zoning import ZoningParams

SQUARE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]


def _site(far=2.0, coverage=0.6, zone="1res", road_width=6.0, name="テスト敷地"):
    specs = [
        {"kind": "road", "road_width_m": road_width},
        {"kind": "adjacent"},
        {"kind": "adjacent"},
        {"kind": "adjacent"},
    ]
    return Site.from_rings(SQUARE, specs, ZoningParams(zone, far, coverage), name=name)


def _result():
    return optimize(_site(), None, OptimizeOptions(cell_size_x_m=3.0, cell_size_y_m=3.0))


def test_build_floor_area_table_orders_rows_by_level():
    table = build_floor_area_table(_result())
    assert table.site_name == "テスト敷地"
    assert [r.level for r in table.rows] == sorted(r.level for r in table.rows)
    assert table.rows[0].level == 0
    # 累計は単調非減少
    cumulative = [r.cumulative_area_m2 for r in table.rows]
    assert cumulative == sorted(cumulative)
    assert table.total_floor_area_m2 == pytest.approx(cumulative[-1])


def test_building_area_matches_ground_floor():
    result = _result()
    table = build_floor_area_table(result)
    assert table.building_area_m2 == pytest.approx(result.building_area_m2, rel=1e-6)


def test_write_floor_area_table_xlsx_creates_readable_workbook(tmp_path):
    table = build_floor_area_table(_result())
    out = tmp_path / "floor_area.xlsx"
    write_floor_area_table_xlsx(table, str(out))
    assert out.exists()

    wb = openpyxl.load_workbook(str(out))
    ws = wb.active
    assert ws.title == "各階床面積表"
    header = [c.value for c in ws[5]]
    assert header[:4] == ["階", "階高下端(m)", "階高上端(m)", "床面積(m2)"]
    # ヘッダの次の行から表の行数ぶんの階が並んでいる（上階から表示）
    first_data_row = [ws.cell(row=6, column=c).value for c in range(1, 7)]
    assert first_data_row[0] == table.rows[-1].label_ja
