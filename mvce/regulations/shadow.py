"""日影規制（法56条の2、令135条の12）.

冬至日の真太陽時8時〜16時（北海道は9時〜15時）に、**測定面**の高さの
水平面上で、敷地境界線から5m・10mの範囲に一定時間以上の日影を生じさせない
こと、という規制です。

## 測定面（法56条の2第1項・別表第四）

> **要照合** — 従来この docstring は根拠を「令135条の12第1項」としていま
> したが誤りです。同項は許可に係る「位置」の規定で、測定面とは関係あり
> ません。正しい根拠は法56条の2第1項および別表第四と思われますが、
> その原文をまだ取得していないため断定していません
> （`docs/mvce/legal_basis.md` の「食い違い B」）。

平均地盤面からの高さで 1.5m / 4m / 6.5m のいずれか。どれが適用されるかは
用途地域と条例で決まります（低層住居専用・田園住居は1.5m、その他の対象
地域は4mまたは6.5m）。`ShadowRegulationSpec.measurement_height_m` で
指定します。

## みなし境界線（令135条の12第3項第1号）

敷地が道路・水面・線路敷等に接する場合、その分だけ敷地境界線が外側に
あるものとみなせます。

    幅が10m以下  … 幅の 1/2 だけ外側
    幅が10m超    … 反対側の境界線から敷地側へ 5m の線

道路に接する敷地では、この緩和で測定線がかなり外へ出るため、日影規制の
厳しさが実際にはだいぶ変わります。

> **未決** — 条文が列挙するのは「道路、水面、線路敷その他これらに類する
> もの」で、**公園・広場は明示されていません**。令134条（道路斜線）と
> 令135条の3（隣地斜線）が「公園、広場、水面」と明示しているのとは対照的
> です。`DEEMED_BOUNDARY_KINDS` は公園を含めていますが、これは「その他
> これらに類するもの」に当たるという解釈であって、条文がそう書いている
> わけではありません（`docs/mvce/legal_basis.md` の「食い違い C」）。

## 5m/10mラインの取り方

規制時間は「敷地境界線からの水平距離が5mを超え10m以内の範囲」と
「10mを超える範囲」で分かれます（別表第四）。本モジュールは
**みなし境界線から5m・10mの等距離線上**に測定点を並べ、各点の日影時間を
求めます。

## 日影時間の求め方

各時刻について、建物が測定面へ落とす影の領域に測定点が入るかを判定し、
入っていた時間を積算します。影の領域は「平面形状と、影のずれベクトルが
作るミンコフスキー和」ですが、和集合を作らずに

    点Pが影の中 ⟺ 線分 [P-d, P] が平面形状と交わる

という同値関係で判定しています（`d` は影のずれベクトル）。ブロックごとに
独立に判定できるので、多角形の和集合演算が不要になります。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon

from ..geometry import Point, ensure_ccw, interior_normal, polygon_to_ring
from ..massing import Block
from ..site import RelaxationKind, Site
from ..solar import (
    HOKKAIDO_HOURS,
    STANDARD_HOURS,
    WINTER_SOLSTICE,
    day_of_year,
    solar_declination_deg,
    solar_position_deg,
)


# 令135条の12第3項第1号「道路、水面、線路敷その他これらに類するもの」。
# 公園は条文に明示が無く、「これらに類するもの」に当たるという解釈で
# 入れています（legal_basis.md の食い違い C）。判断が付いたら見直すこと。
DEEMED_BOUNDARY_KINDS = {RelaxationKind.WATER, RelaxationKind.RAILWAY, RelaxationKind.PARK}
DEEMED_BOUNDARY_WIDTH_THRESHOLD_M = 10.0
DEEMED_BOUNDARY_INSET_M = 5.0


@dataclass
class ShadowRegulationSpec:
    """適用される日影規制の内容.

    規制時間（`line_5m_max_hours` / `line_10m_max_hours`）と測定面は
    **条例で決まる**ため、既定値は置かずに必ず指定してもらう設計に
    しています。都市計画図と自治体の条例（別表第四相当）で確認して
    ください。
    """

    measurement_height_m: float          # 1.5 / 4.0 / 6.5
    line_5m_max_hours: float             # 5m超10m以内の範囲の規制時間
    line_10m_max_hours: float            # 10m超の範囲の規制時間
    latitude_deg: float = 35.7
    hokkaido: bool = False               # 北海道は9時〜15時
    time_step_minutes: float = 10.0
    sample_interval_m: float = 2.0       # 測定線上の点の間隔
    apply_deemed_boundary: bool = True   # 令135条の12第3項の緩和を使うか
    #: 等時間日影図（等時間日影線）を作る時間のリスト（例: [2.0, 3.0, 4.0, 5.0]）。
    #: 空リスト（既定）なら作らない。`mvce/index/isochrone.py` を参照。
    isochrone_hours: list[float] = field(default_factory=list)
    #: 等時間日影図のグリッド間隔(m)。細かくすると精度が上がるが計算時間も増える。
    isochrone_grid_interval_m: float = 2.0
    #: 等時間日影図のグリッドを敷地の外側にどれだけ広げるか(m)。
    #: None なら建物高さと最低太陽高度から自動計算する。
    isochrone_margin_m: float | None = None

    def __post_init__(self) -> None:
        if self.measurement_height_m not in (1.5, 4.0, 6.5):
            raise ValueError(
                f"測定面は1.5m / 4m / 6.5m のいずれかです（指定値: {self.measurement_height_m}）"
            )
        if self.line_5m_max_hours <= 0 or self.line_10m_max_hours <= 0:
            raise ValueError("規制時間は正の値で指定してください")
        if self.line_10m_max_hours > self.line_5m_max_hours:
            raise ValueError(
                "10m超の規制時間が5m〜10mの規制時間より長くなっています"
                "（別表第四では外側ほど短くなります）"
            )
        if any(h <= 0 for h in self.isochrone_hours):
            raise ValueError("isochrone_hours は正の値で指定してください")
        if self.isochrone_grid_interval_m <= 0:
            raise ValueError("isochrone_grid_interval_m は正の値にしてください")
        if self.isochrone_margin_m is not None and self.isochrone_margin_m <= 0:
            raise ValueError("isochrone_margin_m は正の値にしてください")

    @property
    def hours_range(self) -> tuple[float, float]:
        return HOKKAIDO_HOURS if self.hokkaido else STANDARD_HOURS

    def true_solar_hours(self) -> list[float]:
        start, end = self.hours_range
        step = self.time_step_minutes / 60.0
        hours = []
        h = start
        while h < end - 1e-9:
            hours.append(h)
            h += step
        return hours


@dataclass
class ShadowLineResult:
    distance_m: float                      # 5.0 or 10.0
    max_hours: float                       # 規制時間
    point_hours: list[tuple[Point, float]] = field(default_factory=list)

    @property
    def worst_hours(self) -> float:
        return max((h for _, h in self.point_hours), default=0.0)

    @property
    def worst_point(self) -> Point | None:
        if not self.point_hours:
            return None
        return max(self.point_hours, key=lambda ph: ph[1])[0]

    @property
    def ok(self) -> bool:
        return self.worst_hours <= self.max_hours + 1e-9

    @property
    def margin_hours(self) -> float:
        return self.max_hours - self.worst_hours


def deemed_boundary_offsets(site: Site) -> list[float]:
    """辺ごとの、令135条の12第3項によるみなし境界線の外側への移動量。"""
    offsets = []
    for edge in site.edges:
        width = 0.0
        if edge.is_road:
            width = edge.road_width_m
        elif edge.relaxation.active and edge.relaxation.kind in DEEMED_BOUNDARY_KINDS:
            width = edge.relaxation.width_m

        if width <= 0:
            offsets.append(0.0)
        elif width <= DEEMED_BOUNDARY_WIDTH_THRESHOLD_M:
            offsets.append(width / 2.0)
        else:
            # 幅が10m超: 反対側境界線から敷地側5mの線が境界線とみなされる
            offsets.append(max(0.0, width - DEEMED_BOUNDARY_INSET_M))
    return offsets


def _offset_ring(points: list[Point], offsets: list[float]) -> list[Point]:
    """各辺を外向きに offsets[i] だけ動かし、角は延長して交点で結ぶ。"""
    pts = ensure_ccw(points)
    n = len(pts)
    moved = []
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        nx, ny = interior_normal(p1, p2)
        d = offsets[i]
        moved.append((
            (p1[0] - d * nx, p1[1] - d * ny),
            (p2[0] - d * nx, p2[1] - d * ny),
        ))
    corners = []
    for i in range(n):
        (a1, a2), (b1, b2) = moved[i], moved[(i + 1) % n]
        d1 = (a2[0] - a1[0], a2[1] - a1[1])
        d2 = (b2[0] - b1[0], b2[1] - b1[1])
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-12:  # 平行（同一直線上）ならそのまま端点を使う
            corners.append(a2)
            continue
        t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / den
        corners.append((a1[0] + t * d1[0], a1[1] + t * d1[1]))
    return corners


def regulation_boundary(site: Site, spec: ShadowRegulationSpec) -> list[Point]:
    """日影規制の基準となる敷地境界線（みなし境界線を適用したもの）。"""
    if not spec.apply_deemed_boundary:
        return ensure_ccw(site.points)
    return _offset_ring(site.points, deemed_boundary_offsets(site))


def measurement_points(site: Site, spec: ShadowRegulationSpec, distance_m: float) -> list[Point]:
    """みなし境界線から `distance_m` の等距離線上に並べた測定点。"""
    base = regulation_boundary(site, spec)
    ring = _offset_ring(base, [distance_m] * len(base))
    line = LineString(list(ring) + [ring[0]])
    length = line.length
    if length <= 0:
        return ring
    count = max(3, math.ceil(length / spec.sample_interval_m))
    return [tuple(line.interpolate(length * i / count).coords[0]) for i in range(count)]


def _point_in_block_shadow(
    point: Point, block: Block, altitude_deg: float, azimuth_deg: float,
    measurement_height_m: float, site: Site,
) -> bool:
    """測定面の高さで、点が1つのブロックの影に入っているか。

    測定面より低い部分は影を落とさないので、有効な高さは
    (ブロック頂部 - 測定面高さ) になります。
    """
    effective_height = block.z_top - measurement_height_m
    if effective_height <= 0:
        return False
    shift_len = effective_height / math.tan(math.radians(altitude_deg))
    # 影は太陽の反対方向へ伸びる。方位角は真北基準なので図面座標に直す。
    sun_dir = site.north.vector_for_azimuth(azimuth_deg)
    shift = (-sun_dir[0] * shift_len, -sun_dir[1] * shift_len)
    origin = (point[0] - shift[0], point[1] - shift[1])
    return block.footprint.intersects(LineString([origin, point]))


def compute_shadow_hours(
    site: Site, blocks: list[Block], spec: ShadowRegulationSpec
) -> list[ShadowLineResult]:
    """5mラインと10mラインの各測定点における日影時間を求める。"""
    declination = solar_declination_deg(day_of_year(*WINTER_SOLSTICE))
    hours = spec.true_solar_hours()
    step = spec.time_step_minutes / 60.0

    lines = [
        ShadowLineResult(5.0, spec.line_5m_max_hours, []),
        ShadowLineResult(10.0, spec.line_10m_max_hours, []),
    ]
    points_by_line = {
        line.distance_m: measurement_points(site, spec, line.distance_m) for line in lines
    }
    duration = {d: [0.0] * len(pts) for d, pts in points_by_line.items()}

    if blocks:
        for hour in hours:
            altitude, azimuth = solar_position_deg(spec.latitude_deg, declination, hour)
            if altitude <= 0:
                continue
            for distance, pts in points_by_line.items():
                accumulated = duration[distance]
                for i, point in enumerate(pts):
                    for block in blocks:
                        if _point_in_block_shadow(
                            point, block, altitude, azimuth, spec.measurement_height_m, site
                        ):
                            accumulated[i] += step
                            break

    for line in lines:
        pts = points_by_line[line.distance_m]
        line.point_hours = list(zip(pts, duration[line.distance_m]))
    return lines


def is_compliant(site: Site, blocks: list[Block], spec: ShadowRegulationSpec) -> bool:
    return all(line.ok for line in compute_shadow_hours(site, blocks, spec))
