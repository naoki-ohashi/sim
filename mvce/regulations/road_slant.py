"""道路斜線制限（法56条1項1号）と関連する緩和.

計算の骨格:

    高さ制限 H = 勾配 × L        （L ≦ 適用距離のとき。超えたら制限なし）
    L = 敷地内の点から「前面道路の反対側の境界線」までの水平距離

適用する緩和:

- **令130条の12（後退緩和）**: 建物を道路境界線から A だけ後退させると、
  反対側境界線がさらに A だけ外側にあるものとみなす。
- **令134条（公園・広場・水面等）**: 道路の反対側にこれらがある場合、
  反対側境界線をその対象物の反対側の境界線とみなす。
- **令135条の2（高低差緩和）**: 敷地の地盤面が道路面より1m以上低い場合、
  道路面が (高低差 - 1) / 2 だけ高い位置にあるものとみなす。
- **令132条（2以上の前面道路）**: 下記参照。

## 令132条の扱い

条文（1項）は次の区域について「すべての前面道路が最大幅員の道路と同じ
幅員を有するものとみなす」としています。

    (a) 幅員最大の前面道路の境界線から、その幅員の2倍以内 かつ 35m以内
    (b) その他の前面道路の中心線から10mを超える区域

本モジュールは点ごとに (a) または (b) に該当するかを判定し、該当する場合は
その点における各前面道路の幅員を最大幅員に読み替えて計算します。狭い道路に
面していても、条件を満たす範囲では広い道路の斜線で判定できるため、実際に
建てられる高さが上がります。

複雑な道路配置（3本以上で幅員がばらつく、屈曲した道路など）では行政庁の
運用が分かれることがあります。判定内訳は `RoadSlantDetail` で確認できます。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import Point, outward_normal, point_line_distance
from ..site import Boundary, RelaxationKind, Site
from ..zoning import road_slant_tier

# 令134条の緩和対象（道路斜線）: 公園・広場・水面
ROAD_RELAXATION_KINDS = {RelaxationKind.PARK, RelaxationKind.WATER}

# 令132条1項の定数
MULTI_ROAD_WIDTH_FACTOR = 2.0     # 最大幅員の2倍以内
MULTI_ROAD_MAX_DISTANCE_M = 35.0  # かつ35m以内
MULTI_ROAD_CENTERLINE_M = 10.0    # 他の道路の中心線から10m超


@dataclass
class RoadSlantDetail:
    """1本の前面道路が、ある点に与える制限の内訳（根拠の確認用）。"""

    edge_index: int
    actual_width_m: float
    applied_width_m: float      # 令132条で読み替えた後の幅員
    widened_by_article_132: bool
    distance_from_boundary_m: float   # 敷地内の点から道路境界線までの距離
    relaxation_extra_m: float         # 令134条による追加分
    level_relaxation_m: float         # 令135条の2による見かけの高さ低減
    total_distance_m: float           # L（反対側境界線からの水平距離）
    applicable_distance_m: float
    slope: float
    height_limit_m: float             # この道路による制限（inf なら適用距離外）


def _level_relaxation(edge: Boundary) -> float:
    """令135条の2: 地盤面が道路より1m以上低い場合の見かけの高さ。

    高低差 h に対して (h - 1) / 2 だけ道路が高い位置にあるとみなすので、
    その分だけ敷地側の許容高さが上がります。
    """
    h = edge.ground_level_diff_m
    return (h - 1.0) / 2.0 if h >= 1.0 else 0.0


def _relaxation_extra(edge: Boundary) -> float:
    """令134条: 道路の反対側の公園・広場・水面の幅（そのぶん外側とみなす）。"""
    relax = edge.relaxation
    if relax.active and relax.kind in ROAD_RELAXATION_KINDS:
        return relax.width_m
    return 0.0


def applied_width_at(site: Site, point: Point, edge: Boundary) -> tuple[float, bool]:
    """令132条を適用した後の、その点における `edge` の幅員。

    戻り値は (適用幅員, 読み替えが起きたか)。
    """
    roads = site.road_edges
    max_width = site.max_road_width_m
    if len(roads) < 2 or edge.road_width_m >= max_width:
        return edge.road_width_m, False

    widest = max(roads, key=lambda e: e.road_width_m)

    # (a) 最大幅員道路の境界線から 2A 以内 かつ 35m 以内
    d_widest = point_line_distance(point, widest.p1, widest.p2)
    in_a = (d_widest <= MULTI_ROAD_WIDTH_FACTOR * max_width + 1e-9
            and d_widest <= MULTI_ROAD_MAX_DISTANCE_M + 1e-9)

    # (b) この道路の中心線から 10m を超える
    #     中心線は道路境界線から幅員の半分だけ敷地の外側にある
    d_centerline = point_line_distance(point, edge.p1, edge.p2) + edge.road_width_m / 2.0
    in_b = d_centerline > MULTI_ROAD_CENTERLINE_M + 1e-9

    if in_a or in_b:
        return max_width, True
    return edge.road_width_m, False


def detail_at(site: Site, point: Point, edge_index: int) -> RoadSlantDetail:
    edge = site.edges[edge_index]
    if not edge.is_road:
        raise ValueError("道路境界線ではありません")

    tier = road_slant_tier(site.zoning.zone_type, site.zoning.far_ratio,
                           site.zoning.unspecified_road_slant_slope)
    applied_width, widened = applied_width_at(site, point, edge)
    s = point_line_distance(point, edge.p1, edge.p2)
    extra = _relaxation_extra(edge)
    level = _level_relaxation(edge)

    # L = 敷地内の距離 + 道路幅員 + 後退距離 + 公園等の幅
    total = s + applied_width + edge.wall_setback_m + extra
    if total > tier.applicable_distance_m + 1e-9:
        height = math.inf
    else:
        height = tier.slope * total + level

    return RoadSlantDetail(
        edge_index=edge_index,
        actual_width_m=edge.road_width_m,
        applied_width_m=applied_width,
        widened_by_article_132=widened,
        distance_from_boundary_m=s,
        relaxation_extra_m=extra,
        level_relaxation_m=level,
        total_distance_m=total,
        applicable_distance_m=tier.applicable_distance_m,
        slope=tier.slope,
        height_limit_m=height,
    )


def height_limit_at(site: Site, point: Point) -> float:
    """すべての前面道路による道路斜線の高さ制限（最も厳しいもの）。"""
    limits = [
        detail_at(site, point, i).height_limit_m
        for i, e in enumerate(site.edges) if e.is_road
    ]
    return min(limits) if limits else math.inf


def details_at(site: Site, point: Point) -> list[RoadSlantDetail]:
    return [detail_at(site, point, i) for i, e in enumerate(site.edges) if e.is_road]


def opposite_boundary_line(site: Site, edge_index: int) -> tuple[Point, Point]:
    """道路境界線の「反対側」とみなす基準線（3D表示・図面確認用）。

    令130条の12（後退緩和）・令134条（公園等緩和）を反映した、実際に
    道路斜線の高さ制限で使われている基準線です。令132条（2以上の前面
    道路の幅員読み替え）は敷地内の点ごとに結果が変わるため、静的な1本の
    線としては表現していません（`applied_width_at` を参照）。

    後退・緩和が無ければ、道路の反対側境界線（`_road_polygon` が描く
    帯の遠い辺）と一致します。
    """
    edge = site.edges[edge_index]
    if not edge.is_road:
        raise ValueError("道路境界線ではありません")

    offset = edge.road_width_m + edge.wall_setback_m + _relaxation_extra(edge)
    nx, ny = outward_normal(edge.p1, edge.p2)
    p1 = (edge.p1[0] + offset * nx, edge.p1[1] + offset * ny)
    p2 = (edge.p2[0] + offset * nx, edge.p2[1] + offset * ny)
    return p1, p2


def opposite_boundary_lines(site: Site) -> list[tuple[int, tuple[Point, Point]]]:
    """前面道路すべてについて (辺インデックス, 反対側基準線) の一覧。"""
    return [
        (i, opposite_boundary_line(site, i))
        for i, edge in enumerate(site.edges) if edge.is_road
    ]


def required_setback_for_height(site: Site, edge_index: int, height_m: float) -> float:
    """高さ `height_m` を確保するために必要な、道路境界線からの後退距離。

    L の式を s について解いたものです。適用距離を超えると制限が外れるため、
    必要距離は「適用距離まで下がれば以降は自由」という上限で頭打ちにします。
    緩和（後退・公園等・高低差）は考慮済みです。
    """
    edge = site.edges[edge_index]
    if not edge.is_road or height_m <= 0:
        return 0.0

    tier = road_slant_tier(site.zoning.zone_type, site.zoning.far_ratio,
                           site.zoning.unspecified_road_slant_slope)
    # 幅員は最も不利（読み替えなし）の値で見る。読み替えは点ごとの判定なので、
    # ここでは安全側に実幅員を使う。
    base = edge.road_width_m + edge.wall_setback_m + _relaxation_extra(edge)
    level = _level_relaxation(edge)

    h0 = tier.slope * base + level          # 敷地境界線上（s=0）での制限高さ
    if height_m <= h0:
        return 0.0
    needed_total = (height_m - level) / tier.slope
    s_needed = needed_total - base
    s_max = max(0.0, tier.applicable_distance_m - base)  # ここまで下がれば制限外
    return min(s_needed, s_max)
