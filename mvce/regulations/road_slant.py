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

条文は3項あります。

**1項** — 次の2つの区域について「すべての前面道路が最大幅員の道路と同じ
幅員を有するものとみなす」。

    (a) 幅員最大の前面道路の境界線から、その幅員の2倍以内 かつ 35m以内
    (b) その他の前面道路の中心線から10mを超える区域

条文が2つの区域を「及び」で並べているとおり、どちらかに該当すれば
読み替えます。狭い道路に面していても、条件を満たす範囲では広い道路の
斜線で判定できるので、建てられる高さが上がります。

**2項** — 1項の区域外で、2以上の前面道路の境界線からそれぞれ幅員の2倍
（幅員4m未満の道路は `10 − 幅員/2`）かつ35m以内の区域については、それらの
道路のみを前面道路とし、幅員の小さいものを大きいものと同じ幅員とみなす。

**3項** — 前2項の区域外は、その接する前面道路のみを前面道路とする。

### 前面道路が2本のとき

**2項の区域は空になります。** 2項は「1項の区域外」に限られますが、2本の
場合、2項が要求する「両方の道路の2倍かつ35m以内」は 1項(a)（最大幅員道路の
2倍かつ35m以内）を含んでしまうためです。したがって 1項に該当しなければ
3項、つまり接する道路の幅員をそのまま使います。本モジュールはそう実装して
います。

### 令131条の2（前面道路とみなす道路等）は非対応

土地区画整理地区の指定街区（1項）、計画道路・予定道路（2項）、壁面線・
条例の壁面位置制限（3項）を前面道路とみなす規定です。**実装していません。**

3つとも**特定行政庁の指定・認定が前提**で、MVCE が敷地情報だけから
判定できるものではありません（原則H）。使う場合は、みなし後の道路を
そのまま `Boundary` の前面道路として入力してください。そのほうが
「行政庁の認定を受けた前提で検討している」ことが入力に残ります。

なお2項は令135条の3第1項3号・令135条の4第1項3号（計画道路内の隣地
境界線はないものとみなす）からも参照されており、そちらも非対応です。

### 令134条2項（公園等がある道路を基準にする選択）

前面道路が2以上あり、そのうちの1つの反対側に公園・広場・水面等がある
場合、令132条1項によらず、**その道路を基準に全前面道路をみなす**ことが
できます。

    区域 = 公園等がある前面道路の境界線から
           「公園等の反対側の境界線から当該前面道路の境界線までの距離」の2倍以内
           かつ 35m以内
           （及び その他の前面道路の中心線から10m超）

この区域では、すべての前面道路が「公園等がある前面道路と同じ幅員を持ち、
かつ反対側に同様の公園等がある」ものとみなされます。

条文は「前項の規定に**よることができる**」で、**選択できる**規定です。
使うかどうかは設計者の判断なので、`Site.apply_article_134_2` を明示的に
`True` にしたときだけ適用します。既定は `False`（＝令132条1項による）で、
そのほうが保守側です。

### 前面道路が3本以上のとき

**計算します**（2026-08-30）。それまでは `UndeterminedRegulation` で
止めていました（食い違い W）。2項が実際に効くのはこの場合で、点ごとに
どの道路の集合が「前面道路」になるかが変わります。

区域の切り方は `road_regions.py` にまとめました。日本建築行政会議の
新JCBA方式の解説（`docs/mvce/methods/`）で、とくに

- 1項の 2A 区域を生むのは**最大幅員の道路だけ**（狭い道路側からは区分しない）
- 1項(b) は「その他の**すべての**前面道路の中心線から10m超」

が確認できたため、条文どおりに実装できるようになりました。

集合に含まれない道路は、その点では前面道路ではありません（2項「これらの
前面道路のみを前面道路とし」・3項「その接する前面道路のみを前面道路と
する」）。`applied_width_at()` はその場合に実幅員を返し、適用距離の判定で
制限が外れます。

