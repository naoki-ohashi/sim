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
"""
from __future__ import annotations

import math

import ezdxf

from ..geometry import Point, interior_normal, polygon_to_ring
from ..optimizer import OptimizeResult
from ..regulations.shadow import measurement_points, regulation_boundary
from ..site import Site

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


def _add_north_symbol(msp, site: Site, origin: Point, size: float) -> None:
    nx, ny = site.north.north_vector
    tip = (origin[0] + nx * size, origin[1] + ny * size)
    msp.add_line(origin, tip, dxfattribs={"layer": "MVE-NORTH", "color": 1})
    # 矢じり
    for sign in (1, -1):
        angle = math.radians(150 * sign)
        ax = nx * math.cos(angle) - ny * math.sin(angle)
        ay = nx * math.sin(angle) + ny * math.cos(angle)
        msp.add_line(tip, (tip[0] + ax * size * 0.25, tip[1] + ay * size * 0.25),
                     dxfattribs={"layer": "MVE-NORTH", "color": 1})
    msp.add_text("N", height=size * 0.2, dxfattribs={"layer": "MVE-NORTH", "color": 1}
                 ).set_placement((tip[0] + nx * size * 0.15, tip[1] + ny * size * 0.15))


def write_dxf(result: OptimizeResult, path: str, draw_mesh: bool = True,
              draw_floor_labels: bool = True) -> None:
    site = result.site
    doc = ezdxf.new("R2010", setup=False)
    for name in LAYERS:
        doc.layers.add(name)
    msp = doc.modelspace()

    xs = [p[0] for p in site.points]
    ys = [p[1] for p in site.points]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    span = max(width, height)

    # 敷地
    msp.add_lwpolyline(site.points, close=True,
                       dxfattribs={"layer": "MVE-SITE", "color": LAYERS["MVE-SITE"]})
    # 道路
    for edge in site.edges:
        if edge.is_road:
            msp.add_lwpolyline(_road_polygon(site, edge), close=True,
                               dxfattribs={"layer": "MVE-ROAD", "color": LAYERS["MVE-ROAD"]})
            mid = edge.midpoint
            nx, ny = interior_normal(edge.p1, edge.p2)
            msp.add_text(
                f"W={edge.road_width_m:.1f}m", height=span * 0.02,
                dxfattribs={"layer": "MVE-ROAD", "color": LAYERS["MVE-ROAD"]},
            ).set_placement((mid[0] - nx * edge.road_width_m * 0.5,
                             mid[1] - ny * edge.road_width_m * 0.5))

    # 壁面後退線・建物外郭線・メッシュ
    if result.area is not None:
        if result.area.setback_ring and any(e.wall_setback_m > 0 for e in site.edges):
            msp.add_lwpolyline(result.area.setback_ring, close=True,
                               dxfattribs={"layer": "MVE-SETBACK",
                                           "color": LAYERS["MVE-SETBACK"]})
        msp.add_lwpolyline(polygon_to_ring(result.area.outline), close=True,
                           dxfattribs={"layer": "MVE-OUTLINE", "color": LAYERS["MVE-OUTLINE"]})
        if draw_mesh:
            for cell in result.area.cells:
                msp.add_lwpolyline(cell.corners, close=True,
                                   dxfattribs={"layer": "MVE-MESH", "color": LAYERS["MVE-MESH"]})
        if draw_floor_labels and result.floors.size:
            cell_size = min(result.area.cell_size_x_m, result.area.cell_size_y_m)
            for cell, floors in zip(result.area.cells, result.floors):
                if floors > 0:
                    msp.add_text(
                        str(int(floors)), height=cell_size * 0.3,
                        dxfattribs={"layer": "MVE-FLOORS", "color": LAYERS["MVE-FLOORS"]},
                    ).set_placement(cell.center)

    # 各階の平面輪郭
    by_level: dict[int, list] = {}
    for block in result.blocks:
        level = int(round(block.z_bottom / site.floor_height_m))
        by_level.setdefault(level, []).append(block)
    for level, blocks in sorted(by_level.items()):
        layer = f"MVE-PLAN-{level + 1}"
        if layer not in doc.layers:
            doc.layers.add(layer)
        for block in blocks:
            msp.add_lwpolyline(polygon_to_ring(block.footprint), close=True,
                               dxfattribs={"layer": layer, "color": (level % 7) + 1})

    # 日影の測定線
    if result.shadow_spec is not None:
        spec = result.shadow_spec
        msp.add_lwpolyline(regulation_boundary(site, spec), close=True,
                           dxfattribs={"layer": "MVE-SITE", "color": 253})
        for distance, layer in ((5.0, "MVE-SHADOW-5M"), (10.0, "MVE-SHADOW-10M")):
            pts = measurement_points(site, spec, distance)
            msp.add_lwpolyline(pts, close=True,
                               dxfattribs={"layer": layer, "color": LAYERS[layer]})

    _add_north_symbol(msp, site, (max(xs) + span * 0.15, max(ys)), span * 0.18)

    # 要約
    text_height = span * 0.022
    for i, line in enumerate(result.summary_lines_ja()):
        msp.add_text(line, height=text_height,
                     dxfattribs={"layer": "MVE-SUMMARY", "color": LAYERS["MVE-SUMMARY"]}
                     ).set_placement((min(xs), min(ys) - span * 0.12 - i * text_height * 1.6))

    doc.saveas(path)
