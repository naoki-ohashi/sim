"""プロジェクト設定（YAML）の読み込み.

敷地の与え方は5通りあり、どれか1つを指定します。

    site.points     … 頂点座標を直接書く
    site.rectangle  … 間口×奥行の長方形
    site.dxf        … DXFの敷地図を読み込む
    site.json       … JSONの敷地図を読み込む（外部ツール連携用）
    site.csv        … CSVの敷地図を読み込む（外部ツール連携用）

例は examples/mvce_sample.yaml を参照してください。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .io.dxf_pen import JWW_UNITS_PER_METER
from .io.dxf_site import read_site_plan
from .io.site_csv import read_site_plan_csv
from .io.site_json import read_site_plan_json
from .north import NorthReference
from .solvers.optimizer import OptimizeOptions
from .regulations.shadow import ShadowRegulationSpec
from .site import Site
from .zoning import ZoningParams, validate_measurement_height


@dataclass
class OutputSettings:
    dxf_path: str | None = None
    html_path: str | None = None
    draw_mesh: bool = True
    draw_floor_labels: bool = True
    #: 図面1mを何単位で書くか。JW-CADはmmなので既定は1000。
    dxf_units_per_meter: float = JWW_UNITS_PER_METER
    #: 書き出しの実装。r12 = JW-CAD向けの最小構成 / ezdxf = 他CAD互換重視
    dxf_backend: str = "r12"


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
        # 用途地域の指定のない区域でだけ要る2つ。別表第三 五の項と
        # 別表第四 四の項が特定行政庁／条例の指定に委ねている部分。
        unspecified_road_slant_slope=data.get("unspecified_road_slant_slope"),
        unspecified_shadow_row=data.get("unspecified_shadow_row"),
        unspecified_adjacent_slant_slope=data.get("unspecified_adjacent_slant_slope"),
        adjacent_slant_2_5_designated=data.get("adjacent_slant_2_5_designated", False),
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
    elif "json" in data:
        js = data["json"]
        plan = read_site_plan_json(js["path"], units_per_meter=js.get("units_per_meter", 1.0))
        notes.extend(plan.notes)
        points = plan.points
        if edge_specs is None:
            edge_specs = plan.edge_specs(
                default_road_width_m=js.get("default_road_width_m", 6.0),
                wall_setback_m=data.get("wall_setback_m", 0.0),
            )
            notes.append("辺の種別はJSONの内容から読み取りました。")
    elif "csv" in data:
        csv_cfg = data["csv"]
        plan = read_site_plan_csv(
            csv_cfg["path"], units_per_meter=csv_cfg.get("units_per_meter", 1.0),
            encoding=csv_cfg.get("encoding", "utf-8-sig"),
        )
        notes.extend(plan.notes)
        points = plan.points
        if edge_specs is None:
            edge_specs = plan.edge_specs(
                default_road_width_m=csv_cfg.get("default_road_width_m", 6.0),
                wall_setback_m=data.get("wall_setback_m", 0.0),
            )
            notes.append("辺の種別はCSVの内容から読み取りました。")
    elif "rectangle" in data:
        rect = data["rectangle"]
        points = _rectangle_points(rect["width_m"], rect["depth_m"])
    elif "points" in data:
        points = [tuple(p) for p in data["points"]]
    else:
        raise ValueError(
            "敷地は points / rectangle / dxf / json / csv のいずれかで指定してください"
        )

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
        isochrone_hours=list(data.get("isochrone_hours", [])),
        isochrone_grid_interval_m=data.get("isochrone_grid_interval_m", 2.0),
        isochrone_margin_m=data.get("isochrone_margin_m"),
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
        sky_ratio_interval_m=data.get("sky_ratio_interval_m", 4.0),
        sky_ratio_n_azimuth=data.get("sky_ratio_n_azimuth", 72),
        envelope_family=data.get("envelope_family", "voxel"),
        roof_angle_span_deg=data.get("roof_angle_span_deg", 15.0),
        roof_angle_step_deg=data.get("roof_angle_step_deg", 7.5),
        roof_offset_steps=data.get("roof_offset_steps", 7),
        roof_pitch_candidates_deg=tuple(
            data.get("roof_pitch_candidates_deg", (20.0, 27.0, 35.0, 45.0))),
        roof_far_pitch_candidates_deg=tuple(
            data.get("roof_far_pitch_candidates_deg", (0.0, 20.0, 35.0))),
        roof_fixed_low_azimuth_deg=data.get("roof_fixed_low_azimuth_deg"),
    )


def load_project(path: str) -> Project:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    site, notes = _build_site(data["site"])
    shadow = _build_shadow(data.get("shadow"))
    if shadow is not None:
        # 用途地域が分かるここで、別表第四（は）欄に照らして測定面を検証する。
        validate_measurement_height(
            site.zoning.zone_type,
            shadow.measurement_height_m,
            site.zoning.unspecified_shadow_row,
        )
    return Project(
        site=site,
        options=_build_options(data.get("mesh")),
        shadow=shadow,
        output=OutputSettings(**(data.get("output") or {})),
        notes=notes,
    )