判定内訳は `RoadSlantDetail` で確認できます。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..far import effective_far_limit
from ..geometry import Point, outward_normal, point_line_distance
from ..site import Boundary, RelaxationKind, Site

# 令134条1項の緩和対象: 「公園、広場、水面その他これらに類するもの」。
# 線路敷は列挙されていないので入れない。都市公園を除く規定も無いので、
# 都市公園は対象に入る（隣地＝令135条の3 とはここが違う）。
ROAD_RELAXATION_KINDS = {
    RelaxationKind.PARK, RelaxationKind.URBAN_PARK, RelaxationKind.WATER,
}

# 令132条の定数（令134条2項の判定で使う。区域区分そのものは road_regions.py）
MULTI_ROAD_WIDTH_FACTOR = 2.0     # 1項(a): 最大幅員の2倍以内
MULTI_ROAD_MAX_DISTANCE_M = 35.0  # 1項(a)・2項: かつ35m以内
MULTI_ROAD_CENTERLINE_M = 10.0    # 1項(b): 他の道路の中心線から10m超


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
    """令135条の2: 敷地の地盤面が前面道路より1m以上高い場合の緩和。

        第百三十五条の二　建築物の敷地の地盤面が前面道路より一メートル以上
        高い場合においては、その前面道路は、敷地の地盤面と前面道路との
        高低差から一メートルを減じたものの二分の一だけ高い位置にあるものと
        みなす。

    道路を高い位置にあるものとみなすので、そのぶん敷地側の許容高さが
    上がります。

    **隣地（令135条の3第1項2号）・北側（令135条の4第1項2号）とは向きが
    逆です。** あちらは敷地が隣地より「低い」ときに効きます。
    `ground_level_diff_m` は「外側が敷地より何m高いか」の符号つきなので、
    道路ではその符号を反転して見ます。
    """
    rise = -edge.ground_level_diff_m   # 敷地が道路よりどれだけ高いか
    return (rise - 1.0) / 2.0 if rise >= 1.0 else 0.0


def _relaxation_extra(edge: Boundary) -> float:
    """令134条: 道路の反対側の公園・広場・水面の幅（そのぶん外側とみなす）。"""
    relax = edge.relaxation
    if relax.active and relax.kind in ROAD_RELAXATION_KINDS:
        return relax.width_m
    return 0.0


def article_134_2_span(site: Site, point: Point) -> tuple[float, float] | None:
    """令134条2項を選択したときの、その点での (みなし幅員, みなし公園等の幅)。

    適用外なら None。条文は「すべての前面道路を当該公園等がある前面道路と
    同じ幅員を有し、**かつ、その反対側に同様の公園等があるもの**とみなす」
    としているので、幅員だけでなく公園等の幅も全前面道路に及びます。
    だから2つ返します。
    """
    if not site.apply_article_134_2:
        return None
    roads = site.road_edges
    if len(roads) < 2:
        return None
    with_park = [r for r in roads
                 if r.relaxation.active and r.relaxation.kind in ROAD_RELAXATION_KINDS]
    if not with_park:
        return None

    best: tuple[float, float] | None = None
    for base in with_park:
        # 公園等の反対側の境界線から当該前面道路の境界線までの水平距離
        span = base.road_width_m + base.relaxation.width_m
        d_base = point_line_distance(point, base.p1, base.p2)
        in_a = (d_base <= MULTI_ROAD_WIDTH_FACTOR * span + 1e-9
                and d_base <= MULTI_ROAD_MAX_DISTANCE_M + 1e-9)
        others = [r for r in roads if r is not base]
        in_b = all(
            point_line_distance(point, r.p1, r.p2) + r.road_width_m / 2.0
            > MULTI_ROAD_CENTERLINE_M + 1e-9
            for r in others
        )
        if not (in_a or in_b):
            continue
        # 「よることができる」選択規定なので、複数の候補があれば
        # 設計者に有利な（＝反対側境界線が遠い）ものを採る。
        if best is None or span > best[0] + best[1]:
            best = (base.road_width_m, base.relaxation.width_m)
    return best


