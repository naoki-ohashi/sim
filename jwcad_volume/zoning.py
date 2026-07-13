"""用途地域 (zoning) reference data.

These tables encode the *structure* of Building Standards Act Article 56 /
Enforcement Order Art. 130-11, 135-3, 135-4 (which zone groups get which
slant-line slope, which zones get a north-side slant line, etc).

The exact breakpoints for 容積率 (FAR) vs. 適用距離 (applicable distance) for
the road slant line (別表第三) are reproduced here as defaults but are
legally load-bearing numbers that change with FAR tiers not all listed
below (esp. very high-FAR central commercial zones). Treat ROAD_SLANT_TABLE
as a starting point and override it in the project config against the
current law text / local ordinance for anything unusual.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RESIDENTIAL_ZONES = {
    "1low",  # 第一種低層住居専用地域
    "2low",  # 第二種低層住居専用地域
    "denen",  # 田園住居地域
    "1mid",  # 第一種中高層住居専用地域
    "2mid",  # 第二種中高層住居専用地域
    "1res",  # 第一種住居地域
    "2res",  # 第二種住居地域
    "quasi_res",  # 準住居地域
}
COMMERCIAL_ZONES = {"neighbor_commercial", "commercial"}
INDUSTRIAL_ZONES = {"quasi_industrial", "industrial", "industrial_exclusive"}
UNSPECIFIED_ZONE = {"unspecified"}

ALL_ZONES = RESIDENTIAL_ZONES | COMMERCIAL_ZONES | INDUSTRIAL_ZONES | UNSPECIFIED_ZONE

# 北側斜線 (north-side slant line): (start height above ground, slope). Only
# these zone types have it (Building Standards Act Art. 56-1-3).
NORTH_SLANT_ZONES: dict[str, tuple[float, float]] = {
    "1low": (5.0, 1.25),
    "2low": (5.0, 1.25),
    "denen": (5.0, 1.25),
    "1mid": (10.0, 1.25),
    "2mid": (10.0, 1.25),
}

# 隣地斜線 (adjacent-site slant line): (start height, slope) by zone group.
# Residential-group zones: start 20m, slope 1.25 (Art. 56-1-2, though 1low/2low/
# denen normally never reach it because of the absolute height limit).
# Commercial/industrial/unspecified group: start 31m, slope 2.5.
ADJACENT_SLANT_BY_GROUP: dict[str, tuple[float, float]] = {
    "residential": (20.0, 1.25),
    "other": (31.0, 2.5),
}


def zone_group(zone_type: str) -> str:
    if zone_type in RESIDENTIAL_ZONES:
        return "residential"
    if zone_type in COMMERCIAL_ZONES or zone_type in INDUSTRIAL_ZONES or zone_type in UNSPECIFIED_ZONE:
        return "other"
    raise ValueError(f"unknown zone_type: {zone_type}")


def road_slant_group(zone_type: str) -> str:
    """Road slant-line slope group: 'residential' (1.25) or 'other' (1.5)."""
    if zone_type in RESIDENTIAL_ZONES:
        return "residential"
    if zone_type in COMMERCIAL_ZONES or zone_type in INDUSTRIAL_ZONES or zone_type in UNSPECIFIED_ZONE:
        return "other"
    raise ValueError(f"unknown zone_type: {zone_type}")


@dataclass(frozen=True)
class FarTier:
    far_upper: float | None  # upper bound of 容積率 (as ratio, e.g. 2.0 = 200%); None = no upper bound
    applicable_distance_m: float
    slope: float


# Building Standards Act 別表第三 (い)(ろ)(は), simplified defaults.
ROAD_SLANT_TABLE: dict[str, list[FarTier]] = {
    "residential": [
        FarTier(2.0, 20.0, 1.25),
        FarTier(3.0, 25.0, 1.25),
        FarTier(4.0, 30.0, 1.25),
        FarTier(None, 35.0, 1.25),
    ],
    "other": [
        FarTier(4.0, 20.0, 1.5),
        FarTier(6.0, 25.0, 1.5),
        FarTier(8.0, 30.0, 1.5),
        FarTier(10.0, 35.0, 1.5),
        FarTier(11.0, 40.0, 1.5),
        FarTier(None, 45.0, 1.5),
    ],
}


def road_slant_params(zone_type: str, far_ratio: float) -> FarTier:
    group = road_slant_group(zone_type)
    for tier in ROAD_SLANT_TABLE[group]:
        if tier.far_upper is None or far_ratio <= tier.far_upper:
            return tier
    raise AssertionError("unreachable: last tier has far_upper=None")


@dataclass
class ZoningParams:
    zone_type: str
    far_ratio: float  # 容積率 as a ratio, e.g. 2.0 for 200%
    coverage_ratio: float  # 建蔽率 as a ratio, e.g. 0.6 for 60%
    absolute_height_limit_m: float | None = None  # 絶対高さ制限 (10 or 12m districts)

    def __post_init__(self) -> None:
        if self.zone_type not in ALL_ZONES:
            raise ValueError(f"unknown zone_type: {self.zone_type!r}; valid: {sorted(ALL_ZONES)}")
        if self.far_ratio <= 0:
            raise ValueError("far_ratio must be positive")
        if not (0 < self.coverage_ratio <= 1.0):
            raise ValueError("coverage_ratio must be in (0, 1]")
