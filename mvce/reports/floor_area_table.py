"""各階床面積表（MVCE3 基本設計書 3.2節）.

`floors_from_blocks()` が返す `FloorSlab` を、そのまま Excel（.xlsx）に
書き出せる表の形に組み立てます。**新しい面積計算はしていません** —
`OptimizeResult.blocks` を階ごとに集計するだけです（`mvce/floors.py`）。

対象外・未実装のもの（読み手に必ず伝える。原則H）:

- 用途別の内訳（住戸・共用部・駐車場等）
- 容積率に算入しない部分（令2条1項4号: 吹抜け・共同住宅の共用廊下等、
  令2条3項: 自動車車庫等の緩和）
- 壁芯／内法の別

このエンジンの外郭線（メッシュの採用マスを結合した多角形）をそのまま
床の輪郭とみなした近似値です。確認申請用の床面積表としてはそのまま
使えません（`docs/mvce/disclaimer.md` と同じ限界）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..floors import FloorSlab, floors_from_blocks
from ..solvers.optimizer import OptimizeResult

TITLE_JA = "各階床面積表（MVCE3 近似値）"

DISCLAIMER_JA = (
    "この表はMVCEの最大ボリューム計算結果から機械的に算定した近似値です。"
    "壁芯・内法の別、容積率不算入部分（令2条1項4号・令2条3項等）、"
    "用途別の内訳は反映していません。確認申請の床面積表としてそのまま"
    "使うことはできません。"
)


@dataclass
class FloorAreaRow:
    level: int
    label_ja: str
    z_bottom_m: float
    z_top_m: float
    area_m2: float
    cumulative_area_m2: float
    note: str = ""


@dataclass
class FloorAreaTable:
    site_name: str
    rows: list[FloorAreaRow]
    total_floor_area_m2: float
    building_area_m2: float          # 建築面積（最下階の床面積で近似）
    site_area_m2: float
    coverage_ratio_achieved: float | None    # 建築面積 / 敷地面積
    far_achieved: float                      # 延床面積 / 敷地面積
    far_effective: float                     # 適用容積率（法52条1・2・7・9項）
    notes: list[str] = field(default_factory=list)

    @property
    def floor_count(self) -> int:
        return len(self.rows)


def build_floor_area_table(result: OptimizeResult) -> FloorAreaTable:
    """`OptimizeResult` から各階床面積表を組み立てる。"""
    floors: list[FloorSlab] = floors_from_blocks(result.blocks, result.site.floor_height_m)

    rows: list[FloorAreaRow] = []
    cumulative = 0.0
    for f in floors:
        cumulative += f.area_m2
        note = "分棟あり" if len(f.footprints) > 1 else ""
        if f.has_holes:
            note = (note + "・" if note else "") + "中抜きあり（表示は外周のみ）"
        rows.append(FloorAreaRow(
            level=f.level, label_ja=f.label_ja, z_bottom_m=f.z_bottom,
            z_top_m=f.z_top, area_m2=f.area_m2, cumulative_area_m2=cumulative,
            note=note,
        ))

    site_area = result.site.area_m2
    building_area = rows[0].area_m2 if rows else 0.0
    notes = [DISCLAIMER_JA]
    notes.extend(result.notes)

    return FloorAreaTable(
        site_name=result.site.name or "(無題)",
        rows=rows,
        total_floor_area_m2=cumulative,
        building_area_m2=building_area,
        site_area_m2=site_area,
        coverage_ratio_achieved=(building_area / site_area) if site_area else None,
        far_achieved=result.far_achieved,
        far_effective=result.far.effective_far,
        notes=notes,
    )


# --- Excel 出力 --------------------------------------------------------

_HEADER_JA = ["階", "階高下端(m)", "階高上端(m)", "床面積(m2)", "累計延床面積(m2)", "備考"]


def write_floor_area_table_xlsx(table: FloorAreaTable, path: str) -> None:
    """各階床面積表を .xlsx に書き出す。

    `openpyxl` が要ります（`pip install openpyxl` または
    `pip install "jwcad-volume[xlsx]"`）。未インストールなら
    分かりやすいメッセージで `ImportError` を出します。
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover - 依存未導入時の経路
        raise ImportError(
            "各階床面積表のExcel出力には openpyxl が必要です。"
            "`pip install openpyxl` を実行してください。"
        ) from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "各階床面積表"

    bold = Font(bold=True)
    center = Alignment(horizontal="center")

    ws["A1"] = TITLE_JA
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"敷地: {table.site_name}"
    ws["A3"] = f"敷地面積: {table.site_area_m2:.2f} m2"

    header_row = 5
    for col, text in enumerate(_HEADER_JA, start=1):
        cell = ws.cell(row=header_row, column=col, value=text)
        cell.font = bold
        cell.alignment = center

    row_i = header_row + 1
    # 上階から表示する（確認申請の慣例に合わせる）
    for row in reversed(table.rows):
        ws.cell(row=row_i, column=1, value=row.label_ja)
        ws.cell(row=row_i, column=2, value=round(row.z_bottom_m, 3))
        ws.cell(row=row_i, column=3, value=round(row.z_top_m, 3))
        ws.cell(row=row_i, column=4, value=round(row.area_m2, 2))
        ws.cell(row=row_i, column=5, value=round(row.cumulative_area_m2, 2))
        ws.cell(row=row_i, column=6, value=row.note)
        row_i += 1

    total_row = row_i
    ws.cell(row=total_row, column=1, value="合計").font = bold
    ws.cell(row=total_row, column=4, value=round(table.total_floor_area_m2, 2)).font = bold

    info_row = total_row + 2
    info_lines = [
        f"建築面積: {table.building_area_m2:.2f} m2"
        + (f"（建蔽率 {table.coverage_ratio_achieved * 100:.1f}%）"
           if table.coverage_ratio_achieved is not None else ""),
        f"延床面積: {table.total_floor_area_m2:.2f} m2"
        f"（容積率 {table.far_achieved * 100:.1f}% / 適用容積率 "
        f"{table.far_effective * 100:.0f}%）",
        "",
        DISCLAIMER_JA,
    ]
    for offset, line in enumerate(info_lines):
        ws.cell(row=info_row + offset, column=1, value=line)

    widths = [10, 12, 12, 14, 16, 30]
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

    wb.save(path)
