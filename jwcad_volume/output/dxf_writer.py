"""DXF export of a computed envelope: plan (stepped footprint contours) and
a section cut, plus a text summary. This is the recommended way to bring
results into JW-CAD/JWW -- DXF import ([ファイル]-[開く] or [図面編集]-
[DXF読込] depending on version) is a standard, well-supported JWW feature,
unlike the native 外部変形 exchange format (see gaihen_text.py), whose exact
byte-level protocol this project has not been able to verify against a real
JWW installation.

JWW only reads old-style DXF, so the drawing is written through
``mvce.io.dxf_pen.JwwDrawing`` (R12, LINE/TEXT only, millimetres, Shift-JIS).
Writing R2010 with LWPOLYLINE in metres -- as this module used to -- imports
without an error but leaves the JWW drawing empty. See ``dxf_pen.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString

from mvce.io.dxf_pen import JWW_UNITS_PER_METER, JwwDrawing

from ..envelope import EnvelopeResult
from ..massing import Block
from .isometric import isometric_segments

PLAN_LAYER_COLORS = [1, 2, 3, 4, 5, 6, 7, 8, 30, 40]  # cycles through AutoCAD color indices


def _footprint_ring(block: Block) -> list[tuple[float, float]]:
    return list(block.footprint.exterior.coords)


def _add_plan(pen: JwwDrawing, result: EnvelopeResult) -> None:
    pen.polyline(result.site.points, "SITE", 250)
    for i, block in enumerate(result.blocks):
        color = PLAN_LAYER_COLORS[i % len(PLAN_LAYER_COLORS)]
        pen.polyline(_footprint_ring(block), "ENVELOPE-PLAN", color)
        label_point = block.footprint.representative_point()
        pen.text(
            f"GL+{block.z_bottom:.2f}~{block.z_top:.2f}m",
            (label_point.x, label_point.y), 0.5, "ENVELOPE-PLAN-TEXT", color,
        )


def _section_cut_line(result: EnvelopeResult, axis: str, position: float | None) -> LineString:
    minx, miny, maxx, maxy = _site_bounds(result)
    margin = max(maxx - minx, maxy - miny) * 0.1 + 1.0
    if axis == "y":
        y = position if position is not None else (miny + maxy) / 2
        return LineString([(minx - margin, y), (maxx + margin, y)])
    x = position if position is not None else (minx + maxx) / 2
    return LineString([(x, miny - margin), (x, maxy + margin)])


def _site_bounds(result: EnvelopeResult) -> tuple[float, float, float, float]:
    xs = [p[0] for p in result.site.points]
    ys = [p[1] for p in result.site.points]
    return min(xs), min(ys), max(xs), max(ys)


def _add_section(pen: JwwDrawing, result: EnvelopeResult, axis: str, position: float | None, offset: tuple[float, float]) -> None:
    cut = _section_cut_line(result, axis, position)
    ox, oy = offset
    ground_u = [cut.project(p) for p in [cut.interpolate(0), cut.interpolate(cut.length)]]
    pen.line((ox + ground_u[0], oy), (ox + ground_u[1], oy), "SECTION-GL", 8)

    for i, block in enumerate(result.blocks):
        inter = block.footprint.intersection(cut)
        if inter.is_empty:
            continue
        segments = list(inter.geoms) if inter.geom_type.startswith("Multi") else [inter]
        color = PLAN_LAYER_COLORS[i % len(PLAN_LAYER_COLORS)]
        for seg in segments:
            if seg.length < 1e-9:
                continue
            u0 = cut.project(seg.interpolate(0))
            u1 = cut.project(seg.interpolate(seg.length))
            u0, u1 = sorted((u0, u1))
            rect = [
                (ox + u0, oy + block.z_bottom),
                (ox + u1, oy + block.z_bottom),
                (ox + u1, oy + block.z_top),
                (ox + u0, oy + block.z_top),
            ]
            pen.polyline(rect, "ENVELOPE-SECTION", color)


def _add_summary_text(pen: JwwDrawing, result: EnvelopeResult, offset: tuple[float, float]) -> None:
    ox, oy = offset
    for i, line in enumerate(result.summary_lines()):
        pen.text(line, (ox, oy - i * 0.9), 0.6, "SUMMARY", 7)


ISO_LAYER_BY_KIND = {
    "site": ("ISO-SITE", 8),
    "outline": ("ISO-OUTLINE", 2),
    "vertical": ("ISO-VERTICAL", 3),
}


def _add_isometric(
    pen: JwwDrawing,
    result: EnvelopeResult,
    azimuth_deg: float,
    elevation_deg: float,
    offset: tuple[float, float],
) -> None:
    segments = isometric_segments(
        result, azimuth_deg=azimuth_deg, elevation_deg=elevation_deg, origin=offset
    )
    for p1, p2, kind in segments:
        layer, color = ISO_LAYER_BY_KIND.get(kind, ("ISO-OUTLINE", 2))
        pen.line(p1, p2, layer, color)


def write_envelope_dxf(
    result: EnvelopeResult,
    path: str,
    section_axis: str = "y",
    section_position: float | None = None,
    isometric_azimuth_deg: float = 225.0,
    isometric_elevation_deg: float = 30.0,
    units_per_meter: float = JWW_UNITS_PER_METER,
) -> None:
    if section_axis not in ("x", "y"):
        raise ValueError("section_axis must be 'x' or 'y'")
    pen = JwwDrawing(units_per_meter=units_per_meter)
    for name in (
        "SITE", "ENVELOPE-PLAN", "ENVELOPE-PLAN-TEXT", "SECTION-GL", "ENVELOPE-SECTION", "SUMMARY",
        "ISO-SITE", "ISO-OUTLINE", "ISO-VERTICAL",
    ):
        pen.add_layer(name)

    minx, miny, maxx, maxy = _site_bounds(result)
    width, height = maxx - minx, maxy - miny
    _add_plan(pen, result)

    section_offset = (maxx + width * 0.2 + 5.0, miny)
    _add_section(pen, result, section_axis, section_position, section_offset)

    summary_offset = (minx, miny - height * 0.15 - 5.0)
    _add_summary_text(pen, result, summary_offset)

    # アイソメ図は平面図の上側に配置（断面図・サマリーと重ならない位置）
    iso_offset = (minx, maxy + height * 0.2 + 5.0)
    _add_isometric(pen, result, isometric_azimuth_deg, isometric_elevation_deg, iso_offset)

    pen.save(path)
