"""日影の「しきい値高さ」インデックス.

ボクセル最適化で日影規制を扱うための中核データです。

## 考え方

測定点 P、時刻 t、メッシュのマス C を固定すると、
「C が P に日影を落とすかどうか」は **C の高さだけ**の単調な条件になります。

太陽高度を α、測定面高さを mh とすると、高さ h のマスが落とす影の長さは
(h - mh) / tan(α) です。P から太陽の方向へ伸ばした半直線が C に距離 r で
入るなら、

    C が P を日影にする  ⟺  (h - mh) / tan(α) ≧ r
                        ⟺  h ≧ mh + r・tan(α)

つまり **しきい値高さ** `h_thresh(P, t, C) = mh + r・tan(α)` を先に計算して
おけば、あとは各マスの高さと比較するだけで日影判定ができます。半直線が
C を通らない場合はしきい値を無限大（何m積んでも影を落とさない）とします。

この形にしておく利点は2つあります。

1. 高さを変えるたびに影の多角形を作り直す必要がなく、比較だけで済む。
2. 規制を超えた測定点について「どのマスが効いているか」を正確に特定でき、
   **そのマスだけを下げる**という設計判断ができる。建物全体を一律に
   低くする必要がなくなります。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geometry import Point
from .mesh import BuildableArea
from .regulations.shadow import ShadowRegulationSpec, measurement_points
from .site import Site
from .solar import WINTER_SOLSTICE, day_of_year, solar_declination_deg, solar_position_deg


@dataclass
class ShadowIndex:
    """(測定線, 測定点, 時刻, マス) ごとのしきい値高さ。

    `thresholds[line][point_index]` は形状 (時刻数, マス数) の配列で、
    値はそのマスがその測定点を日影にするために必要な高さ(m)。
    """

    spec: ShadowRegulationSpec
    hours: list[float]
    step_hours: float
    points: dict[float, list[Point]]              # 測定線距離 -> 測定点
    thresholds: dict[float, list[np.ndarray]]     # 測定線距離 -> 点ごとの (時刻, マス)
    n_cells: int
    #: hours[i] における太陽方位角（真北基準・時計回り）。日の出前・日没後は None。
    #: 逆日影（roof_envelope.py）が「最も厳しい方位」を特定するために使う。
    sun_azimuths_deg: list[float | None] = field(default_factory=list)

    def active_hours(self, distance_m: float, point_index: int,
                      heights: np.ndarray) -> np.ndarray:
        """現在の高さ配列で、その測定点を実際に日影にしている時刻のインデックス。"""
        thresh = self.thresholds[distance_m][point_index]
        shadowed = (heights[None, :] >= thresh).any(axis=1)
        return np.where(shadowed)[0]

    def offending_cells(self, distance_m: float, point_index: int, time_index: int,
                        heights: np.ndarray) -> np.ndarray:
        """ある時刻に、その測定点を日影にしているマス。"""
        thresh = self.thresholds[distance_m][point_index][time_index]
        return np.where(heights >= thresh)[0]

    def hours_at(self, distance_m: float, point_index: int, heights: np.ndarray) -> float:
        """現在の高さ配列における、その測定点の日影時間。"""
        thresh = self.thresholds[distance_m][point_index]
        shadowed = (heights[None, :] >= thresh).any(axis=1)
        return float(shadowed.sum()) * self.step_hours

    def worst(self, heights: np.ndarray) -> tuple[float, int, float, float] | None:
        """最も規制を超過している測定点。

        戻り値は (測定線距離, 点インデックス, 日影時間, 超過時間)。
        すべて適合していれば None。
        """
        worst = None
        for distance, points in self.points.items():
            limit = (self.spec.line_5m_max_hours if distance == 5.0
                     else self.spec.line_10m_max_hours)
            for i in range(len(points)):
                hours = self.hours_at(distance, i, heights)
                excess = hours - limit
                if excess > 1e-9 and (worst is None or excess > worst[3]):
                    worst = (distance, i, hours, excess)
        return worst

    def is_compliant(self, heights: np.ndarray) -> bool:
        return self.worst(heights) is None


def _ray_entry_distances(origins: np.ndarray, direction: tuple[float, float],
                         boxes: np.ndarray) -> np.ndarray:
    """半直線が各矩形に入るまでの距離（入らなければ inf）。

    `origins` は (1,2)、`direction` は単位ベクトル、`boxes` は
    (n, 4) の [xmin, ymin, xmax, ymax]。スラブ法で一括計算します。
    """
    ox, oy = float(origins[0]), float(origins[1])
    dx, dy = direction

    def slab(o, d, lo, hi):
        if abs(d) < 1e-12:
            inside = (lo <= o) & (o <= hi)
            return (np.where(inside, -np.inf, np.inf),
                    np.where(inside, np.inf, -np.inf))
        t1 = (lo - o) / d
        t2 = (hi - o) / d
        return np.minimum(t1, t2), np.maximum(t1, t2)

    tx_lo, tx_hi = slab(ox, dx, boxes[:, 0], boxes[:, 2])
    ty_lo, ty_hi = slab(oy, dy, boxes[:, 1], boxes[:, 3])
    t_enter = np.maximum(tx_lo, ty_lo)
    t_exit = np.minimum(tx_hi, ty_hi)

    hit = (t_enter <= t_exit) & (t_exit > 0)
    # 半直線なので負の側は0に切り上げる（測定点が矩形の中にある場合）
    entry = np.where(t_enter > 0, t_enter, 0.0)
    return np.where(hit, entry, np.inf)


def build_shadow_index(
    site: Site, area: BuildableArea, spec: ShadowRegulationSpec
) -> ShadowIndex:
    """しきい値高さのインデックスを作る。"""
    boxes = np.array(
        [list(cell.polygon.bounds) for cell in area.cells], dtype=float
    ).reshape(-1, 4)

    declination = solar_declination_deg(day_of_year(*WINTER_SOLSTICE))
    hours = spec.true_solar_hours()
    step = spec.time_step_minutes / 60.0

    points = {d: measurement_points(site, spec, d) for d in (5.0, 10.0)}
    thresholds: dict[float, list[np.ndarray]] = {}

    # 時刻ごとの (太陽方向ベクトル, tanα) を先に用意する
    sun: list[tuple[tuple[float, float], float]] = []
    sun_azimuths_deg: list[float | None] = []
    for hour in hours:
        altitude, azimuth = solar_position_deg(spec.latitude_deg, declination, hour)
        if altitude <= 0:
            sun.append((None, 0.0))
            sun_azimuths_deg.append(None)
            continue
        sun.append((site.north.vector_for_azimuth(azimuth), math.tan(math.radians(altitude))))
        sun_azimuths_deg.append(azimuth)

    for distance, pts in points.items():
        per_point = []
        for point in pts:
            table = np.full((len(hours), len(area.cells)), np.inf)
            origin = np.array(point, dtype=float)
            for ti, (direction, tan_alt) in enumerate(sun):
                if direction is None or len(area.cells) == 0:
                    continue
                # 測定点から太陽の方向へ半直線を伸ばし、各マスまでの距離を測る
                r = _ray_entry_distances(origin, direction, boxes)
                table[ti] = spec.measurement_height_m + r * tan_alt
            per_point.append(table)
        thresholds[distance] = per_point

    return ShadowIndex(
        spec=spec, hours=hours, step_hours=step, points=points,
        thresholds=thresholds, n_cells=len(area.cells),
        sun_azimuths_deg=sun_azimuths_deg,
    )
