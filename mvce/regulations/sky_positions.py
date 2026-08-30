"""天空率の算定位置（令135条の9・10・11、法56条7項各号）.

天空率の判定は「想定半球の中心をどこに置くか」で答えが変わります。位置は
政令が細かく定めていて、**規制ごとに基準線も間隔も違います**。

| 規制 | 基準線 | 中心の高さ | 間隔 |
|---|---|---|---|
| 道路（令135条の9） | 前面道路の反対側の境界線 | 路面の中心 | 幅員の**1/2**以内 |
| 隣地（令135条の10） | 隣地境界線から **16m**（勾配1.25）/ **12.4m**（2.5）外側 | 敷地の地盤面 | **8m**（1.25）/ **6.2m**（2.5）以内 |
| 北側（令135条の11） | 隣地境界線等から**真北方向**に **4m**（低層・田園）/ **8m**（中高層）外側 | 敷地の地盤面 | **1m**（低層・田園）/ **2m**（中高層）以内 |

基準線の距離は法56条7項各号、位置と間隔は令135条の9〜11 です。

    法56条7項
    二　（略）隣地境界線からの水平距離が、第一項第二号イ又はニに定める数値が
    一・二五とされている建築物にあつては十六メートル、（略）二・五と
    されている建築物にあつては十二・四メートルだけ外側の線上の政令で定める位置
    三　（略）隣地境界線から真北方向への水平距離が、第一種低層住居専用地域、
    第二種低層住居専用地域又は田園住居地域内の建築物にあつては四メートル、
    第一種中高層住居専用地域又は第二種中高層住居専用地域内の建築物に
    あつては八メートルだけ外側の線上の政令で定める位置

    令135条の9第1項
    一　当該建築物の敷地（略）の前面道路に面する部分の両端から最も近い
    当該前面道路の反対側の境界線上の位置
    二　前号の位置の間の境界線の延長が当該前面道路の幅員の二分の一を
    超えるときは、当該位置の間の境界線上に当該前面道路の幅員の二分の一
    以内の間隔で均等に配置した位置

## 隣地・北側の基準線は境界線の**上**ではありません

ここが従来の実装の最大の誤りでした。隣地は16m（または12.4m）、北側は
真北方向に4m（または8m）**外側**です。境界線上に置くと、計画建築物も
適合建築物も実際より大きく見え、Ps と Pr の差が実際と変わります。

## 間隔は規制ごとに違います

従来はすべて2m間隔でした。北側の低層住専は条文が**1m以内**なので、
2mでは粗すぎて危険側（測定点の間をすり抜ける）でした。

## 高さ

- 道路 … 前面道路の**路面の中心**の高さ。令135条の9第4項の高低差みなし
  （敷地の地盤面が路面中心より1m以上高いとき `(高低差−1)/2` だけ高い）を
  含みます
- 隣地・北側 … **敷地の地盤面**。令135条の10第4項・令135条の11第4項の
  高低差みなし（敷地が隣地より1m以上低いとき `(高低差−1)/2` だけ高い）を
  含みます

いずれも敷地の地盤面を Z=0 とした値です。MVCE は全体で Z=0 を地盤面と
しているので（`ground.py` の算定はまだ高さの判定に繋いでいません）、
ここも同じ約束にそろえています。

## 条文にあって未対応のもの

- **令135条の9第5項・令135条の10第5項・令135条の11第5項** … 特定行政庁が
  規則で高さを別に定めている場合。規則を入力する口がないので未対応です
- **令135条の6第2項・3項、令135条の7第2項・3項、令135条の8第2項・3項** …
  勾配が異なる地域等ごと／令132条・令134条2項の区域ごと／高低差区分区域
  ごとの分割。`zone_split` が用途地域のまたがりで止まるのと同じ理由で、
  MVCE はまだ区域ごとの分割ができません
- **北側の基準線が前面道路のとき** … 法56条7項3号は「隣地境界線から」と
  しか書いていませんが、法56条1項3号は「前面道路の反対側の境界線又は
  隣地境界線」から測ります。北側が前面道路の敷地で7項3号を動かすには
  反対側の境界線を起点にするしかないので、そう読んでいます。
  **条文が明記していない解釈です**（照合台帳に記録）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import Point, edge_direction, interior_normal
from ..site import Boundary, Site
from ..zoning import LOW_RISE_ZONES, MID_RISE_ZONES, adjacent_slant_params
from . import adjacent_slant, north_slant, road_slant

# 法56条7項2号: 隣地の基準線までの水平距離（勾配ごと）
ADJACENT_BASELINE_M: dict[float, float] = {1.25: 16.0, 2.5: 12.4}
# 令135条の10第1項2号: 隣地の測定点の間隔の上限（勾配ごと）
ADJACENT_INTERVAL_M: dict[float, float] = {1.25: 8.0, 2.5: 6.2}

# 法56条7項3号: 北側の基準線までの真北方向の水平距離（用途地域ごと）
NORTH_BASELINE_M: dict[str, float] = {
    **{z: 4.0 for z in LOW_RISE_ZONES},
    **{z: 8.0 for z in MID_RISE_ZONES},
}
# 令135条の11第1項2号: 北側の測定点の間隔の上限（用途地域ごと）
NORTH_INTERVAL_M: dict[str, float] = {
    **{z: 1.0 for z in LOW_RISE_ZONES},
    **{z: 2.0 for z in MID_RISE_ZONES},
}

_EPS = 1e-9


@dataclass(frozen=True)
class MeasurementPosition:
    """想定半球の中心1つ。"""

    point: Point       # 平面位置
    z_m: float         # 中心の高さ（敷地の地盤面を0とした値）
    kind: str          # "road" | "adjacent" | "north"
    edge_index: int

    @property
    def point3(self) -> tuple[float, float, float]:
        return (self.point[0], self.point[1], self.z_m)


def _cap(statutory_m: float, user_m: float | None) -> float:
    """条文の間隔と利用者の指定の**厳しい方**（＝小さい方）。

    粗くする方向の指定は受け付けません。条文が定めた間隔より粗くすると
    測定点の間をすり抜けて危険側になります。
    """
    if user_m is None or user_m <= 0:
        return statutory_m
    return min(statutory_m, user_m)


def _evenly_spaced(a: Point, b: Point, max_interval_m: float) -> list[Point]:
    """両端 a・b を含み、間隔が `max_interval_m` 以下になるよう均等配置する。

    条文は「前号の位置の間の…延長が…を超えるときは、当該位置の間の…上に
    …以内の間隔で均等に配置した位置」なので、
    **両端は常に置き**、超えたぶんだけ間を割ります。
    """
    span = math.dist(a, b)
    if span <= _EPS:
        return [a]
    if span <= max_interval_m + _EPS:
        return [a, b]
    n = math.ceil(span / max_interval_m - _EPS)   # 区間の数
    return [
        (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
        for k in range(n + 1)
    ]


def _offset_outward(edge: Boundary, distance_m: float) -> tuple[Point, Point]:
    """辺を外向き法線方向に `distance_m` ずらした線分の両端。"""
    nx, ny = interior_normal(edge.p1, edge.p2)
    return (
        (edge.p1[0] - distance_m * nx, edge.p1[1] - distance_m * ny),
        (edge.p2[0] - distance_m * nx, edge.p2[1] - distance_m * ny),
    )


def _offset_north(site: Site, edge: Boundary, distance_m: float) -> tuple[Point, Point]:
    """辺を**真北方向**に `distance_m` ずらした線分の両端。

    令135条の11第1項1号は「両端から**真北方向の**基準線上の位置」なので、
    垂線ではなく真北方向に送ります。基準線自体も「真北方向への水平距離が
    4m（8m）だけ外側の線」＝辺を真北に平行移動した線です。
    """
    nx, ny = site.north.north_vector
    return (
        (edge.p1[0] + distance_m * nx, edge.p1[1] + distance_m * ny),
        (edge.p2[0] + distance_m * nx, edge.p2[1] + distance_m * ny),
    )


# === 道路（令135条の9）================================================

def road_positions(site: Site,
                   max_interval_m: float | None = None) -> list[MeasurementPosition]:
    """令135条の9: 前面道路の反対側の境界線上、幅員の1/2以内の間隔。

    `max_interval_m` は利用者が**さらに細かく**したいときの上限です。
    条文の値より粗くはできません（`min` を取ります）。細かくするぶんには
    測定点が増えて判定が厳しくなるだけなので安全側です。
    """
    positions: list[MeasurementPosition] = []
    for i, edge in enumerate(site.edges):
        if not edge.is_road:
            continue
        # 1号: 敷地の前面道路に面する部分の両端から最も近い反対側境界線上の位置。
        # 直線の道路では辺の両端の垂線の足がそれに当たる。
        a, b = _offset_outward(edge, edge.road_width_m)
        # 令135条の9第1項: 路面の中心の高さ。第4項の高低差みなしを含む。
        z = edge.ground_level_diff_m + road_slant._level_relaxation(edge)
        interval = _cap(edge.road_width_m / 2.0, max_interval_m)
        for point in _evenly_spaced(a, b, interval):
            positions.append(MeasurementPosition(point, z, "road", i))
    return positions


# === 隣地（令135条の10）===============================================

def adjacent_baseline_distance_m(site: Site) -> float | None:
    """法56条7項2号の基準線までの水平距離。隣地斜線の適用が無ければ None。"""
    params = adjacent_slant_params(
        site.zoning.zone_type, site.zoning.far_ratio,
        site.zoning.unspecified_adjacent_slant_slope,
        site.zoning.adjacent_slant_2_5_designated,
    )
    if params is None:
        return None
    return ADJACENT_BASELINE_M[params[1]]


def adjacent_interval_m(site: Site) -> float | None:
    """令135条の10第1項2号の間隔の上限。"""
    params = adjacent_slant_params(
        site.zoning.zone_type, site.zoning.far_ratio,
        site.zoning.unspecified_adjacent_slant_slope,
        site.zoning.adjacent_slant_2_5_designated,
    )
    if params is None:
        return None
    return ADJACENT_INTERVAL_M[params[1]]


def adjacent_positions(site: Site,
                       max_interval_m: float | None = None) -> list[MeasurementPosition]:
    """令135条の10: 隣地境界線から16m（12.4m）外側の線上。"""
    baseline = adjacent_baseline_distance_m(site)
    if baseline is None:
        return []
    interval = _cap(adjacent_interval_m(site), max_interval_m)

    positions: list[MeasurementPosition] = []
    for i, edge in enumerate(site.edges):
        if edge.kind.value != "adjacent":
            continue
        a, b = _offset_outward(edge, baseline)
        # 令135条の10第1項: 敷地の地盤面の高さ。第4項の高低差みなしを含む。
        z = adjacent_slant._level_relaxation(edge)
        for point in _evenly_spaced(a, b, interval):
            positions.append(MeasurementPosition(point, z, "adjacent", i))
    return positions


# === 北側（令135条の11）===============================================

def north_baseline_distance_m(site: Site) -> float | None:
    """法56条7項3号の基準線までの真北方向の水平距離。"""
    return NORTH_BASELINE_M.get(site.zoning.zone_type)


def north_interval_m(site: Site) -> float | None:
    """令135条の11第1項2号の間隔の上限。"""
    return NORTH_INTERVAL_M.get(site.zoning.zone_type)


def north_positions(site: Site,
                    max_interval_m: float | None = None) -> list[MeasurementPosition]:
    """令135条の11: 真北方向に4m（8m）外側の線上、1m（2m）以内の間隔。

    北側が前面道路のときは、法56条1項3号が「前面道路の反対側の境界線又は
    隣地境界線」から測るので、反対側の境界線を起点にします
    （7項3号は「隣地境界線」としか書いていない。モジュール docstring 参照）。
    """
    baseline = north_baseline_distance_m(site)
    if baseline is None:
        return []
    interval = _cap(north_interval_m(site), max_interval_m)

    positions: list[MeasurementPosition] = []
    for i in north_slant.north_edges(site):
        edge = site.edges[i]
        distance = baseline + (edge.road_width_m if edge.is_road else 0.0)
        a, b = _offset_north(site, edge, distance)
        # 令135条の11第1項: 敷地の地盤面の高さ。第4項の高低差みなしを含む。
        z = north_slant._level_relaxation(edge)
        for point in _evenly_spaced(a, b, interval):
            positions.append(MeasurementPosition(point, z, "north", i))
    return positions


# === まとめ ===========================================================

def all_positions(site: Site,
                  max_interval_m: float | None = None) -> list[MeasurementPosition]:
    """道路・隣地・北側のすべての算定位置。

    北側を向いた**前面道路**の辺は、道路（令135条の9）と北側
    （令135条の11）の両方の位置を持ちます。どちらの制限も適用される
    ためで、重複ではありません。
    """
    return (road_positions(site, max_interval_m)
            + adjacent_positions(site, max_interval_m)
            + north_positions(site, max_interval_m))
