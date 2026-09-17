"""単純多角形（穴なし）の耳切り法（ear clipping）三角形分割.

`mesh` バックエンド（`mesh_backend.py`）専用の、外部ライブラリを使わない
最小限の三角形分割です。凹多角形には対応しますが、**穴のある多角形
（内側のリングを持つもの）には対応していません** — 呼び出し側が外周の
座標列だけを渡す前提です。

`shapely` の `shapely.ops.triangulate` を使わない理由は、あれがドロネー
三角形分割であり凹多角形の外形をはみ出す・欠けることがあるためです。
ここでの用途は「見た目のためのポリゴン分割」であって数値計算ではないので、
自前の単純な実装で十分としています。
"""
from __future__ import annotations

Point2 = tuple[float, float]
Triangle = tuple[int, int, int]


def _signed_area_x2(ring: list[Point2]) -> float:
    total = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total


def _is_ccw(ring: list[Point2]) -> bool:
    return _signed_area_x2(ring) > 0.0


def _cross(o: Point2, a: Point2, b: Point2) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _point_in_triangle(p: Point2, a: Point2, b: Point2, c: Point2) -> bool:
    """`p` が三角形 `a,b,c`（向き不問）の内部または辺上にあるか。"""
    d1 = _cross(a, b, p)
    d2 = _cross(b, c, p)
    d3 = _cross(c, a, p)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def triangulate_simple_polygon(ring: list[Point2]) -> list[Triangle]:
    """穴の無い単純多角形を耳切り法で三角形分割する。

    `ring` は最初と最後が重ならない頂点列（`shapely` の
    `polygon.exterior.coords[:-1]` をそのまま渡せます）。向き（CW/CCW）は
    問いません。戻り値は `ring` に対するインデックスの3つ組のリストで、
    頂点数を `n` とすると必ず `n - 2` 個になります（自己交差が無い前提）。
    """
    n = len(ring)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]

    if _is_ccw(ring):
        pts = list(ring)
        index_map = list(range(n))
    else:
        pts = list(reversed(ring))
        index_map = list(range(n - 1, -1, -1))

    indices = list(range(n))
    triangles: list[Triangle] = []
    guard = 0
    max_guard = n * n + 8
    while len(indices) > 3 and guard < max_guard:
        guard += 1
        ear_found = False
        m = len(indices)
        for i in range(m):
            i_prev = indices[(i - 1) % m]
            i_curr = indices[i]
            i_next = indices[(i + 1) % m]
            a, b, c = pts[i_prev], pts[i_curr], pts[i_next]
            if _cross(a, b, c) <= 1e-12:
                continue  # 凹角・共線は耳になれない
            is_ear = True
            for j in indices:
                if j in (i_prev, i_curr, i_next):
                    continue
                if _point_in_triangle(pts[j], a, b, c):
                    is_ear = False
                    break
            if is_ear:
                triangles.append((index_map[i_prev], index_map[i_curr], index_map[i_next]))
                del indices[i]
                ear_found = True
                break
        if not ear_found:
            break  # 数値誤差でどれも耳と判定できない場合、扇形分割で残りを埋める

    if len(indices) >= 3:
        anchor = indices[0]
        for k in range(1, len(indices) - 1):
            triangles.append((
                index_map[anchor], index_map[indices[k]], index_map[indices[k + 1]],
            ))
    return triangles
