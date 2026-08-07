"""バラバラの線分群から、閉じた敷地ポリゴンを組み立てる.

JWWから受け取る敷地形状は「線分の集まり」でしかなく、順序も向きも
バラバラです（作図した順に並んでいるとは限らず、各線分の始点/終点も
どちら向きに引かれたか分かりません）。ここでは端点を突き合わせて
1本の閉じたリングに並べ替え、同時に「どの線分が元だったか」を保って
線色→境界種別の対応を引き継げるようにします。
"""
from __future__ import annotations

from dataclasses import dataclass

from .geometry import Point, polygon_signed_area
from .jwc import JwcLineSeg

DEFAULT_TOLERANCE_M = 0.01  # 10mm: 作図誤差で端点がぴったり一致しない場合の許容


class RingBuildError(ValueError):
    """線分群が1つの閉じたリングにならなかった。"""


@dataclass
class Ring:
    """閉じた敷地リング。`points[i]` から `points[i+1]` への辺が `segments[i]`。"""

    points: list[Point]
    segments: list[JwcLineSeg]

    def __post_init__(self) -> None:
        if len(self.points) != len(self.segments):
            raise ValueError("points と segments の数が一致していません")

    @property
    def colors(self) -> list[int]:
        return [s.color for s in self.segments]


def _cluster_endpoints(segments: list[JwcLineSeg], tolerance: float) -> tuple[list[Point], list[tuple[int, int]]]:
    """端点を許容誤差でまとめ、各線分を (始点ノード, 終点ノード) で表す。"""
    nodes: list[Point] = []

    def node_for(p: Point) -> int:
        for i, q in enumerate(nodes):
            if abs(p[0] - q[0]) <= tolerance and abs(p[1] - q[1]) <= tolerance:
                return i
        nodes.append(p)
        return len(nodes) - 1

    edges = [(node_for(s.p1), node_for(s.p2)) for s in segments]
    return nodes, edges


def build_ring(segments: list[JwcLineSeg], tolerance: float = DEFAULT_TOLERANCE_M) -> Ring:
    """線分群を1つの閉じたリングに並べ替え、反時計回り(CCW)で返す。

    リングにならない場合（開いている・枝分かれしている・複数リングに
    分かれている等）は `RingBuildError` を投げ、原因が分かるように
    メッセージへ具体的な地点を含めます。
    """
    usable = [s for s in segments if s.length > tolerance]
    if len(usable) < 3:
        raise RingBuildError(
            f"敷地を構成するには線分が3本以上必要です（有効な線分: {len(usable)}本）。"
            "長さ0の線分や重複線が含まれていないか確認してください。"
        )

    nodes, edges = _cluster_endpoints(usable, tolerance)

    adjacency: dict[int, list[tuple[int, int]]] = {}
    for edge_index, (a, b) in enumerate(edges):
        if a == b:
            raise RingBuildError(f"始点と終点が同じ線分があります（座標 {nodes[a]} 付近）。")
        adjacency.setdefault(a, []).append((edge_index, b))
        adjacency.setdefault(b, []).append((edge_index, a))

    for node, links in adjacency.items():
        if len(links) != 2:
            x, y = nodes[node]
            raise RingBuildError(
                f"座標 ({x:.3f}, {y:.3f}) に線分が{len(links)}本つながっています"
                "（閉じた敷地形状にするには、各頂点でちょうど2本である必要があります）。"
                " 線が余分に伸びている・重複している・角が繋がっていない箇所を確認してください。"
            )

    # 1本目の線分から順に端点をたどる
    start_edge = 0
    start_node, current_node = edges[start_edge]
    ordered_points = [nodes[start_node]]
    ordered_segments = [usable[start_edge]]
    used = {start_edge}

    while current_node != start_node:
        nexts = [(ei, other) for ei, other in adjacency[current_node] if ei not in used]
        if not nexts:
            raise RingBuildError(
                "敷地の線が閉じていません（途中で行き止まりになりました）。"
                "角がわずかに離れている場合は許容誤差の調整で解決することがあります。"
            )
        edge_index, next_node = nexts[0]
        ordered_points.append(nodes[current_node])
        ordered_segments.append(usable[edge_index])
        used.add(edge_index)
        current_node = next_node

    if len(used) != len(usable):
        raise RingBuildError(
            f"敷地の線が複数のまとまりに分かれています"
            f"（1つ目のまとまりは{len(used)}本、全体は{len(usable)}本）。"
            "敷地の外形線だけを選択しているか確認してください。"
        )

    if polygon_signed_area(ordered_points) < 0:
        n = len(ordered_points)
        ordered_points.reverse()
        ordered_segments = [ordered_segments[(n - 2 - i) % n] for i in range(n)]

    return Ring(points=ordered_points, segments=ordered_segments)
