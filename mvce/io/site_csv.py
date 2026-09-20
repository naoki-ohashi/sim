"""CSVから敷地図を読み込む.

HBU-ANALYZER等の外部ツールが出力するポリゴンデータを想定しています。
1行1頂点、`x`/`y` 列は必須、それ以外の列は任意です。

    x,y,kind,road_width_m,wall_setback_m,relaxation_kind,relaxation_width_m,ground_level_diff_m,label
    0,0,road,6.0,1.5,,,,南側道路
    30,0,adjacent,,,,,,
    30,20,adjacent,,,water,4.0,,水路に接する
    0,20,adjacent,,,,,,

行 `i` の `kind` 以下の列は、`points[i] → points[i+1]`（次の行への辺）を
表します（`Boundary` の "辺 i = 頂点 i → 頂点 i+1" という慣習と同じです）。
`kind` 列自体が無い場合はすべての辺が「対象外」になるので、YAML側の
`site.edges` で指定してください。
"""
from __future__ import annotations

import csv

from ..geometry import Point
from .dxf_site import ImportedEdge, ImportedSitePlan, SiteImportError

_VALID_KINDS = ("road", "adjacent", "none", "")


def _float_or_none(value: str | None):
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise SiteImportError(f"数値ではありません: {value!r}") from exc


def read_site_plan_csv(
    path: str, units_per_meter: float = 1.0, encoding: str = "utf-8-sig",
) -> ImportedSitePlan:
    """CSVから敷地の外形を読み取る。

    `encoding` は既定で "utf-8-sig"（BOM付きUTF-8でもそのまま読めます）。
    Excelで保存したCSVが文字化けする場合は `encoding="shift_jis"` を
    指定してください。
    """
    scale = 1.0 / units_per_meter
    try:
        with open(path, encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
    except OSError as exc:
        raise SiteImportError(f"CSVを読み込めませんでした: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise SiteImportError(
            f"CSVの文字コードを読み取れませんでした（{encoding}として開こうとして失敗）。"
            "Excelで保存したCSVの場合は encoding: shift_jis を指定してください。"
            f" 詳細: {exc}"
        ) from exc

    if "x" not in fieldnames or "y" not in fieldnames:
        raise SiteImportError(
            f"必須列: x, y／見つかった列: {', '.join(fieldnames) if fieldnames else '（列が読み取れませんでした）'}"
        )
    if len(rows) < 3:
        raise SiteImportError(f"敷地には3点以上の行が必要です（現在: {len(rows)}行）")

    points: list[Point] = []
    for i, row in enumerate(rows):
        try:
            x = float(row["x"])
            y = float(row["y"])
        except (TypeError, ValueError) as exc:
            raise SiteImportError(
                f"{i + 2}行目: x/y が数値ではありません（x={row.get('x')!r}, y={row.get('y')!r}）"
            ) from exc
        points.append((x * scale, y * scale))

    n = len(points)
    notes: list[str] = []
    has_kind_column = "kind" in fieldnames

    if not has_kind_column:
        edges = [ImportedEdge(p1=points[i], p2=points[(i + 1) % n]) for i in range(n)]
        notes.append(
            "CSVにkind列が無いため、辺の種別はすべて「対象外」としました。"
            "YAML側の site.edges で指定してください。"
        )
        return ImportedSitePlan(points=points, edges=edges, notes=notes)

    edges = []
    for i, row in enumerate(rows):
        kind = (row.get("kind") or "").strip() or "none"
        if kind not in _VALID_KINDS:
            raise SiteImportError(
                f"{i + 2}行目: kind は road/adjacent/none のいずれかにしてください: {kind!r}"
            )
        try:
            road_width_m = _float_or_none(row.get("road_width_m"))
            wall_setback_m = _float_or_none(row.get("wall_setback_m"))
            ground_level_diff_m = _float_or_none(row.get("ground_level_diff_m"))
            relaxation_width_m = _float_or_none(row.get("relaxation_width_m"))
        except SiteImportError as exc:
            raise SiteImportError(f"{i + 2}行目: {exc}") from exc

        if kind == "road" and (road_width_m is None or road_width_m <= 0):
            raise SiteImportError(
                f"{i + 2}行目は道路境界線（kind: road）ですが、"
                "road_width_m が指定されていないか0以下です"
            )

        relaxation_kind = (row.get("relaxation_kind") or "").strip() or None
        relaxation = (
            {"kind": relaxation_kind, "width_m": relaxation_width_m or 0.0}
            if relaxation_kind else None
        )

        edges.append(ImportedEdge(
            p1=points[i], p2=points[(i + 1) % n],
            kind_hint=kind,
            road_width_m=road_width_m,
            wall_setback_m=wall_setback_m,
            relaxation=relaxation,
            ground_level_diff_m=ground_level_diff_m,
            label=(row.get("label") or "").strip(),
        ))

    return ImportedSitePlan(points=points, edges=edges, notes=notes)
