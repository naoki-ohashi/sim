"""図面（DXF）の書き出し.

敷地図・道路・壁面後退線・建物外郭線・メッシュ・階数・日影測定線を、
それぞれ別レイヤに分けて出力します。JW-CADのDXF読込でそのまま開けます。

| レイヤ | 内容 |
|---|---|
| `MVE-SITE` | 敷地境界線 |
| `MVE-ROAD` | 前面道路（幅員ぶんの範囲） |
| `MVE-SETBACK` | 壁面後退線 |
| `MVE-OUTLINE` | 建物外郭線 |
| `MVE-MESH` | メッシュの割り付け |
| `MVE-FLOORS` | 各マスの階数（文字） |
| `MVE-PLAN-n` | 各階の平面輪郭 |
| `MVE-SHADOW-5M` / `MVE-SHADOW-10M` | 日影の測定線 |
| `MVE-NORTH` | 真北記号 |
| `MVE-SUMMARY` | 計算結果の要約（文字） |

JWWが読める形式（R12・LINE/TEXTのみ・mm）で書き出します。理由は
`dxf_pen.py` の説明を参照してください。
"""
from __future__ import annotations

import math

from ..geometry import Point, interior_normal, polygon_to_ring
from ..optimizer import OptimizeResult
from ..regulations.shadow import measurement_points, regulation_boundary
from ..site import Site
from .dxf_pen import JWW_UNITS_PER_METER, JwwDrawing
from .dxf_r12 import R12Drawing

LAYERS = {
    "MVE-SITE": 7, "MVE-ROAD": 8, "MVE-SETBACK": 3, "MVE-OUTLINE": 5,
    "MVE-MESH": 254, "MVE-FLOORS": 2, "MVE-SHADOW-5M": 1, "MVE-SHADOW-10M": 30,
    "MVE-NORTH": 1, "MVE-SUMMARY": 7,
}


def _road_polygon(site: Site, edge) -> list[Point]:
    """前面道路を、境界線から幅員ぶん外側に広げた帯として描く。"""
    nx, ny = interior_normal(edge.p1, edge.p2)
    w = edge.road_width_m
    return [
        edge.p1, edge.p2,
        (edge.p2[0] - w * nx, edge.p2[1] - w * ny),
        (edge.p1[0] - w * nx, edge.p1[1] - w * ny),
    ]


def _add_north_symbol(pen: JwwDrawing, site: Site, origin: Point, size: float) -> None:
    nx, ny = site.north.north_vector
    tip = (origin[0] + nx * size, origin[1] + ny * size)
    pen.line(origin, tip, "MVE-NORTH", 1)
    # 矢じり
    for sign in (1, -1):
        angle = math.radians(150 * sign)
        ax = nx * math.cos(angle) - ny * math.sin(angle)
        ay = nx * math.sin(angle) + ny * math.cos(angle)
        pen.line(tip, (tip[0] + ax * size * 0.25, tip[1] + ay * size * 0.25),
                 "MVE-NORTH", 1)
    pen.text("N", (tip[0] + nx * size * 0.15, tip[1] + ny * size * 0.15),
             size * 0.2, "MVE-NORTH", 1)


#: 書き出しの実装。`r12` は外部ライブラリを使わない最小構成（JW-CAD向け）。
BACKENDS = {"ezdxf": JwwDrawing, "r12": R12Drawing}


def write_dxf(result: OptimizeResult, path: str, draw_mesh: bool = True,
              draw_floor_labels: bool = True,
              units_per_meter: float = JWW_UNITS_PER_METER,
              backend: str = "r12") -> None:
    """計算結果をDXFに書き出す。

    `units_per_meter` は図面1単位が何mにあたるかの逆数です。既定の1000は
    「1m = 1000単位 = mmで作図」の意味で、JW-CADの標準です。mで作図している
    図面に合わせたい場合だけ 1 を指定してください。

    `backend` は書き出しの実装です。既定の `r12` は外部ライブラリを使わず、
    JW-CADが解釈できる範囲だけを組み立てます（`dxf_r12.py`）。`ezdxf` は
    ezdxf が書くR12で、他のCADとの互換性は高いぶんJW-CADには読みにくい
    要素（大文字でないテーブル名・ハンドル・余分なテーブル）が入ります。
    """
    if backend not in BACKENDS:
        raise ValueError(f"backend は {'/'.join(BACKENDS)} のいずれかにしてください")
    site = result.site
    pen = BACKENDS[backend](units_per_meter=units_per_meter)
    for name, color in LAYERS.items():
        pen.add_layer(name, color)

    xs = [p[0] for p in site.points]
    ys = [p[1] for p in site.points]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    span = max(width, height)

    # 敷地
    pen.polyline(site.points, "MVE-SITE", LAYERS["MVE-SITE"])
    # 道路
    for edge in site.edges:
        if edge.is_road:
            pen.polyline(_road_polygon(site, edge), "MVE-ROAD", LAYERS["MVE-ROAD"])
            mid = edge.midpoint
            nx, ny = interior_normal(edge.p1, edge.p2)
            pen.text(
                f"W={edge.road_width_m:.1f}m",
                (mid[0] - nx * edge.road_width_m * 0.5,
                 mid[1] - ny * edge.road_width_m * 0.5),
                span * 0.02, "MVE-ROAD", LAYERS["MVE-ROAD"],
            )

    # 壁面後退線・建物外郭線・メッシュ
    if result.area is not None:
        if result.area.setback_ring and any(e.wall_setback_m > 0 for e in site.edges):
            pen.polyline(result.area.setback_ring, "MVE-SETBACK", LAYERS["MVE-SETBACK"])
        pen.polyline(polygon_to_ring(result.area.outline), "MVE-OUTLINE",
                     LAYERS["MVE-OUTLINE"])
        if draw_mesh:
            for cell in result.area.cells:
                pen.polyline(cell.corners, "MVE-MESH", LAYERS["MVE-MESH"])
        if draw_floor_labels and result.floors.size:
            cell_size = min(result.area.cell_size_x_m, result.area.cell_size_y_m)
            for cell, floors in zip(result.area.cells, result.floors):
                if floors > 0:
                    pen.text(str(int(floors)), cell.center, cell_size * 0.3,
                             "MVE-FLOORS", LAYERS["MVE-FLOORS"])

    # 各階の平面輪郭
    by_level: dict[int, list] = {}
    for block in result.blocks:
        level = int(round(block.z_bottom / site.floor_height_m))
        by_level.setdefault(level, []).append(block)
    for level, blocks in sorted(by_level.items()):
        layer = f"MVE-PLAN-{level + 1}"
        color = (level % 7) + 1
        pen.add_layer(layer, color)
        for block in blocks:
            pen.polyline(polygon_to_ring(block.footprint), layer, color)

    # 日影の測定線
    if result.shadow_spec is not None:
        spec = result.shadow_spec
        pen.polyline(regulation_boundary(site, spec), "MVE-SITE", 253)
        for distance, layer in ((5.0, "MVE-SHADOW-5M"), (10.0, "MVE-SHADOW-10M")):
            pen.polyline(measurement_points(site, spec, distance), layer, LAYERS[layer])

    _add_north_symbol(pen, site, (max(xs) + span * 0.15, max(ys)), span * 0.18)

    # 要約
    text_height = span * 0.022
    for i, line in enumerate(result.summary_lines_ja()):
        pen.text(line, (min(xs), min(ys) - span * 0.12 - i * text_height * 1.6),
                 text_height, "MVE-SUMMARY", LAYERS["MVE-SUMMARY"])

    pen.save(path)
