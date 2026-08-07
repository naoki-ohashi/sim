"""DXF export of a computed envelope: plan (stepped footprint contours) and
a section cut, plus a text summary. This is the recommended way to bring
results into JW-CAD/JWW -- DXF import ([ファイル]-[開く] or [図面編集]-
[DXF読込] depending on version) is a standard, well-supported JWW feature,
unlike the native 外部変形 exchange format (see gaihen_text.py), whose exact
byte-level protocol this project has not been able to verify against a real
JWW installation.
"""
from __future__ import annotations

from dataclasses import dataclass

import ezdxf
from shapely.geometry import LineString

from ..envelope import EnvelopeResult
from ..massing import Block
from .isometric import isometric_segments

PLAN_LAYER_COLORS = [1, 2, 3, 4, 5, 6, 7, 8, 30, 40]  # cycles through AutoCAD color indices


def _footprint_ring(block: Block) -> list[tuple[float, float]]:
    return list(block.footprint.exterior.coords)


def _add_plan(msp, result: EnvelopeResult) -> None:
    msp.add_lwpolyline(
        result.site.points, format="xy", close=True, dxfattribs={"layer": "SITE", "color": 250}
    )
    for i, block in enumerate(result.blocks):
        color = PLAN_LAYER_COLORS[i % len(PLAN_LAYER_COLORS)]
        msp.add_lwpolyline(
            _footprint_ring(block),
            format="xy",
            close=True,
            dxfattribs={"layer": "ENVELOPE-PLAN", "color": color},
        )
        label_point = block.footprint.representative_point()
        msp.add_text(
            f"GL+{block.z_bottom:.2f}~{block.z_top:.2f}m",
            height=0.5,
            dxfattribs={"layer": "ENVELOPE-PLAN-TEXT", "color": color},
        ).set_placement((label_point.x, label_point.y))


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


def _add_section(msp, result: EnvelopeResult, axis: str, position: float | None, offset: tuple[float, float]) -> None:
    cut = _section_cut_line(result, axis, position)
    ox, oy = offset
    ground_u = [cut.project(p) for p in [cut.interpolate(0), cut.interpolate(cut.length)]]
    msp.add_line((ox + ground_u[0], oy), (ox + ground_u[1], oy), dxfattribs={"layer": "SECTION-GL", "color": 8})

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
            msp.add_lwpolyline(rect, format="xy", close=True, dxfattribs={"layer": "ENVELOPE-SECTION", "color": color})


def _add_summary_text(msp, result: EnvelopeResult, offset: tuple[float, float]) -> None:
    ox, oy = offset
    for i, line in enumerate(result.summary_lines()):
        msp.add_text(line, height=0.6, dxfattribs={"layer": "SUMMARY", "color": 7}).set_placement(
            (ox, oy - i * 0.9)
        )


ISO_LAYER_BY_KIND = {
    "site": ("ISO-SITE", 8),
    "outline": ("ISO-OUTLINE", 2),
    "vertical": ("ISO-VERTICAL", 3),
}


def _add_isometric(
    msp,
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
        msp.add_line(p1, p2, dxfattribs={"layer": layer, "color": color})


def write_envelope_dxf(
    result: EnvelopeResult,
    path: str,
    section_axis: str = "y",
    section_position: float | None = None,
    isometric_azimuth_deg: float = 225.0,
    isometric_elevation_deg: float = 30.0,
) -> None:
    if section_axis not in ("x", "y"):
        raise ValueError("section_axis must be 'x' or 'y'")
    doc = ezdxf.new("R2010", setup=False)
    for name in (
        "SITE", "ENVELOPE-PLAN", "ENVELOPE-PLAN-TEXT", "SECTION-GL", "ENVELOPE-SECTION", "SUMMARY",
        "ISO-SITE", "ISO-OUTLINE", "ISO-VERTICAL",
    ):
        doc.layers.add(name)
    msp = doc.modelspace()

    minx, miny, maxx, maxy = _site_bounds(result)
    width, height = maxx - minx, maxy - miny
    _add_plan(msp, result)

    section_offset = (maxx + width * 0.2 + 5.0, miny)
    _add_section(msp, result, section_axis, section_position, section_offset)

    summary_offset = (minx, miny - height * 0.15 - 5.0)
    _add_summary_text(msp, result, summary_offset)

    # アイソメ図は平面図の上側に配置（断面図・サマリーと重ならない位置）
    iso_offset = (minx, maxy + height * 0.2 + 5.0)
    _add_isometric(msp, result, isometric_azimuth_deg, isometric_elevation_deg, iso_offset)

    doc.saveas(path)
