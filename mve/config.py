"""プロジェクト設定（YAML）の読み込み.

敷地の与え方は3通りあり、どれか1つを指定します。

    site.points     … 頂点座標を直接書く
    site.rectangle  … 間口×奥行の長方形
    site.dxf        … DXFの敷地図を読み込む

例は examples/mve_sample.yaml を参照してください。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .io.dxf_pen import JWW_UNITS_PER_METER
from .io.dxf_site import read_site_plan
from .north import NorthReference
from .optimizer import OptimizeOptions
from .regulations.shadow import ShadowRegulationSpec
from .site import Site
from .zoning import ZoningParams


@dataclass
class OutputSettings:
    dxf_path: str | None = None
    html_path: str | None = None
    draw_mesh: bool = True
    draw_floor_labels: bool = True
    #: 図面1mを何単位で書くか。JW-CADはmmなので既定は1000。
    dxf_units_per_meter: float = JWW_UNITS_PER_METER


@dataclass
class Project:
    site: Site
    options: OptimizeOptions
    shadow: ShadowRegulationSpec | None
    output: OutputSettings
    notes: list[str] = field(default_factory=list)


def _build_zoning(data: dict) -> ZoningParams:
    return ZoningParams(
        zone_type=data["zone_type"],
        far_ratio=_ratio(data["far_ratio"]),
        coverage_ratio=_ratio(data["coverage_ratio"]),
        absolute_height_limit_m=data.get("absolute_height_limit_m"),
    )


def _ratio(value: float) -> float:
    """200 のように百分率で書かれていても比に直す。"""
    return value / 100.0 if value > 20 else float(value)


def _rectangle_points(width_m: float, depth_m: float) -> list[tuple[float, float]]:
    return [(0.0, 0.0), (width_m, 0.0), (width_m, depth_m), (0.0, depth_m)]


def _build_site(data: dict) -> tuple[Site, list[str]]:
    notes: list[str] = []
    zoning = _build_zoning(data["zoning"])
    north = NorthReference(north_angle_deg=data.get("north_angle_deg", 0.0))
    floor_height = data.get("floor_height_m", 3.2)
    edge_specs = data.get("edges")

    if "dxf" in data:
        dxf = data["dxf"]
        plan = read_site_plan(
            dxf["path"], layer=dxf.get("layer"),
            units_per_meter=dxf.get("units_per_meter", 1.0),
        )
        notes.extend(plan.notes)
        points = plan.points
        if edge_specs is None:
            edge_specs = plan.edge_specs(
                default_road_width_m=dxf.get("default_road_width_m", 6.0),
                wall_setback_m=data.get("wall_setback_m", 0.0),
            )
            notes.append("辺の種別はDXFのレイヤ名から推測しました。")
    elif "rectangle" in data:
        rect = data["rectangle"]
        points = _rectangle_points(rect["width_m"], rect["depth_m"])
    elif "points" in data:
        points = [tuple(p) for p in data["points"]]
    else:
        raise ValueError("敷地は points / rectangle / dxf のいずれかで指定してください")

    if edge_specs is None:
        raise ValueError("edges（辺ごとの境界種別）を指定してください")
    if len(edge_specs) != len(points):
        raise ValueError(
            f"edges の数({len(edge_specs)})が頂点の数({len(points)})と一致しません"
        )

    default_setback = data.get("wall_setback_m", 0.0)
    normalized = []
    for spec in edge_specs:
        spec = dict(spec)
        spec.setdefault("wall_setback_m", default_setback)
        normalized.append(spec)

    site = Site.from_rings(points, normalized, zoning, north=north,
                           floor_height_m=floor_height, name=data.get("name", ""))
    return site, notes


def _build_shadow(data: dict | None) -> ShadowRegulationSpec | None:
    if not data:
        return None
    return ShadowRegulationSpec(
        measurement_height_m=data["measurement_height_m"],
        line_5m_max_hours=data["line_5m_max_hours"],
        line_10m_max_hours=data["line_10m_max_hours"],
        latitude_deg=data.get("latitude_deg", 35.7),
        hokkaido=data.get("hokkaido", False),
        time_step_minutes=data.get("time_step_minutes", 10.0),
        sample_interval_m=data.get("sample_interval_m", 2.0),
        apply_deemed_boundary=data.get("apply_deemed_boundary", True),
    )


def _build_options(data: dict | None) -> OptimizeOptions:
    data = data or {}
    return OptimizeOptions(
        cell_size_x_m=data.get("cell_size_x_m", 3.0),
        cell_size_y_m=data.get("cell_size_y_m", 3.0),
        mesh_angle_deg=data.get("mesh_angle_deg", 0.0),
        coverage_threshold=data.get("coverage_threshold", 0.5),
        use_sky_ratio=data.get("use_sky_ratio", False),
        max_iterations=data.get("max_iterations", 4000),
    )


def load_project(path: str) -> Project:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    site, notes = _build_site(data["site"])
    return Project(
        site=site,
        options=_build_options(data.get("mesh")),
        shadow=_build_shadow(data.get("shadow")),
        output=OutputSettings(**(data.get("output") or {})),
        notes=notes,
    )