def applied_width_at(site: Site, point: Point, edge: Boundary) -> tuple[float, bool]:
    """令132条を適用した後の、その点における `edge` の幅員。

    戻り値は (適用幅員, 読み替えが起きたか)。

    区域の切り方は `road_regions.py` にまとめてあります。**前面道路が3本以上
    でも計算できます**（2026-08-30。それまでは `UndeterminedRegulation` で
    止めていました。新JCBA方式の解説で区域の切り方が確認できたため）。

    その点の区域に `edge` が前面道路として含まれていなければ、`edge` は
    その点では前面道路ではありません（令132条2項「これらの前面道路のみを
    前面道路とし」・3項「その接する前面道路のみを前面道路とする」）。
    その場合は幅員をそのまま返し、`detail_at()` 側で適用距離により
    制限が外れます。
    """
    from .road_regions import region_at_point

    region = region_at_point(site, point)
    if region is None:
        return edge.road_width_m, False

    edge_index = next(
        (i for i, e in enumerate(site.edges) if e is edge), None)
    if edge_index is None or edge_index not in region.road_indices:
        # その点ではこの道路は前面道路ではない
        return edge.road_width_m, False

    widened = region.deemed_width_m > edge.road_width_m + 1e-9
    return region.deemed_width_m, widened


def detail_at(site: Site, point: Point, edge_index: int) -> RoadSlantDetail:
    edge = site.edges[edge_index]
    if not edge.is_road:
        raise ValueError("道路境界線ではありません")

    tier = site.zoning.road_slant_tier(effective_far_limit(site))
    span = article_134_2_span(site, point)
    if span is not None:
        # 令134条2項を選択。全前面道路が公園等のある道路と同じ幅員を持ち、
        # 反対側に同様の公園等があるものとみなす。
        applied_width, extra = span
        widened = applied_width > edge.road_width_m
    else:
        applied_width, widened = applied_width_at(site, point, edge)
        extra = _relaxation_extra(edge)
    s = point_line_distance(point, edge.p1, edge.p2)
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


def slant_distance_for_height(site: Site, edge_index: int, height_m: float,
                              width_m: float | None = None) -> float:
    """高さ `height_m` に必要な、道路境界線からの後退距離（**適用距離で
    頭打ちにしない**素の値）。

    `required_setback_for_height()` は「適用距離まで下がれば以降は自由」と
    いう上限で頭打ちにします。それはボリューム探索には正しい扱いですが、
    **天空率の道路高さ制限適合建築物には使えません**。あちらは
    「道路高さ制限が適用される範囲内の部分に限る」（令135条の6第1項1号）
    ので、適用距離までの帯の中で斜線どおりの形を作る必要があり、
    頭打ちにすると帯の中に何も残らなくなります。

    `width_m` は令132条のみなし幅員を渡すためのものです。省略すると実幅員を
    使います。緩和（後退・公園等・高低差）は幅員を差し替えてもそのまま
    効きます。令132条が読み替えるのは**幅員だけ**だからです。
    """
    edge = site.edges[edge_index]
    if not edge.is_road or height_m <= 0:
        return 0.0
    tier = site.zoning.road_slant_tier(effective_far_limit(site))
    width = edge.road_width_m if width_m is None else width_m
    base = width + edge.wall_setback_m + _relaxation_extra(edge)
    level = _level_relaxation(edge)
    if height_m <= tier.slope * base + level:
        return 0.0
    return (height_m - level) / tier.slope - base


def required_setback_for_height(site: Site, edge_index: int, height_m: float) -> float:
    """高さ `height_m` を確保するために必要な、道路境界線からの後退距離。

    L の式を s について解いたものです。適用距離を超えると制限が外れるため、
    必要距離は「適用距離まで下がれば以降は自由」という上限で頭打ちにします。
    緩和（後退・公園等・高低差）は考慮済みです。
    """
    edge = site.edges[edge_index]
    if not edge.is_road or height_m <= 0:
        return 0.0

    tier = site.zoning.road_slant_tier(effective_far_limit(site))
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
