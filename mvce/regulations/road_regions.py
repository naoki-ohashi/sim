"""令132条の区域区分（2以上の前面道路）.

前面道路が2以上ある敷地では、敷地が**区域**に分かれ、区域ごとに前面道路の
みなし幅員が変わります。天空率（令135条の6第3項・令135条の9第3項）は
「令132条又は令134条第2項に規定する**区域ごと**」に比較しろと定めているので、
区域を平面図形として持つ必要があります。

    第百三十二条　建築物の前面道路が二以上ある場合においては、幅員の最大な
    前面道路の境界線からの水平距離がその前面道路の幅員の二倍以内で、かつ、
    三十五メートル以内の区域**及び**その他の前面道路の中心線からの水平距離が
    十メートルをこえる区域については、すべての前面道路が幅員の最大な前面道路と
    同じ幅員を有するものとみなす。

    ２　前項の区域外の区域のうち、**二以上**の前面道路の境界線からの水平距離が
    それぞれその前面道路の幅員の二倍（幅員が四メートル未満の前面道路にあつては、
    十メートルからその幅員の二分の一を減じた数値）以内で、かつ、三十五メートル
    以内の区域については、これらの前面道路のみを前面道路とし、これらの前面道路の
    うち、幅員の小さい前面道路は、幅員の大きい前面道路と同じ幅員を有するものと
    みなす。

    ３　前二項の区域外の区域については、その接する前面道路のみを前面道路とする。

## 区域の作り方

各前面道路 r について「**到達範囲**」を決めます（2項の括弧書き）。

    reach(W) = min(35, 2W)              W ≥ 4m
             = min(35, 10 − W/2)        W < 4m

そのうえで、敷地内の各点がどの道路の到達範囲に入っているか（集合 S）で
区域が決まります。

| 条件 | 項 | 前面道路 | みなし幅員 |
|---|---|---|---|
| 最大幅員 A の 2A かつ 35m 以内、**または**他の全前面道路の中心線から 10m 超 | 1項 | すべて | A |
| 1項の外で \\|S\\| ≥ 2 | 2項 | S | max(S の幅員) |
| 1項の外で \\|S\\| = 1 | 3項 | その1本 | その幅員 |

## 狭い道路側からは区分しない

**1項の 2A 区域を生むのは最大幅員の道路だけです。** 新JCBA方式の解説が
わざわざ強調しているところで、間違いが多いそうです。

> ・狭い道路側からの２Ａ処理は、行わない　一体の区域とする（図 1-6-1）
> ・令 132 条の規定は、常に広い道路側から「幅員の２倍かつ 35m」の区域を設定する。
>
> — 日本建築行政会議 報告書 P50（`docs/mvce/methods/新JCBA方式_要点.md`）

3方向道路（A=8m 最大 / B=6m / C=4.5m）だと、区域は3つになります。

1. 1項 … 2A(16m) の帯 ∪ B・C の中心線10m超。みなし幅員 8m
2. 2項 … 1項の外で B(2B=12m) と C(2C=9m) の両方の届く範囲。みなし幅員 6m
3. 3項 … 残り（C だけが届く）。幅員 4.5m

## この実装が抱えている未決点

新JCBA方式の解説の図 1-6-1（4方道路）は、狭い道路 C が B・D の区域に作る
「2C」の小区域を**作るな**（B・D の区域と一体に扱え）と言っています。
この実装は条文どおりに集合 S で切るので、その小区域を作ります。

小区域を分けること自体は**厳しい側**です（算定位置が増え、区域ごとの
適合建築物はその区域の前面道路すべての最小になる）。ただし方式と食い違うので、
JCBA 報告書の原典が手に入ったら確認が要ります（照合台帳の食い違い AD）。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..geometry import offset_polygon_by_edge_distances
from ..site import Site
from ..zoning import UndeterminedRegulation

#: 令132条1項: 最大幅員の境界線から「幅員の2倍」以内
WIDTH_FACTOR = 2.0
#: 令132条1項・2項: かつ35m以内
MAX_DISTANCE_M = 35.0
#: 令132条1項: その他の前面道路の中心線から10mをこえる
CENTERLINE_M = 10.0
#: 令132条2項の括弧書き: 幅員がこれ未満なら 10 − W/2 を使う
NARROW_ROAD_M = 4.0

#: 区域の組み合わせを総当たりする上限。これを超える前面道路は現実的でなく、
#: 2^n の場合分けも意味を失うので止めます。
MAX_ROADS = 6

_EPS = 1e-9


@dataclass(frozen=True)
class RoadRegion:
    """令132条による1つの区域。"""

    polygon: Polygon
    paragraph: int                  # 1 / 2 / 3
    road_indices: tuple[int, ...]   # この区域の前面道路（`site.edges` の番号）
    deemed_width_m: float           # みなし幅員

    @property
    def label_ja(self) -> str:
        roads = "・".join(str(i) for i in self.road_indices)
        return f"令132条{self.paragraph}項の区域（辺{roads} / みなし幅員{self.deemed_width_m:.1f}m）"


def reach_m(width_m: float) -> float:
    """令132条2項の到達範囲。

        その前面道路の幅員の二倍（幅員が四メートル未満の前面道路にあつては、
        十メートルからその幅員の二分の一を減じた数値）以内で、かつ、
        三十五メートル以内

    4m未満で `10 − W/2` を使うのは、その値のほうが `2W` より大きいからです
    （W=3 なら 8.5 > 6）。狭い道路ほど中心線10mの帯が相対的に広くなるので、
    1項の裏返しとして辻褄が合います。
    """
    base = (WIDTH_FACTOR * width_m if width_m >= NARROW_ROAD_M
            else CENTERLINE_M - width_m / 2.0)
    return min(base, MAX_DISTANCE_M)


def centerline_reach_m(width_m: float) -> float:
    """令132条1項の「中心線から10m」を境界線からの距離に直した値。

    中心線は境界線から幅員の半分だけ外側にあるので、境界線からは
    `10 − W/2` です。負になる（幅員20m超）ときは0にします。
    """
    return max(0.0, CENTERLINE_M - width_m / 2.0)


def _within(site: Site, edge_index: int, distance_m: float) -> BaseGeometry:
    """辺から水平距離 `distance_m` 以内の敷地内領域。"""
    site_poly = Polygon(site.points)
    if distance_m <= 0:
        return site_poly.intersection(site_poly.boundary)   # 実質空
    inner = offset_polygon_by_edge_distances(
        site.points,
        [distance_m if j == edge_index else 0.0 for j in range(len(site.edges))])
    return site_poly if inner is None else site_poly.difference(inner)


def _beyond(site: Site, edge_index: int, distance_m: float) -> BaseGeometry:
    """辺から水平距離 `distance_m` を**こえる**敷地内領域。"""
    site_poly = Polygon(site.points)
    if distance_m <= 0:
        return site_poly
    inner = offset_polygon_by_edge_distances(
        site.points,
        [distance_m if j == edge_index else 0.0 for j in range(len(site.edges))])
    return Polygon() if inner is None else inner


def _clean(geometry: BaseGeometry) -> BaseGeometry | None:
    if geometry.is_empty or geometry.area <= 1e-9:
        return None
    return geometry


def _polygons(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [g for g in getattr(geometry, "geoms", []) if g.geom_type == "Polygon"]


def article_132_regions(site: Site) -> list[RoadRegion]:
    """令132条による区域区分。前面道路が1本以下なら空リスト。

    区域は敷地内で互いに重なりません。合計すると（前面道路の到達範囲外を
    除いて）敷地になります。
    """
    roads = [i for i, e in enumerate(site.edges) if e.is_road]
    if len(roads) < 2:
        return []
    if len(roads) > MAX_ROADS:
        raise UndeterminedRegulation(
            f"前面道路が{len(roads)}本あります。令132条の区域区分は"
            f"{MAX_ROADS}本までしか扱いません。"
        )

    widths = {i: site.edges[i].road_width_m for i in roads}
    max_width = max(widths.values())
    widest = [i for i in roads if widths[i] >= max_width - _EPS]
    others = [i for i in roads if i not in widest]

    site_poly = Polygon(site.points)

    # --- 1項 ---------------------------------------------------------
    # (a) 最大幅員の境界線から 2A 以内 かつ 35m 以内。
    #     幅員が並んだときは、そのすべてが「幅員の最大な前面道路」。
    part_a = unary_union([
        _within(site, i, min(WIDTH_FACTOR * max_width, MAX_DISTANCE_M))
        for i in widest
    ])
    # (b) その他の前面道路の中心線から 10m をこえる区域（すべての「その他」について）
    part_b: BaseGeometry = site_poly
    for i in others:
        part_b = part_b.intersection(_beyond(site, i, centerline_reach_m(widths[i])))
    region_1 = unary_union([part_a, part_b])

    regions: list[RoadRegion] = []
    for poly in _polygons(region_1):
        if poly.area > 1e-9:
            regions.append(RoadRegion(
                polygon=poly, paragraph=1,
                road_indices=tuple(roads), deemed_width_m=max_width))

    # --- 2項・3項 -----------------------------------------------------
    # 各道路の到達範囲に入っているかの組み合わせ（集合S）で切る。
    reaches = {i: reach_m(widths[i]) for i in roads}
    within = {i: _within(site, i, reaches[i]) for i in roads}
    beyond = {i: _beyond(site, i, reaches[i]) for i in roads}

    for size in range(len(roads), 0, -1):
        for subset in itertools.combinations(roads, size):
            piece: BaseGeometry = site_poly
            for i in roads:
                piece = piece.intersection(within[i] if i in subset else beyond[i])
                if piece.is_empty:
                    break
            if piece.is_empty:
                continue
            piece = piece.difference(region_1)
            if _clean(piece) is None:
                continue
            deemed = max(widths[i] for i in subset)
            paragraph = 2 if size >= 2 else 3
            for poly in _polygons(piece):
                if poly.area > 1e-9:
                    regions.append(RoadRegion(
                        polygon=poly, paragraph=paragraph,
                        road_indices=tuple(subset), deemed_width_m=deemed))

    return regions


@dataclass(frozen=True)
class RegionAt:
    """ある点における令132条の当てはめ結果（多角形を作らない軽い版）。"""

    paragraph: int
    road_indices: tuple[int, ...]
    deemed_width_m: float


def region_at_point(site: Site, point) -> RegionAt | None:
    """点における令132条の区域。前面道路が1本以下なら None。

    `article_132_regions()` と同じ判定を、多角形を作らずに距離だけで行います。
    斜線制限は点ごとに何万回も呼ばれるので、こちらを使います。
    両者が一致することは `test_road_regions.py` で固定しています。
    """
    from ..geometry import point_line_distance

    roads = [i for i, e in enumerate(site.edges) if e.is_road]
    if len(roads) < 2:
        return None
    if len(roads) > MAX_ROADS:
        raise UndeterminedRegulation(
            f"前面道路が{len(roads)}本あります。令132条の区域区分は"
            f"{MAX_ROADS}本までしか扱いません。"
        )

    widths = {i: site.edges[i].road_width_m for i in roads}
    max_width = max(widths.values())
    widest = [i for i in roads if widths[i] >= max_width - _EPS]
    dist = {
        i: point_line_distance(point, site.edges[i].p1, site.edges[i].p2)
        for i in roads
    }

    # 1項(a) 最大幅員の境界線から 2A 以内 かつ 35m 以内
    limit_a = min(WIDTH_FACTOR * max_width, MAX_DISTANCE_M)
    in_a = any(dist[i] <= limit_a + _EPS for i in widest)
    # 1項(b) その他の前面道路の中心線から 10m をこえる（すべての「その他」について）
    in_b = all(
        dist[i] > centerline_reach_m(widths[i]) + _EPS
        for i in roads if i not in widest
    )
    if in_a or in_b:
        return RegionAt(1, tuple(roads), max_width)

    # 2項・3項: 到達範囲に入っている道路の集合
    subset = tuple(i for i in roads if dist[i] <= reach_m(widths[i]) + _EPS)
    if not subset:
        return None
    deemed = max(widths[i] for i in subset)
    return RegionAt(2 if len(subset) >= 2 else 3, subset, deemed)


def region_at(site: Site, point) -> RoadRegion | None:
    """点が属する区域。どの区域にも入らなければ None。"""
    from shapely.geometry import Point as ShPoint

    p = ShPoint(point)
    for region in article_132_regions(site):
        if region.polygon.covers(p):
            return region
    return None
