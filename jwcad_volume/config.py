"""Load a project (site + zoning + envelope/shadow search settings) from a
YAML config file. See examples/sample_site.yaml for the expected shape."""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from .regulations.shadow import ShadowRegulationParams
from .site import Boundary, Site
from .zoning import ZoningParams


@dataclass
class OutputSettings:
    dxf_path: str | None = None
    gaihen_text_path: str | None = None
    section_axis: str = "y"
    section_position: float | None = None


@dataclass
class EnvelopeSettings:
    # See envelope.compute_max_envelope for the speed/accuracy tradeoff these
    # control; the defaults here match its "quick look" defaults.
    n_layers: int = 10
    interval_m: float = 4.0
    n_azimuth: int = 45
    measurement_height: float = 0.0
    split_fractions: tuple[float, ...] = (0.3, 0.5, 0.7)
    search_iterations: int = 12
    use_sky_ratio: bool = True


@dataclass
class Project:
    site: Site
    envelope: EnvelopeSettings
    shadow: ShadowRegulationParams | None
    output: OutputSettings


def _build_site(data: dict) -> Site:
    points = [tuple(p) for p in data["points"]]
    edges = [
        Boundary(
            p1=points[i],
            p2=points[(i + 1) % len(points)],
            kind=e.get("kind", "none"),
            road_width_m=e.get("road_width_m", 0.0),
            setback_m=e.get("setback_m", 0.0),
        )
        for i, e in enumerate(data["edges"])
    ]
    z = data["zoning"]
    zoning = ZoningParams(
        zone_type=z["zone_type"],
        far_ratio=z["far_ratio"],
        coverage_ratio=z["coverage_ratio"],
        absolute_height_limit_m=z.get("absolute_height_limit_m"),
    )
    return Site(points=points, edges=edges, zoning=zoning, floor_height_m=data.get("floor_height_m", 3.2))


def _build_envelope_settings(data: dict | None) -> EnvelopeSettings:
    data = data or {}
    kwargs = dict(data)
    if "split_fractions" in kwargs:
        kwargs["split_fractions"] = tuple(kwargs["split_fractions"])
    return EnvelopeSettings(**kwargs)


def _build_shadow_params(data: dict | None) -> ShadowRegulationParams | None:
    if data is None:
        return None
    return ShadowRegulationParams(**data)


def _build_output_settings(data: dict | None) -> OutputSettings:
    return OutputSettings(**(data or {}))


def load_project(path: str) -> Project:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Project(
        site=_build_site(data["site"]),
        envelope=_build_envelope_settings(data.get("envelope")),
        shadow=_build_shadow_params(data.get("shadow")),
        output=_build_output_settings(data.get("output")),
    )
