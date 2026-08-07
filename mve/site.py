"""敷地モデル（真北・前面道路・緩和対象・壁面後退）.

境界線の種別と、それぞれに付随する条件をここで表現します。斜線制限の
緩和は種別ごとに対象物が違う（下表）ため、緩和対象は「何であるか」を
`RelaxationKind` として持ち、各斜線モジュールが自分に適用できるかを
判断します。

| 緩和対象 | 道路斜線(令134) | 隣地斜線(令135の3) | 北側斜線(令135の4) | 日影(令135の12) |
|---|---|---|---|---|
| 公園・広場 | ○ | ○(都市公園を除く) | **×** | ○ |
| 水面（河川等） | ○ | ○ | ○ | ○ |
| 線路敷 | ― | ○ | ○ | ○ |
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .geometry import Point, dedupe_ring, polygon_area, polygon_signed_area
from .north import NorthReference
from .zoning import ZoningParams


class BoundaryKind(str, Enum):
    ROAD = "road"          # 道路境界線
    ADJACENT = "adjacent"  # 隣地境界線
    NONE = "none"          # 規制の基準にしない辺


class RelaxationKind(str, Enum):
    """境界線の外側にあるものの種類（斜線・日影の緩和対象）。"""

    NONE = "none"
    PARK = "park"          # 公園・広場（都市公園法の都市公園を除く運用が一般的）
    WATER = "water"        # 河川・水路などの水面
    RAILWAY = "railway"    # 線路敷


@dataclass
class Relaxation:
    """境界線の外側にある公園・水面・線路敷など。

    `width_m` はその対象物の幅（境界線から反対側の境界までの距離）。
    道路の場合は道路自体の幅員とは別に、道路の**反対側**にある対象物の
    幅を指します（令134条）。
    """

    kind: RelaxationKind = RelaxationKind.NONE
    width_m: float = 0.0

    def __post_init__(self) -> None:
        if self.kind != RelaxationKind.NONE and self.width_m <= 0:
            raise ValueError("緩和対象を指定する場合は width_m > 0 が必要です")

    @property
    def active(self) -> bool:
        return self.kind != RelaxationKind.NONE and self.width_m > 0


@dataclass
class Boundary:
    """敷地の1辺と、その規制上の役割。

    `p1`→`p2` は敷地ポリゴン（反時計回り）の辺です。

    - `kind` … 道路境界線 / 隣地境界線 / 対象外
    - `road_width_m` … 前面道路の幅員（kind=ROAD のとき必須）
    - `wall_setback_m` … この境界線からの**壁面後退距離**。斜線制限の
      後退緩和（令130条の12 等）と、天空率比較・ボリューム探索の両方で
      使います。0なら緩和を見込みません。
    - `relaxation` … 境界線の外側（道路なら道路の反対側）にある公園・
      水面・線路敷
    - `ground_level_diff_m` … 敷地地盤面が道路面／隣地より低い場合の高低差
      （正の値で「敷地の方が低い」）。1m以上で緩和が効きます
      （令135条の2、令135条の3第2号）。
    """

    p1: Point
    p2: Point
    kind: BoundaryKind = BoundaryKind.NONE
    road_width_m: float = 0.0
    wall_setback_m: float = 0.0
    relaxation: Relaxation = field(default_factory=Relaxation)
    ground_level_diff_m: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        self.kind = BoundaryKind(self.kind)
        if self.kind == BoundaryKind.ROAD and self.road_width_m <= 0:
            raise ValueError("道路境界線には road_width_m > 0 が必要です")
        if self.wall_setback_m < 0:
            raise ValueError("wall_setback_m は0以上である必要があります")

    @property
    def is_road(self) -> bool:
        return self.kind == BoundaryKind.ROAD

    @property
    def length_m(self) -> float:
        return ((self.p2[0] - self.p1[0]) ** 2 + (self.p2[1] - self.p1[1]) ** 2) ** 0.5

    @property
    def midpoint(self) -> Point:
        return ((self.p1[0] + self.p2[0]) / 2, (self.p1[1] + self.p2[1]) / 2)


@dataclass
class Site:
    """敷地。`points` は反時計回り、`edges[i]` は points[i]→points[i+1] の辺。"""

    points: list[Point]
    edges: list[Boundary]
    zoning: ZoningParams
    north: NorthReference = field(default_factory=NorthReference)
    floor_height_m: float = 3.2
    name: str = ""

    def __post_init__(self) -> None:
        self.points = dedupe_ring(self.points)
        if len(self.points) < 3:
            raise ValueError("敷地は3頂点以上必要です")
        if polygon_signed_area(self.points) < 0:
            raise ValueError(
                "敷地の頂点は反時計回りで指定してください"
                "（from_rings() を使うと自動で揃えられます）"
            )
        if len(self.edges) != len(self.points):
            raise ValueError(
                f"辺の数({len(self.edges)})が頂点の数({len(self.points)})と一致しません"
            )
        for i, edge in enumerate(self.edges):
            p1, p2 = self.points[i], self.points[(i + 1) % len(self.points)]
            if not (_same(edge.p1, p1) and _same(edge.p2, p2)):
                raise ValueError(f"edges[{i}] の端点が points[{i}]→points[{i+1}] と一致しません")

    # --- 面積・上限 -------------------------------------------------
    @property
    def area_m2(self) -> float:
        return polygon_area(self.points)

    @property
    def road_edges(self) -> list[Boundary]:
        return [e for e in self.edges if e.is_road]

    @property
    def max_road_width_m(self) -> float:
        """前面道路のうち最大の幅員（法52条2項・令132条で使う）。"""
        return max((e.road_width_m for e in self.road_edges), default=0.0)

    def max_building_area_m2(self) -> float:
        """建蔽率による建築面積の上限。"""
        return self.area_m2 * self.zoning.coverage_ratio

    def max_total_floor_area_m2(self) -> float:
        """容積率による延床面積の上限。

        指定容積率と、前面道路幅員による制限（法52条2項）の小さい方を使います。
        """
        from .far import effective_far_ratio

        return self.area_m2 * effective_far_ratio(self)

    # --- 生成ヘルパ -------------------------------------------------
    @classmethod
    def from_rings(
        cls,
        points: list[Point],
        edge_specs: list[dict],
        zoning: ZoningParams,
        north: NorthReference | None = None,
        floor_height_m: float = 3.2,
        name: str = "",
    ) -> "Site":
        """頂点列と辺の設定（dict）から Site を作る。

        頂点の向きが時計回りでも自動で反時計回りに直し、辺の設定も
        追従させます。手入力やDXF読み込みの結果をそのまま渡せます。
        """
        pts = dedupe_ring(points)
        specs = list(edge_specs)
        if len(specs) != len(pts):
            raise ValueError(f"辺の設定({len(specs)})が頂点の数({len(pts)})と一致しません")
        if polygon_signed_area(pts) < 0:
            # 反転すると「辺i = 点i→点i+1」の対応がずれるので付け替える
            n = len(pts)
            pts = pts[::-1]
            specs = [specs[(n - 2 - i) % n] for i in range(n)]
        edges = []
        for i, spec in enumerate(specs):
            p1, p2 = pts[i], pts[(i + 1) % len(pts)]
            data = dict(spec)
            relax = data.pop("relaxation", None)
            if isinstance(relax, dict):
                relax = Relaxation(
                    kind=RelaxationKind(relax.get("kind", "none")),
                    width_m=float(relax.get("width_m", 0.0)),
                )
            edges.append(Boundary(p1=p1, p2=p2, relaxation=relax or Relaxation(), **data))
        return cls(
            points=pts, edges=edges, zoning=zoning,
            north=north or NorthReference(), floor_height_m=floor_height_m, name=name,
        )


def _same(a: Point, b: Point, tol: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
