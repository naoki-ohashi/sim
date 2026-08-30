"""図面（DXF）の書き出し.

敷地図・道路・壁面後退線・建物外郭線・メッシュ・階数・日影測定線を、
それぞれ別レイヤに分けて出力します。JW-CADのDXF読込でそのまま開けます。

| レイヤ | 内容 |
|---|---|
| `MVCE-SITE` | 敷地境界線 |
| `MVCE-ROAD` | 前面道路（幅員ぶんの範囲） |
| `MVCE-SETBACK` | 壁面後退線 |
| `MVCE-OUTLINE` | 建物外郭線 |
| `MVCE-MESH` | メッシュの割り付け |
| `MVCE-FLOORS` | 各マスの階数（文字） |
| `MVCE-PLAN-n` | 各階の平面輪郭 |
| `MVCE-SHADOW-5M` / `MVCE-SHADOW-10M` | 日影の測定線 |
| `MVCE-ISOCHRONE-{時間}H` | 等時間日影線（`shadow.isochrone_hours` を指定したときのみ） |
| `MVCE-NORTH` | 真北記号 |
| `MVCE-SUMMARY` | 計算結果の要約（文字） |

JWWが読める形式（R12・LINE/TEXTのみ・mm）で書き出します。理由は
`dxf_pen.py` の説明を参照してください。
"""
from __future__ import annotations

import math

from ..geometry import Point, interior_normal, polygon_to_ring
from ..index.isochrone import site_isochrones
from ..solvers.optimizer import OptimizeResult
from ..regulations.shadow import measurement_points, regulation_boundary
from ..site import Site
from .dxf_pen import JWW_UNITS_PER_METER, JwwDrawing
from .dxf_r12 import R12Drawing

