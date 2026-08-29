"""DXFから敷地図を読み込む.

CADで描いた敷地の外形線をそのまま使えるようにします。読み取り方は2通り。

1. **閉じたポリライン**（LWPOLYLINE / POLYLINE）を敷地とみなす
2. 個々の**線分**（LINE）をつないで閉じた輪郭を組み立てる

境界線の種別（道路／隣地）は、CADの**レイヤ名**または**線色**で指定します。
図面上で描き分けるだけで済むので、座標を打ち直す必要がありません。

    レイヤ名に "道路" / "road" を含む → 道路境界線
    レイヤ名に "隣地" / "adjacent"    → 隣地境界線

単位は既定でメートルです。mmで作図した図面は `units_per_meter=1000` を
指定してください。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import ezdxf

from ..geometry import Point, dedupe_ring, ensure_ccw, polygon_signed_area

DEFAULT_TOLERANCE_M = 0.01  # 10mm: 作図誤差で角がぴったり合わない場合の許容

ROAD_KEYWORDS = ("道路", "road", "ROAD", "Road")
ADJACENT_KEYWORDS = ("隣地", "adjacent", "ADJACENT", "Adjacent", "隣地境界")


class SiteImportError(ValueError):
    """敷地図を読み取れなかった。"""


@dataclass
class ImportedEdge:
    p1: Point
    p2: Point
    layer: str = ""
    color: int = 0
    #: JSON/CSVなど、種別・属性がデータそのものに明示されている場合はここに入れる。
    #: 指定があれば `guess_kind()`/`edge_specs()` はレイヤ名推測より必ずこちらを優先する。
    kind_hint: str | None = None
    road_width_m: float | None = None
    wall_setback_m: float | None = None
    relaxation: dict | None = None
    ground_level_diff_m: float | None = None
    label: str = ""

    @property
    def length(self) -> float:
        return math.hypot(self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])

    def guess_kind(self) -> str:
        """境界線の種別を求める。`kind_hint` があればそれを、無ければレイヤ名から推測する。"""
        if self.kind_hint is not None:
            return self.kind_hint
        name = self.layer or ""
        if any(k in name for k in ROAD_KEYWORDS):
            return "road"
        if any(k in name for k in ADJACENT_KEYWORDS):
            return "adjacent"
        return "none"


@dataclass
class ImportedSitePlan:
    """DXF/JSON/CSVから読み取った敷地の外形。"""

    points: list[Point]
    edges: list[ImportedEdge]
    source_layers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def edge_specs(self, default_road_width_m: float = 6.0,
                   wall_setback_m: float = 0.0) -> list[dict]:
        """`Site.from_rings` に渡せる辺の設定に変換する。

        辺ごとに `road_width_m`/`wall_setback_m` 等が明示されていれば
        それを使い、無ければ引数の既定値にフォールバックする
        （DXFはレイヤ名推測のみなので常にフォールバック側、JSON/CSVは
        辺ごとの値があればそちらを優先）。
        """
        specs = []
        for edge in self.edges:
            kind = edge.guess_kind()
            spec: dict = {
                "kind": kind,
                "wall_setback_m": edge.wall_setback_m if edge.wall_setback_m is not None
                else wall_setback_m,
            }
            if kind == "road":
                spec["road_width_m"] = (
                    edge.road_width_m if edge.road_width_m is not None
                    else default_road_width_m
                )
            if edge.relaxation is not None:
                spec["relaxation"] = edge.relaxation
            if edge.ground_level_diff_m is not None:
                spec["ground_level_diff_m"] = edge.ground_level_diff_m
            if edge.label:
                spec["label"] = edge.label
            specs.append(spec)
        return specs


def _polyline_points(entity, scale: float) -> list[Point]:
    if entity.dxftype() == "LWPOLYLINE":
        return [(x * scale, y * scale) for x, y, *_ in entity.get_points("xy")]
    return [(v.dxf.location.x * scale, v.dxf.location.y * scale) for v in entity.vertices]


def _ring_from_segments(segments: list[ImportedEdge], tolerance: float) -> list[ImportedEdge]:
    """バラバラの線分を端点でつないで、1つの閉じた輪にする。"""
    usable = [s for s in segments if s.length > tolerance]
    if len(usable) < 3:
        raise SiteImportError(
            f"敷地を作るには線分が3本以上必要です（有効な線分: {len(usable)}本）"
        )

    nodes: list[Point] = []

    def node_for(p: Point) -> int:
        for i, q in enumerate(nodes):
            if abs(p[0] - q[0]) <= tolerance and abs(p[1] - q[1]) <= tolerance:
                return i
        nodes.append(p)
        return len(nodes) - 1

    links: dict[int, list[tuple[int, int]]] = {}
    for i, seg in enumerate(usable):
        a, b = node_for(seg.p1), node_for(seg.p2)
        if a == b:
            raise SiteImportError(f"始点と終点が同じ線分があります（{nodes[a]} 付近）")
        links.setdefault(a, []).append((i, b))
        links.setdefault(b, []).append((i, a))

    for node, connected in links.items():
        if len(connected) != 2:
            x, y = nodes[node]
            raise SiteImportError(
                f"座標 ({x:.3f}, {y:.3f}) に線分が{len(connected)}本つながっています。"
                "閉じた敷地にするには各頂点でちょうど2本である必要があります"
                "（余分な線が選択に含まれていないか確認してください）"
            )

    start_edge = 0
    a, b = node_for(usable[start_edge].p1), node_for(usable[start_edge].p2)
    ordered = [usable[start_edge]]
    ordered_nodes = [a]
    used = {start_edge}
    current = b
    while current != a:
        nexts = [(ei, other) for ei, other in links[current] if ei not in used]
        if not nexts:
            raise SiteImportError("敷地の線が閉じていません（途中で行き止まりになりました）")
        edge_index, nxt = nexts[0]
        ordered.append(usable[edge_index])
        ordered_nodes.append(current)
        used.add(edge_index)
        current = nxt

    if len(used) != len(usable):
        raise SiteImportError(
            f"線が複数のまとまりに分かれています"
            f"（1つ目は{len(used)}本、全体は{len(usable)}本）。"
            "敷地の外形線だけを含むDXFにしてください"
        )
    return [(_ordered_edge(e, nodes[n])) for e, n in zip(ordered, ordered_nodes)]


def _ordered_edge(edge: ImportedEdge, start: Point) -> ImportedEdge:
    """線分の向きを、輪をたどる向きに揃える。"""
    if abs(edge.p1[0] - start[0]) < 1e-6 and abs(edge.p1[1] - start[1]) < 1e-6:
        return edge
    return ImportedEdge(p1=edge.p2, p2=edge.p1, layer=edge.layer, color=edge.color)


def read_site_plan(
    path: str,
    layer: str | None = None,
    units_per_meter: float = 1.0,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
) -> ImportedSitePlan:
    """DXFから敷地の外形を読み取る。

    `layer` を指定すると、そのレイヤの図形だけを対象にします。閉じた
    ポリラインがあればそれを優先し、無ければ線分をつなぎます。
    """
    try:
        doc = ezdxf.readfile(path)
    except (OSError, ezdxf.DXFError) as exc:
        raise SiteImportError(f"DXFを読み込めませんでした: {exc}") from exc

    msp = doc.modelspace()
    scale = 1.0 / units_per_meter
    notes: list[str] = []

    def wanted(entity) -> bool:
        return layer is None or entity.dxf.layer == layer

    # 1. 閉じたポリラインを探す
    candidates = []
    for entity in msp:
        if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE") or not wanted(entity):
            continue
        try:
            closed = bool(entity.closed)
        except AttributeError:
            closed = bool(getattr(entity, "is_closed", False))
        pts = dedupe_ring(_polyline_points(entity, scale))
        if closed and len(pts) >= 3:
            candidates.append((abs(polygon_signed_area(pts)), pts, entity.dxf.layer,
                               entity.dxf.color))

    if candidates:
        area, pts, layer_name, color = max(candidates, key=lambda c: c[0])
        if len(candidates) > 1:
            notes.append(
                f"閉じたポリラインが{len(candidates)}個ありました。"
                f"最も面積の大きいもの（{area:.1f} m2、レイヤ「{layer_name}」）を敷地としました。"
            )
        pts = ensure_ccw(pts)
        edges = [
            ImportedEdge(p1=pts[i], p2=pts[(i + 1) % len(pts)], layer=layer_name, color=color)
            for i in range(len(pts))
        ]
        notes.append(
            "閉じたポリラインから読み取りました。境界線の種別はレイヤ名では"
            "分けられないため、すべて同じ扱いになります。辺ごとに種別を"
            "変える場合は線分（LINE）で描き分けてください。"
        )
        return ImportedSitePlan(points=pts, edges=edges,
                                source_layers=[layer_name], notes=notes)

    # 2. 線分をつなぐ
    segments = [
        ImportedEdge(
            p1=(e.dxf.start.x * scale, e.dxf.start.y * scale),
            p2=(e.dxf.end.x * scale, e.dxf.end.y * scale),
            layer=e.dxf.layer, color=e.dxf.color,
        )
        for e in msp if e.dxftype() == "LINE" and wanted(e)
    ]
    if not segments:
        raise SiteImportError(
            "敷地の外形になる図形が見つかりませんでした"
            "（閉じたポリラインか、つながった線分が必要です）"
        )

    ordered = _ring_from_segments(segments, tolerance_m)
    points = dedupe_ring([e.p1 for e in ordered])
    if polygon_signed_area(points) < 0:
        n = len(points)
        points = points[::-1]
        ordered = [
            ImportedEdge(p1=points[i], p2=points[(i + 1) % n],
                         layer=ordered[(n - 2 - i) % n].layer,
                         color=ordered[(n - 2 - i) % n].color)
            for i in range(n)
        ]
    layers = sorted({e.layer for e in ordered})
    notes.append(f"{len(ordered)}本の線分から敷地を組み立てました（レイヤ: {', '.join(layers)}）")
    return ImportedSitePlan(points=points, edges=ordered, source_layers=layers, notes=notes)
