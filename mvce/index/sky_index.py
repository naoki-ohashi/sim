"""天空率の「入射距離」インデックス.

ボクセル最適化で天空率（法56条7項）を扱うための中核データです。
`index/shadow_index.py` と同じ考え方を、日影ではなく天空率に適用したものです。

## 考え方

測定点 P、方位 φ、メッシュのマス C を固定すると、P から φ 方向へ伸ばした
半直線が C に入るまでの距離 r は**マスの高さによらず一定**です。したがって
先に r を計算しておけば、天空率は高さ配列との比較だけで求まります。

    C が方位 φ で作る仰角 = atan2(h_C - z0, r(P, φ, C))
    その方位の稜線      = マスについての最大値
    天空率 Ps           = Σ 0.5・cos²(仰角)・dφ / π × 100     （正射影）

r が無限大（半直線がCを通らない）なら仰角0、つまり空が見えます。

## 階ごとのブロックに統合しても同じ値になる

`sky_ratio.sky_ratio_percent` は階ごとに結合したブロックを見ますが、
マスごとに見た最大値と**厳密に一致**します。

- ブロック側の最大値は、各階層について「その階に達している最も近いマス」で決まる
- マス側の最大値を与えるマス c* は、階層 k = floors[c*] - 1 で同じ値を作れる

両方向の不等式が成り立つため一致します。マス単位で持てるので、
**超過した測定点についてどのマスが稜線を作っているかを特定でき、
そのマスだけを下げる**という判断ができます。

## 適合建築物（Pr）

Pr は斜線制限ぎりぎりの適合建築物から求めます。こちらは任意形状の多角形
なのでインデックス化せず、`sky_ratio.sky_ratio_percent` で1回だけ計算して
保持します。最適化中に変化しないためです。

## 近似について

半直線とマスの交差は軸平行の外接矩形（スラブ法）で判定します。メッシュを
回転させていない場合（`mesh_angle_deg = 0`）はマスが軸平行なので厳密です。
回転させた場合はマスをわずかに大きく見積もるため、天空率は安全側
（塞ぐ側）に出ます。

天空図の投影方法と測定点の配置は内部で一貫した近似であり、告示が定める
厳密な測定点設置規則には準拠していません（`docs/mvce/disclaimer.md`）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..geometry import Point
from ..massing import Block
from ..mesh import BuildableArea
from ..regulations.sky_ratio import (
    azimuths_deg,
    measurement_points,
    applicable_region,
    reference_buildings,
    sky_ratio_percent,
)
from .shadow_index import _ray_entry_distances
from ..site import Site

#: 方位の分割数の既定値。測定点の**間隔は条文が定める**ので既定値を
#: 持ちません（令135条の9〜11。`regulations/sky_positions.py`）。
DEFAULT_N_AZIMUTH = 72

#: 方位を刻み幅の半分だけずらす。0/90/180/270度ちょうどを避けることで、
#: 軸に平行なマスの面に沿って走る光線という縮退をなくす（`azimuths_deg` 参照）。
AZIMUTH_OFFSET_RATIO = 0.5

#: Ps ≧ Pr の判定に使う許容誤差(%)
TOLERANCE_PERCENT = 1e-9


@dataclass
class SkyIndex:
    """(測定点, 方位, マス) ごとの入射距離と、適合建築物の天空率。

    `distances[point_index]` は形状 (方位数, マス数) の配列で、値はその方位の
    半直線がそのマスに入るまでの距離(m)。入らなければ `inf`。
    """

    points: list[Point]
    kinds: list[str]                 # "road" | "adjacent" | "north"
    edge_indices: list[int]
    distances: list[np.ndarray]      # 点ごとの (方位, マス)
    pr: np.ndarray                   # 点ごとの適合建築物の天空率(%)
    #: 点ごとの想定半球の中心の高さ（令135条の9〜11）。道路は路面の中心、
    #: 隣地・北側は敷地の地盤面で、位置ごとに違う。
    z_m: np.ndarray
    n_azimuth: int
    n_cells: int
    azimuth_offset_ratio: float = AZIMUTH_OFFSET_RATIO

    @property
    def d_phi(self) -> float:
        return 2 * math.pi / self.n_azimuth

    def ps_at(self, point_index: int, heights: np.ndarray) -> float:
        """現在の高さ配列における、その測定点の計画建築物の天空率(%)。"""
        dist = self.distances[point_index]
        if dist.size == 0:
            return 100.0
        above = heights - self.z_m[point_index]
        elevation = np.arctan2(np.maximum(above, 0.0)[None, :], dist)
        rho = np.cos(elevation.max(axis=1))
        return float((0.5 * rho * rho * self.d_phi).sum() / math.pi * 100.0)

    def ps(self, heights: np.ndarray) -> np.ndarray:
        return np.array([self.ps_at(i, heights) for i in range(len(self.points))])

    def worst(self, heights: np.ndarray) -> tuple[int, float, float] | None:
        """最も不足している測定点。

        戻り値は (点インデックス, Ps, 不足分 Pr - Ps)。すべて適合していれば None。
        """
        worst = None
        for i in range(len(self.points)):
            ps = self.ps_at(i, heights)
            deficit = self.pr[i] - ps
            if deficit > TOLERANCE_PERCENT and (worst is None or deficit > worst[2]):
                worst = (i, ps, deficit)
        return worst

    def is_compliant(self, heights: np.ndarray) -> bool:
        return self.worst(heights) is None

    def ridge_cells(self, point_index: int, heights: np.ndarray) -> list[int]:
        """その測定点で稜線（各方位の最大仰角）を作っているマス。

        これらを下げれば天空率が上がります。逆に、ここに無いマスをいくら
        下げても、その測定点の天空率は変わりません。
        """
        dist = self.distances[point_index]
        if dist.size == 0:
            return []
        above = np.maximum(heights - self.z_m[point_index], 0.0)
        elevation = np.arctan2(above[None, :], dist)
        best = elevation.argmax(axis=1)
        # 仰角0の方位（何も見えていない）は稜線を作っていない
        hit = elevation.max(axis=1) > 1e-12
        return sorted(set(int(c) for c in best[hit]))


@dataclass
class SkyRatioSummary:
    """最終形状の天空率の判定結果（サマリー・図面用）。"""

    n_points: int
    worst_margin: float          # Ps - Pr の最小値（負なら不適合）
    worst_point: Point | None
    worst_kind: str
    worst_ps: float
    worst_pr: float

    @property
    def ok(self) -> bool:
        return bool(self.worst_margin >= -TOLERANCE_PERCENT)


def summarize(index: SkyIndex, heights: np.ndarray) -> SkyRatioSummary:
    """すべての測定点を評価して、最も余裕のない点を返す。"""
    if not index.points:
        return SkyRatioSummary(0, 0.0, None, "", 0.0, 0.0)
    worst = None
    for i in range(len(index.points)):
        ps = index.ps_at(i, heights)
        margin = ps - index.pr[i]
        if worst is None or margin < worst[0]:
            worst = (margin, i, ps, float(index.pr[i]))
    margin, i, ps, pr = worst
    return SkyRatioSummary(
        n_points=len(index.points), worst_margin=float(margin),
        worst_point=index.points[i], worst_kind=index.kinds[i],
        worst_ps=float(ps), worst_pr=float(pr),
    )


def build_sky_index(
    site: Site,
    area: BuildableArea,
    max_interval_m: float | None = None,
    n_azimuth: int = DEFAULT_N_AZIMUTH,
    references: dict[str, list[Block]] | None = None,
    azimuth_offset_ratio: float = AZIMUTH_OFFSET_RATIO,
) -> SkyIndex:
    """入射距離のインデックスを作り、適合建築物の天空率を求める。"""
    boxes = np.array(
        [list(cell.polygon.bounds) for cell in area.cells], dtype=float
    ).reshape(-1, 4)

    if references is None:
        references = reference_buildings(site)

    samples = measurement_points(site, max_interval_m)
    points = [s.point for s in samples]
    kinds = [s.kind for s in samples]
    edges = [s.edge_index for s in samples]
    z_m = np.array([s.z_m for s in samples], dtype=float)

    # 方位は図面座標（0が+Y方向、時計回り）。sky_ratio.py の取り方に合わせる。
    angles = azimuths_deg(n_azimuth, azimuth_offset_ratio)
    directions = [(math.sin(math.radians(a)), math.cos(math.radians(a))) for a in angles]

    # 規制ごとの適用範囲の外にあるマスは、その規制の測定点からは見ないように
    # する（令135条の6第1項1号の「…が適用される範囲内の部分に限る」）。
    # 距離を inf にすれば仰角0になり、そのマスは天空を塞がない扱いになる。
    # マスが範囲に一部でもかかっていれば含める（多めに見る＝厳しい側）。
    outside: dict[str, np.ndarray] = {}
    for kind in set(kinds):
        region = applicable_region(site, kind)
        if region is None:
            outside[kind] = np.ones(len(area.cells), dtype=bool)
        else:
            outside[kind] = np.array(
                [not cell.polygon.intersects(region) for cell in area.cells],
                dtype=bool)

    distances: list[np.ndarray] = []
    pr = np.zeros(len(points))
    for i, point in enumerate(points):
        origin = np.array(point, dtype=float)
        table = np.full((n_azimuth, len(area.cells)), np.inf)
        if len(area.cells):
            for ai, direction in enumerate(directions):
                table[ai] = _ray_entry_distances(origin, direction, boxes)
            table[:, outside[kinds[i]]] = np.inf
        distances.append(table)
        # Pr は形が変わらないので1回だけ。Ps と同じ方位でサンプリングする。
        # 測定点の種別ごとに違う適合建築物と比べる（令135条の6・7・8）
        pr[i] = sky_ratio_percent(
            (point[0], point[1], float(z_m[i])), references.get(kinds[i], []),
            n_azimuth, azimuth_offset_ratio)

    return SkyIndex(
        points=points, kinds=kinds, edge_indices=edges,
        distances=distances, pr=pr, z_m=z_m,
        n_azimuth=n_azimuth, n_cells=len(area.cells),
        azimuth_offset_ratio=azimuth_offset_ratio,
    )
