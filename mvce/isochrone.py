"""等時間日影図（等時間日影線）.

冬至日の日影時間が等しい点を結んだ等高線（2時間線・3時間線など）を作ります。
5m/10m測定線（`regulations/shadow.py`）は敷地境界からの2本の等距離線上の
判定に限られますが、こちらは敷地の全面にグリッドを敷いて任意の等高線を
求めます。

外部ライブラリ（scipy/skimage等）は使わず、マーチングスクエア法を
numpyだけで実装しています（JS版が外部ライブラリ完全不使用という方針、
および既存の依存関係を増やさない方針との整合のためです）。

## 手順

1. 敷地の外側に、建物高さと冬至の最低太陽高度から見積もった余白を
   取ったグリッドを敷く（`_default_grid_margin_m`）。
2. 各グリッド点の日影時間を求める（`shadow_index.grid_shadow_hours`）。
3. マーチングスクエア法で、指定した時間（レベル）ごとの等高線を抽出する
   （`compute_isochrones`）。

精度と計算時間はグリッド間隔のトレードオフです。既定は2.0mですが、
敷地が広い・建物が高いほどグリッド点数が増えるため、計算に時間が
かかる場合は間隔を広げてください。
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .geometry import Point
from .mesh import BuildableArea
from .regulations.shadow import ShadowRegulationSpec
from .shadow_index import grid_shadow_hours
from .site import Site
from .solar import solar_position_deg, winter_solstice_declination_deg

#: 太陽高度が求まらない場合のフォールバック余白(m)
_FALLBACK_MARGIN_M = 10.0

# マーチングスクエア法のケース→つなぐ辺のペア。
# 辺番号: 0=下(BL-BR) 1=右(BR-TR) 2=上(TR-TL) 3=左(TL-BL)
# ケース番号のビット: bit0=BL bit1=BR bit2=TR bit3=TL（各値がlevel以上なら1）
_CASE_EDGES: dict[int, list[tuple[int, int]] | str] = {
    0: [], 15: [],
    1: [(3, 0)], 14: [(3, 0)],
    2: [(0, 1)], 13: [(0, 1)],
    3: [(1, 3)], 12: [(1, 3)],
    4: [(1, 2)], 11: [(1, 2)],
    6: [(0, 2)], 9: [(0, 2)],
    7: [(2, 3)], 8: [(2, 3)],
    5: "saddle",   # BL,TR が level以上（BR,TLは未満）
    10: "saddle",  # BR,TL が level以上（BL,TRは未満）
}


def _default_grid_margin_m(spec: ShadowRegulationSpec, max_height_m: float) -> float:
    """建物高さと冬至の最低太陽高度から、影が届きうる最大水平距離を見積もる。

    等時間日影図のグリッドが敷地の外側にどれだけ広がっている必要が
    あるかの既定値です。低い太陽高度ほど影が長く伸びるため、規制の
    対象時間帯（`spec.true_solar_hours()`）のうち最も低い太陽高度を使います。
    """
    declination = winter_solstice_declination_deg()
    min_altitude: float | None = None
    for hour in spec.true_solar_hours():
        altitude, _azimuth = solar_position_deg(spec.latitude_deg, declination, hour)
        if altitude > 0 and (min_altitude is None or altitude < min_altitude):
            min_altitude = altitude

    effective_height = max_height_m - spec.measurement_height_m
    if min_altitude is None or effective_height <= 0:
        return _FALLBACK_MARGIN_M
    return effective_height / math.tan(math.radians(min_altitude))


def _round_point(p: Point, ndigits: int = 6) -> Point:
    return (round(p[0], ndigits), round(p[1], ndigits))


def _segments_to_polylines(
    segments: list[tuple[Point, Point]],
) -> list[tuple[list[Point], bool]]:
    """線分の集まりを、端点でつないだポリラインにまとめる。

    戻り値は (ポリライン, 閉曲線か) のリスト。グリッドの端で切れた線は
    開いたポリライン、敷地の中で完結する等高線は閉じたポリラインになる。
    """
    point_segs: dict[Point, list[int]] = defaultdict(list)
    for idx, (a, b) in enumerate(segments):
        point_segs[a].append(idx)
        point_segs[b].append(idx)

    visited = [False] * len(segments)

    def other_point(seg_idx: int, p: Point) -> Point:
        a, b = segments[seg_idx]
        return b if p == a else a

    def walk(start_point: Point, start_seg: int) -> list[Point]:
        chain = [start_point]
        cur_point, cur_seg = start_point, start_seg
        while True:
            visited[cur_seg] = True
            nxt = other_point(cur_seg, cur_point)
            chain.append(nxt)
            candidates = [s for s in point_segs[nxt] if not visited[s]]
            if not candidates:
                return chain
            cur_seg = candidates[0]
            cur_point = nxt

    polylines: list[tuple[list[Point], bool]] = []

    # 開いた線（端点=次数1の点）から先にたどる
    for point, segs in list(point_segs.items()):
        unvisited = [s for s in segs if not visited[s]]
        if len(segs) == 1 and len(unvisited) == 1:
            chain = walk(point, unvisited[0])
            polylines.append((chain, False))

    # 残りは閉じた等高線
    for idx in range(len(segments)):
        if not visited[idx]:
            a, _b = segments[idx]
            chain = walk(a, idx)
            if len(chain) > 1 and chain[-1] == chain[0]:
                chain = chain[:-1]  # close=True で描くので重複する終点は落とす
            polylines.append((chain, True))

    return polylines


def compute_isochrones(
    grid_x: np.ndarray, grid_y: np.ndarray, values: np.ndarray, levels: list[float],
) -> dict[float, list[tuple[list[Point], bool]]]:
    """マーチングスクエア法で等高線を抽出する。

    `values[j, i]` は座標 `(grid_x[i], grid_y[j])` の値。戻り値は level ごとに
    `(ポリライン, 閉曲線か)` のリスト。
    """
    nx, ny = len(grid_x), len(grid_y)
    result: dict[float, list[tuple[list[Point], bool]]] = {}

    for level in levels:
        segments: list[tuple[Point, Point]] = []
        for j in range(ny - 1):
            y0, y1 = float(grid_y[j]), float(grid_y[j + 1])
            for i in range(nx - 1):
                x0, x1 = float(grid_x[i]), float(grid_x[i + 1])
                v_bl, v_br = values[j, i], values[j, i + 1]
                v_tr, v_tl = values[j + 1, i + 1], values[j + 1, i]

                case = (int(v_bl >= level) | (int(v_br >= level) << 1)
                        | (int(v_tr >= level) << 2) | (int(v_tl >= level) << 3))
                if case in (0, 15):
                    continue

                def interp(v_a: float, v_b: float, pa: Point, pb: Point) -> Point:
                    t = 0.5 if v_a == v_b else (level - v_a) / (v_b - v_a)
                    t = min(1.0, max(0.0, t))
                    return (pa[0] + t * (pb[0] - pa[0]), pa[1] + t * (pb[1] - pa[1]))

                edge_points = {
                    0: lambda: interp(v_bl, v_br, (x0, y0), (x1, y0)),
                    1: lambda: interp(v_br, v_tr, (x1, y0), (x1, y1)),
                    2: lambda: interp(v_tr, v_tl, (x1, y1), (x0, y1)),
                    3: lambda: interp(v_tl, v_bl, (x0, y1), (x0, y0)),
                }

                pairs = _CASE_EDGES[case]
                if pairs == "saddle":
                    center = (v_bl + v_br + v_tr + v_tl) / 4.0
                    if case == 5:
                        pairs = [(3, 0), (1, 2)] if center < level else [(0, 1), (2, 3)]
                    else:  # case 10
                        pairs = [(0, 3), (1, 2)] if center < level else [(0, 1), (2, 3)]

                for a, b in pairs:
                    pa = _round_point(edge_points[a]())
                    pb = _round_point(edge_points[b]())
                    if pa != pb:
                        segments.append((pa, pb))

        result[level] = _segments_to_polylines(segments)

    return result


def site_isochrones(
    site: Site, area: BuildableArea, floors: np.ndarray, spec: ShadowRegulationSpec,
    levels: list[float], interval_m: float = 2.0, margin_m: float | None = None,
) -> dict[float, list[tuple[list[Point], bool]]]:
    """`grid_shadow_hours` + `compute_isochrones` をまとめた入口。"""
    if not levels or area is None or len(area.cells) == 0:
        return {level: [] for level in levels}

    heights = np.asarray(floors, dtype=float) * site.floor_height_m
    max_height = float(heights.max()) if heights.size else 0.0
    margin = margin_m if margin_m is not None else _default_grid_margin_m(spec, max_height)

    xs = [p[0] for p in site.points]
    ys = [p[1] for p in site.points]
    x_min, x_max = min(xs) - margin, max(xs) + margin
    y_min, y_max = min(ys) - margin, max(ys) + margin

    nx = max(2, math.ceil((x_max - x_min) / interval_m) + 1)
    ny = max(2, math.ceil((y_max - y_min) / interval_m) + 1)
    grid_x = np.linspace(x_min, x_max, nx)
    grid_y = np.linspace(y_min, y_max, ny)

    grid_points = [(float(x), float(y)) for y in grid_y for x in grid_x]
    hours_flat = grid_shadow_hours(site, area, floors, spec, grid_points)
    values = hours_flat.reshape(ny, nx)

    return compute_isochrones(grid_x, grid_y, values, levels)
