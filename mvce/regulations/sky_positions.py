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
- **令135条の6第2項、令135条の7第2項・3項、令135条の8第2項・3項** …
  勾配が異なる地域等ごと／高低差区分区域ごとの分割。`zone_split` が用途
  地域のまたがりで止まるのと同じ理由で、MVCE はまだできません。
  **令135条の6第3項・令135条の9第3項（前面道路が2以上のときの令132条の
  区域ごと）は 2026-08-31 に実装しました**（令134条2項の区域は除く）
- **北側の基準線が前面道路のとき** … 法56条7項3号は「隣地境界線から」と
  しか書いていませんが、法56条1項3号は「前面道路の反対側の境界線又は
  隣地境界線」から測ります。北側が前面道路の敷地で7項3号を動かすには
  反対側の境界線を起点にするしかないので、そう読んでいます。
  **条文が明記していない解釈です**（照合台帳に記録）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import Point, interior_normal
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
    #: 令132条の区域の番号（前面道路が2以上のときだけ。それ以外は None）
    region_index: int | None = None

    @property
    def point3(self) -> tuple[float, float, float]:
        return (self.point[0], self.point[1], self.z_m)

    @property
    def group_key(self) -> str:
        """この位置を比べる相手（適合建築物・適用範囲）の識別子。

        令135条の6第3項・令135条の9第3項により、前面道路が2以上ある敷地では
        **区域ごと**に適合建築物・算定位置・計画建築物を切り分けて比べます。
        道路の測定点だけが区域を持ちます。
        """
        if self.kind == "road" and self.region_index is not None:
            return f"road#{self.region_index}"
        return self.kind


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
                   max_interval_m: float | None = None,
                   regions: list | None = None) -> list[MeasurementPosition]:
    """令135条の9: 前面道路の反対側の境界線上、幅員の1/2以内の間隔。

    `max_interval_m` は利用者が**さらに細かく**したいときの上限です。
    条文の値より粗くはできません（`min` を取ります）。細かくするぶんには
    測定点が増えて判定が厳しくなるだけなので安全側です。

    ## 前面道路が2以上あるとき（第3項）

    第3項は1項1号の「敷地（道路高さ制限が適用される範囲内の部分に限る。）」を
    「…の第百三十二条又は第百三十四条第二項に規定する区域**ごと**」と読み替え
    ます。つまり**区域ごとに**、その区域が前面道路に面している部分の両端を
    取り、そこから最も近い反対側の境界線上に位置を置きます。

    区域は `road_regions.sky_regions()` で作ります（`regions` に渡せば
    作り直しません）。令134条2項を選んだ敷地はそこで止まります。区域が持つ前面道路は令132条2項の「これらの前面
    道路のみを前面道路とし」・3項の「その接する前面道路のみ」に従うので、
    区域に入っていない道路にはその区域の位置を作りません。

    ## 間隔に使う幅員は**実幅員**です

    条文は「当該前面道路の幅員の二分の一」としか書いていません。区域内では
    幅員が読み替えられていますが、みなし幅員（＝実幅員以上）で割ると間隔が
    **粗く**なり、測定点の間をすり抜ける危険があります。実幅員で割れば
    間隔は同じか細かくなるので、そちらを採ります（`min` と同じ考え方）。
    """
    from .road_regions import applicable_distance_band, region_frontage, sky_regions

    if regions is None:
        regions = sky_regions(site)

    positions: list[MeasurementPosition] = []
    if not regions:
        for i, edge in enumerate(site.edges):
            if not edge.is_road:
                continue
            # 1号: 敷地の前面道路に面する部分の両端から最も近い反対側境界線上の
            # 位置。直線の道路では辺の両端の垂線の足がそれに当たる。
            a, b = _offset_outward(edge, edge.road_width_m)
            positions.extend(_road_positions_between(site, edge, i, a, b,
                                                     max_interval_m, None))
        return positions

    for k, region in enumerate(regions):
        for i in region.road_indices:
            edge = site.edges[i]
            band = applicable_distance_band(site, i, region.deemed_width_m)
            if band is None:
                # 適用距離がこの区域のみなし幅員に届かない。道路高さ制限が
                # かかる部分が無いので、算定位置も無い。
                continue
            span = region_frontage(site, region, i, within=band)
            if span is None:
                continue
            a, b = (_offset_outward_point(edge, p, edge.road_width_m) for p in span)
            positions.extend(_road_positions_between(site, edge, i, a, b,
                                                     max_interval_m, k))
    return positions


def _offset_outward_point(edge: Boundary, point: Point, distance_m: float) -> Point:
    """点を辺の外向き法線方向に `distance_m` ずらす。"""
    nx, ny = interior_normal(edge.p1, edge.p2)
    return (point[0] - distance_m * nx, point[1] - distance_m * ny)


def _road_positions_between(site: Site, edge: Boundary, edge_index: int,
                            a: Point, b: Point, max_interval_m: float | None,
                            region_index: int | None) -> list[MeasurementPosition]:
    # 令135条の9第1項: 路面の中心の高さ。第4項の高低差みなしを含む。
    z = edge.ground_level_diff_m + road_slant._level_relaxation(edge)
    interval = _cap(edge.road_width_m / 2.0, max_interval_m)
    return [
        MeasurementPosition(point, z, "road", edge_index, region_index)
        for point in _evenly_spaced(a, b, interval)
    ]


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
    """法56条7項3号の基準線までの真北方向の水平距離。

    法56条1項3号の括弧書きは「以下この号**及び第七項第三号**において同じ」
    なので、中高層住専で日影規制の指定があれば北側の算定位置もありません。
    """
    if not north_slant.applies(site):
        return None
    return NORTH_BASELINE_M.get(site.zoning.zone_type)


def north_interval_m(site: Site) -> float | None:
    """令135条の11第1項2号の間隔の上限。"""
    if not north_slant.applies(site):
        return None
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
                  max_interval_m: float | None = None,
                  regions: list | None = None) -> list[MeasurementPosition]:
    """道路・隣地・北側のすべての算定位置。

    北側を向いた**前面道路**の辺は、道路（令135条の9）と北側
    （令135条の11）の両方の位置を持ちます。どちらの制限も適用される
    ためで、重複ではありません。

    `regions` は令132条の区域（道路の第3項）です。省略すると作ります。
    """
    return (road_positions(site, max_interval_m, regions)
            + adjacent_positions(site, max_interval_m)
            + north_positions(site, max_interval_m))