LAYERS = {
    "MVCE-SITE": 7, "MVCE-ROAD": 8, "MVCE-SETBACK": 3, "MVCE-OUTLINE": 5,
    "MVCE-MESH": 254, "MVCE-FLOORS": 2, "MVCE-SHADOW-5M": 1, "MVCE-SHADOW-10M": 30,
    "MVCE-NORTH": 1, "MVCE-SUMMARY": 7, "MVCE-RIDGE": 6,
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
    pen.line(origin, tip, "MVCE-NORTH", 1)
    # 矢じり
    for sign in (1, -1):
        angle = math.radians(150 * sign)
        ax = nx * math.cos(angle) - ny * math.sin(angle)
        ay = nx * math.sin(angle) + ny * math.cos(angle)
        pen.line(tip, (tip[0] + ax * size * 0.25, tip[1] + ay * size * 0.25),
                 "MVCE-NORTH", 1)
    pen.text("N", (tip[0] + nx * size * 0.15, tip[1] + ny * size * 0.15),
             size * 0.2, "MVCE-NORTH", 1)


def _add_ridge_line(pen: JwwDrawing, site: Site, area, roof_spec, span: float) -> None:
    """逆日影の屋根越し／棟状パターンの棟（稜線）を、外郭線を横切る線で描く。"""
    low_normal = site.north.vector_for_azimuth(roof_spec.low_azimuth_deg)
    ridge_dir = (low_normal[1], -low_normal[0])   # 低勾配側の90度：稜線の方向
    cx, cy = area.outline.centroid.coords[0]
    px = cx + roof_spec.ridge_offset_m * low_normal[0]
    py = cy + roof_spec.ridge_offset_m * low_normal[1]
    half = span
    p1 = (px - ridge_dir[0] * half, py - ridge_dir[1] * half)
    p2 = (px + ridge_dir[0] * half, py + ridge_dir[1] * half)
    pen.line(p1, p2, "MVCE-RIDGE", LAYERS["MVCE-RIDGE"])
    pen.text(f"棟 / {roof_spec.describe_ja()}", (px, py), span * 0.018,
             "MVCE-RIDGE", LAYERS["MVCE-RIDGE"])


#: 書き出しの実装。`r12` は外部ライブラリを使わない最小構成（JW-CAD向け）。
BACKENDS = {"ezdxf": JwwDrawing, "r12": R12Drawing}


def write_dxf(result: OptimizeResult, path: str, draw_mesh: bool = True,
              draw_floor_labels: bool = True,
              units_per_meter: float = JWW_UNITS_PER_METER,
              backend: str = "r12",
              isochrones: dict[float, list[tuple[list[Point], bool]]] | None = None) -> None:
    """計算結果をDXFに書き出す。

    `units_per_meter` は図面1単位が何mにあたるかの逆数です。既定の1000は
    「1m = 1000単位 = mmで作図」の意味で、JW-CADの標準です。mで作図している
    図面に合わせたい場合だけ 1 を指定してください。

    `backend` は書き出しの実装です。既定の `r12` は外部ライブラリを使わず、
    JW-CADが解釈できる範囲だけを組み立てます（`dxf_r12.py`）。`ezdxf` は
    ezdxf が書くR12で、他のCADとの互換性は高いぶんJW-CADには読みにくい
    要素（大文字でないテーブル名・ハンドル・余分なテーブル）が入ります。

    `isochrones` は等時間日影図を計算済みなら渡します（`isochrone.site_isochrones`
    の戻り値と同じ形）。省略すると必要な場合に内部で計算します。DXFと3D
    HTMLを両方書き出す場合、呼び出し側で1回だけ計算して両方に渡すと、
    計算時間の大きい等時間日影図の再計算を避けられます。
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
    pen.polyline(site.points, "MVCE-SITE", LAYERS["MVCE-SITE"])
    # 道路
    for edge in site.edges:
        if edge.is_road:
            pen.polyline(_road_polygon(site, edge), "MVCE-ROAD", LAYERS["MVCE-ROAD"])
            mid = edge.midpoint
            nx, ny = interior_normal(edge.p1, edge.p2)
            pen.text(
                f"W={edge.road_width_m:.1f}m",
                (mid[0] - nx * edge.road_width_m * 0.5,
                 mid[1] - ny * edge.road_width_m * 0.5),
                span * 0.02, "MVCE-ROAD", LAYERS["MVCE-ROAD"],
            )

    # 壁面後退線・建物外郭線・メッシュ
    if result.area is not None:
        if result.area.setback_ring and any(e.wall_setback_m > 0 for e in site.edges):
            pen.polyline(result.area.setback_ring, "MVCE-SETBACK", LAYERS["MVCE-SETBACK"])
        pen.polyline(polygon_to_ring(result.area.outline), "MVCE-OUTLINE",
                     LAYERS["MVCE-OUTLINE"])
        if draw_mesh:
            for cell in result.area.cells:
                pen.polyline(cell.corners, "MVCE-MESH", LAYERS["MVCE-MESH"])
        if draw_floor_labels and result.floors.size:
            cell_size = min(result.area.cell_size_x_m, result.area.cell_size_y_m)
            for cell, floors in zip(result.area.cells, result.floors):
                if floors > 0:
                    pen.text(str(int(floors)), cell.center, cell_size * 0.3,
                             "MVCE-FLOORS", LAYERS["MVCE-FLOORS"])

    # 各階の平面輪郭
    by_level: dict[int, list] = {}
    for block in result.blocks:
        level = int(round(block.z_bottom / site.floor_height_m))
        by_level.setdefault(level, []).append(block)
    for level, blocks in sorted(by_level.items()):
        layer = f"MVCE-PLAN-{level + 1}"
        color = (level % 7) + 1
        pen.add_layer(layer, color)
        for block in blocks:
            pen.polyline(polygon_to_ring(block.footprint), layer, color)

    # 日影の測定線
    if result.shadow_spec is not None:
        spec = result.shadow_spec
        pen.polyline(regulation_boundary(site, spec), "MVCE-SITE", 253)
        for distance, layer in ((5.0, "MVCE-SHADOW-5M"), (10.0, "MVCE-SHADOW-10M")):
            pen.polyline(measurement_points(site, spec, distance), layer, LAYERS[layer])

        # 等時間日影図（等時間日影線）。isochrone_hours が空なら何もしない。
        if spec.isochrone_hours and result.area is not None:
            iso = isochrones if isochrones is not None else site_isochrones(
                site, result.area, result.floors, spec, spec.isochrone_hours,
                interval_m=spec.isochrone_grid_interval_m, margin_m=spec.isochrone_margin_m,
            )
            iso_colors = (1, 2, 3, 4, 5, 6)
            for idx, level in enumerate(spec.isochrone_hours):
                layer = f"MVCE-ISOCHRONE-{level:g}H".replace(".", "_")
                color = iso_colors[idx % len(iso_colors)]
                label = f"{level:g}時間"
                for points, closed in iso.get(level, []):
                    pen.polyline(points, layer, color, close=closed)
                    if points:
                        pen.text(label, points[0], span * 0.02, layer, color)

    # 逆日影：屋根越し／棟状パターンの棟（稜線）
    if result.roof_spec is not None and result.area is not None:
        _add_ridge_line(pen, site, result.area, result.roof_spec, span)

    _add_north_symbol(pen, site, (max(xs) + span * 0.15, max(ys)), span * 0.18)

    # 要約
    text_height = span * 0.022
    for i, line in enumerate(result.summary_lines_ja()):
        pen.text(line, (min(xs), min(ys) - span * 0.12 - i * text_height * 1.6),
                 text_height, "MVCE-SUMMARY", LAYERS["MVCE-SUMMARY"])

    pen.save(path)
