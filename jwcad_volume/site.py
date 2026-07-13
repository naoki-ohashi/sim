"""Site boundary model."""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Point, polygon_area, polygon_signed_area
from .zoning import ZoningParams

BOUNDARY_KINDS = {"road", "adjacent", "north", "none"}


@dataclass
class Boundary:
    """One edge of the site polygon and its regulatory role.

    `p1`, `p2` are taken from the (CCW-ordered) site polygon; the edge runs
    p1 -> p2. `kind` selects which slant-line regulation treats this edge as
    its baseline:

    - "road": 道路斜線. `road_width_m` is the opposing road's width; the
      slant-line baseline is the road's *opposite* boundary line, i.e. this
      edge offset outward (away from the site) by `road_width_m`.
    - "adjacent": 隣地斜線, baseline is the edge itself.
    - "north": 北側斜線. Only meaningful for edges on the true-north side of
      the site, baseline is the edge itself. Only applies in zones present
      in zoning.NORTH_SLANT_ZONES.
    - "none": not a regulated boundary for slant-line purposes (e.g. an
      internal notch or a boundary type not modeled here).

    `setback_m` is the minimum horizontal distance every part of the
    building is set back from this edge, used for the slant-line setback
    relaxations (Art. 130-12 for roads, Art. 135-3/135-4 for adjacent/north).
    Leave at 0.0 for the conservative case of no relaxation.
    """

    p1: Point
    p2: Point
    kind: str = "none"
    road_width_m: float = 0.0
    setback_m: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in BOUNDARY_KINDS:
            raise ValueError(f"unknown boundary kind: {self.kind!r}; valid: {sorted(BOUNDARY_KINDS)}")
        if self.kind == "road" and self.road_width_m <= 0:
            raise ValueError("road boundaries require road_width_m > 0")
        if self.setback_m < 0:
            raise ValueError("setback_m must be >= 0")


@dataclass
class Site:
    """A site polygon with one Boundary per edge, plus zoning parameters.

    `points` must be given counter-clockwise (math convention); `edges[i]`
    must describe the edge from `points[i]` to `points[(i+1) % n]`.
    """

    points: list[Point]
    edges: list[Boundary]
    zoning: ZoningParams
    floor_height_m: float = 3.2  # assumed floor-to-floor height, for GFA estimates from volume

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("site polygon needs at least 3 vertices")
        if len(self.edges) != len(self.points):
            raise ValueError("edges must have exactly one entry per polygon edge")
        if polygon_signed_area(self.points) < 0:
            raise ValueError(
                "site polygon points must be counter-clockwise; reverse `points` "
                "and `edges` (and swap each edge's p1/p2) before constructing Site"
            )
        n = len(self.points)
        for i in range(n):
            p1, p2 = self.points[i], self.points[(i + 1) % n]
            edge = self.edges[i]
            if not (_same_point(edge.p1, p1) and _same_point(edge.p2, p2)):
                raise ValueError(
                    f"edges[{i}] endpoints {edge.p1, edge.p2} do not match "
                    f"points[{i}]->points[{(i + 1) % n}] = {p1, p2}"
                )

    @property
    def area_m2(self) -> float:
        return polygon_area(self.points)

    def max_building_area_m2(self) -> float:
        """建蔽率 (building coverage ratio) cap on footprint area."""
        return self.area_m2 * self.zoning.coverage_ratio

    def max_total_floor_area_m2(self) -> float:
        """容積率 (floor area ratio) cap on total floor area."""
        return self.area_m2 * self.zoning.far_ratio


def _same_point(a: Point, b: Point, tol: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
