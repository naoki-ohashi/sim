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

from typing import TYPE_CHECKING, Optional, Sequence

from .crs import CrsContext
from .geometry import Point, dedupe_ring, polygon_area, polygon_signed_area
from .north import NorthReference
from .zone_split import ZoneSplit
from .zoning import ZoningParams

if TYPE_CHECKING:   # 循環参照を避ける（height_district が site を読む）
    from .regulations.height_district import HeightDistrict


class BoundaryKind(str, Enum):
    ROAD = "road"          # 道路境界線
    ADJACENT = "adjacent"  # 隣地境界線
    NONE = "none"          # 規制の基準にしない辺


class RelaxationKind(str, Enum):
    """境界線の外側にあるものの種類（斜線・日影の緩和対象）。

    **4つの条文が、それぞれ違うものを列挙しています。** どれが緩和対象に
    なるかは種類だけでなく斜線の種類でも変わるので、種類はここで区別し、
    どれを拾うかは各モジュールの `*_RELAXATION_KINDS` が持ちます。

    | 種類 | 道路（令134） | 隣地（令135の3） | 北側（令135の4） | 日影（令135の12） |
    |---|---|---|---|---|
    | `PARK` 公園・広場 | ○ 全幅 | ○ 幅の1/2 | × | × |
    | `URBAN_PARK` 都市公園 | ○ 全幅 | **× 明文で除外** | × | × |
    | `WATER` 水面 | ○ 全幅 | ○ 幅の1/2 | ○ 幅の1/2 | ○ |
    | `RAILWAY` 線路敷 | × | × 列挙なし | ○ 幅の1/2 | ○ |

    `URBAN_PARK` を分けているのは、令135条の3第1項第1号が
    「公園（**都市公園法施行令第二条第一項第一号に規定する都市公園を除く。**）」
    と明文で除いているからです。道路（令134条）にはこの除外がないので、
    都市公園も道路斜線では緩和対象になります。
    """

    NONE = "none"
    PARK = "park"              # 公園・広場（都市公園以外）
    URBAN_PARK = "urban_park"  # 都市公園法施行令2条1項1号の都市公園
    WATER = "water"            # 河川・水路などの水面
    RAILWAY = "railway"        # 線路敷


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
class SpecifiedRoad:
    """法52条9項の**特定道路**。前面道路がそこに接続しているときに置きます。

        ９　建築物の敷地が、幅員十五メートル以上の道路（以下この項において
        「特定道路」という。）に接続する幅員六メートル以上十二メートル未満の
        前面道路のうち当該特定道路からの延長が七十メートル以内の部分において
        接する場合における当該建築物に対する第二項から第七項までの規定の
        適用については、第二項中「幅員」とあるのは、「幅員（…その幅員に、
        当該特定道路から当該建築物の敷地が接する当該前面道路の部分までの
        延長に応じて政令で定める数値を加えたもの）」とする。

    加算値は令135条の18 の `Wa＝（12−Wr）（70−L）／70`。

    - `width_m` … 特定道路自体の幅員。**15m以上**でないと適用されません。
      条件を engine 側で確かめるために必須にしています（利用者が
      「特定道路がある」と申告しただけでは適用しません）。
    - `distance_m` … 令135条の18 の **L**。特定道路から、敷地が接している
      前面道路の部分の**直近の端**までの延長。**70m以内**でないと適用外。

    **敷地ポリゴンからは導けない情報です。** 特定道路がどこにあるかは
    敷地の外の話なので、都市計画図・道路台帳で調べて入れてください。
    """

    width_m: float = 0.0
    distance_m: float = 0.0

    def __post_init__(self) -> None:
        if self.width_m < 0:
            raise ValueError("特定道路の width_m は0以上である必要があります")
        if self.distance_m < 0:
            raise ValueError("特定道路までの distance_m は0以上である必要があります")
        if self.distance_m > 0 and self.width_m <= 0:
            raise ValueError(
                "特定道路の distance_m を指定する場合は width_m（特定道路の幅員）も"
                "必要です。15m以上かどうかを確かめられないため既定値では補いません。"
            )

    @property
    def declared(self) -> bool:
        """利用者が特定道路を申告しているか（条件を満たすかは別問題）。"""
        return self.width_m > 0


@dataclass
class ShadowGroundRelaxation:
    """日影規制の高低差緩和（令135条の12第3項第2号・第4項）。

        三　法第五十六条の二第三項の規定による同条第一項本文の規定の適用の
        緩和に関する措置は、次の各号に定めるところによる。
        二　建築物の敷地の平均地盤面が隣地又はこれに連接する土地で日影の
        生ずるものの地盤面（隣地又はこれに連接する土地に建築物がない場合に
        おいては、当該隣地又はこれに連接する土地の平均地表面をいう。）より
        一メートル以上低い場合においては、その建築物の敷地の平均地盤面は、
        当該高低差から一メートルを減じたものの二分の一だけ高い位置に
        あるものとみなす。

    敷地の平均地盤面が高い位置にあるとみなされると、そこから測る測定面
    （1.5m / 4m / 6.5m）も上がるので、日影が短くなります。

    - `neighbour_level_m` … 隣地または連接する土地で日影の生ずるものの
      地盤面（建築物が無ければ平均地表面）。`ground_levels` と同じ基準の
      標高です。`None` なら緩和を見込みません（保守側）。

      **複数の隣地で高さが違うときは一番低いものを入れてください。**
      隣地が低いほど高低差が小さく、緩和も小さくなるので安全側です。

    - `designated_level_m` … 第4項で特定行政庁が規則で定めた平均地盤面の
      位置。定めがあるときだけ入れます。第2号の計算より優先します。

    斜線の高低差緩和（令135条の2・3・4、`Boundary.ground_level_diff_m`）とは
    **別の条文**です。あちらは境界線ごと、こちらは敷地の平均地盤面全体に
    かかります。
    """

    neighbour_level_m: Optional[float] = None
    designated_level_m: Optional[float] = None

    @property
    def active(self) -> bool:
        return self.neighbour_level_m is not None or self.designated_level_m is not None


@dataclass
class Boundary:
    """敷地の1辺と、その規制上の役割。

    `p1`→`p2` は敷地ポリゴン（反時計回り）の辺です。

    - `kind` … 道路境界線 / 隣地境界線 / 対象外
    - `road_width_m` … 前面道路の幅員（kind=ROAD のとき必須）
    - `wall_setback_m` … この境界線からの**壁面後退距離**。斜線制限の
      後退緩和（令130条の12 等）と、天空率比較・ボリューム探索の両方で
      使います。0なら緩和を見込みません。

      **令130条の12 の特例は利用者が控除した値を入れてください。** 条文は
      後退距離の算定で無視できる部分を列挙しています（物置等で軒高2.3m
      以下・床面積5m²以内・道路に面する長さが接道長の1/5以下・道路境界から
      1m以上／ポーチ等で高さ5m以下／道路沿いの高さ2m以下の門塀／隣地境界線
      沿いの門塀／高さ1.2m以下の部分など）。MVCE はこの値をそのまま使うので、
      特例に当たる部分を除いた「実際の最小後退距離」を渡す必要があります。
    - `relaxation` … 境界線の外側（道路なら道路の反対側）にある公園・
      水面・線路敷
    - `specified_road` … 法52条9項の特定道路（この前面道路が幅員15m以上の
      道路に接続しているとき）。**容積率（法52条2項〜7項）にだけ**効き、
      斜線制限（令132条）の幅員は変わりません
    - `ground_level_diff_m` … 辺の外側（道路なら路面、隣地なら隣地の地盤面）が
      敷地の地盤面より何メートル高いか。**符号つき**です。

          正 … 外側が高い（＝敷地が低い）
          負 … 外側が低い（＝敷地が高い）

      **どちら向きで緩和が効くかは斜線の種類で違います。** 同じ「1m以上の
      高低差」でも、条文が見ている向きが逆です。

      | 条文 | 緩和が効く条件 | この値では |
      |---|---|---|
      | 令135条の2（道路） | 敷地が道路より1m以上**高い** | `<= -1.0` |
      | 令135条の3第1項2号（隣地） | 敷地が隣地より1m以上**低い** | `>= 1.0` |
      | 令135条の4第1項2号（北側） | 敷地が北側隣地より1m以上**低い** | `>= 1.0` |

      道路の向きが逆なのは、敷地が道路より高いと、低い路面から測る斜線で
      不利になるからです。そのぶん道路を高い位置にあるものとみなします。
      隣地側は逆で、敷地が低いときに敷地の地盤面を高いものとみなします。

      いずれも緩和量は `(高低差 - 1) / 2` です。
    """

    p1: Point
    p2: Point
    kind: BoundaryKind = BoundaryKind.NONE
    road_width_m: float = 0.0
    wall_setback_m: float = 0.0
    relaxation: Relaxation = field(default_factory=Relaxation)
    specified_road: SpecifiedRoad = field(default_factory=SpecifiedRoad)
    ground_level_diff_m: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        self.kind = BoundaryKind(self.kind)
        if self.kind == BoundaryKind.ROAD and self.road_width_m <= 0:
            raise ValueError("道路境界線には road_width_m > 0 が必要です")
        if self.wall_setback_m < 0:
            raise ValueError("wall_setback_m は0以上である必要があります")
        if self.specified_road.declared and self.kind != BoundaryKind.ROAD:
            raise ValueError(
                "specified_road（法52条9項）は道路境界線にだけ指定できます"
            )

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
    #: 隣地斜線で線路敷を緩和対象に含めるか。令135条の3第1項1号は
    #: 「公園（都市公園を除く）、広場、水面その他これらに類するもの」で、
    #: 線路敷を列挙していません。含める運用の行政庁に合わせるときだけ True。
    railway_is_adjacent_relaxation: bool = False

    #: 令134条2項を使うか。前面道路が2以上あり、そのうちの1つの反対側に
    #: 公園・広場・水面等がある場合に、令132条1項によらずその道路を基準に
    #: 全前面道路をみなす規定です。条文が「よることができる」としている
    #: **選択規定**なので、明示的に True にしたときだけ適用します。
    #: 既定の False は令132条1項によるということで、保守側です。
    apply_article_134_2: bool = False

    #: 高度地区（法58条）。内容は都市計画で決まるので、すべて入力です。
    #: **天空率（法56条7項）では緩和されません。**
    height_district: Optional["HeightDistrict"] = None

    #: 日影規制の高低差緩和（令135条の12第3項第2号・第4項）。
    #: 既定は緩和なし。斜線の高低差緩和とは別の条文です。
    shadow_ground: ShadowGroundRelaxation = field(default_factory=ShadowGroundRelaxation)

    #: 敷地が用途地域の2以上にわたる場合の区分（法52条7項・法53条2項）。
    #: `None` なら `zoning` 1つ。容積率・建蔽率はここから面積按分します。
    #: **斜線・日影は按分しません**（法56条5項・令135条の13）。用途地域が
    #: 2以上あるとそれらは `UndeterminedRegulation` で止まります。
    zone_split: Optional["ZoneSplit"] = None

    #: 敷地の各頂点の地盤の高さ（GL, m）。`points` と同じ数・同じ順。
    #: `None` なら地盤の情報が無い＝平坦（Z=0）として扱います。
    #: 令2条2項の平均地盤面はここから求めます（`ground_contour()`）。
    ground_levels: Optional[tuple[float, ...]] = None

    #: JGD2011 平面直角座標系の文脈（GIS 由来の敷地のみ）。`crs.py` 参照。
    #: `points` は常にローカル系（x=東, y=北, メートル）で、ここには
    #: 「どの系のどこを原点にしたか」だけが入ります。手描き図面から
    #: 起こした敷地では None のままで、その場合は子午線収差角の補正が
    #: 効かないので真北は人が与える必要があります。
    crs: Optional[CrsContext] = None

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
        if self.zone_split is not None:
            self.zone_split.check_total_area(polygon_area(self.points))
            if self.zoning.zone_type not in self.zone_split.zone_types:
                raise ValueError(
                    f"zoning.zone_type={self.zoning.zone_type!r} が zone_split の"
                    f"どの区域にもありません（区分: {self.zone_split.zone_types}）"
                )
        if self.ground_levels is not None:
            self.ground_levels = tuple(float(z) for z in self.ground_levels)
            if len(self.ground_levels) != len(self.points):
                raise ValueError(
                    f"ground_levels の数({len(self.ground_levels)})が"
                    f"頂点の数({len(self.points)})と一致しません"
                )

    # --- 地盤 -------------------------------------------------------
    def ground_contour(self) -> list:
        """敷地境界線を接地線とみなした `ContactPoint` の並び。

        **令2条2項が測るのは「建築物が周囲の地面と接する位置」です。**
        敷地境界線ではありません。これは「建物が敷地境界いっぱいに建つ」と
        置いたときの接地線で、壁面後退を取る計画では実際の接地線と違います。
        実際の輪郭が決まっているなら、その輪郭で `ContactPoint` を作って
        `ground.ground_plane()` に渡してください。

        `ground_levels` が無いときは平坦（すべて0）として返します。
        """
        from .ground import ContactPoint

        levels = self.ground_levels or (0.0,) * len(self.points)
        return [ContactPoint(p, z) for p, z in zip(self.points, levels)]

    def ground_plane(self, **kwargs):
        """敷地境界線を接地線とした令2条2項の地盤面。

        地盤の情報が無ければ Z=0 の平坦地。高低差が3mを超えると
        `UndeterminedRegulation`（区分の切り方が条文に無いため）。
        接地線の取り方の注意は `ground_contour()` の docstring を参照。
        """
        from .ground import flat_ground_plane, ground_plane

        if self.ground_levels is None:
            return flat_ground_plane(0.0)
        return ground_plane(self.ground_contour(), closed=True, **kwargs)

    # --- 面積・上限 -------------------------------------------------
    @property
    def area_m2(self) -> float:
        return polygon_area(self.points)

    @property
    def road_edges(self) -> list[Boundary]:
        return [e for e in self.edges if e.is_road]

    @property
    def max_road_width_m(self) -> float:
        """前面道路のうち最大の**実**幅員（令132条・令134条で使う）。

        **法52条9項（特定道路）の加算は入っていません。** あの読み替えは
        「第二項から第七項までの規定の適用については」と範囲が限られていて、
        斜線制限（法56条・令132条）には及びません。容積率側の幅員は
        `far.far_road_width_m()` を使ってください。
        """
        return max((e.road_width_m for e in self.road_edges), default=0.0)

    def max_building_area_m2(self) -> float:
        """建蔽率による建築面積の上限。

        敷地が用途地域の2以上にわたるときは法53条2項で面積按分します。
        """
        return self.area_m2 * self.coverage_ratio_limit()

    def coverage_ratio_limit(self) -> float:
        """適用される建蔽率（法53条1項、またがりは法53条2項）。"""
        from .zone_split import weighted_coverage_limit

        if self.zone_split is None:
            return self.zoning.coverage_ratio
        return weighted_coverage_limit(self.zone_split)[0]

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
        crs: Optional[CrsContext] = None,
        apply_article_134_2: bool = False,
        railway_is_adjacent_relaxation: bool = False,
        ground_levels: Optional[Sequence[float]] = None,
        zone_split: Optional[ZoneSplit] = None,
        shadow_ground: Optional[ShadowGroundRelaxation] = None,
        height_district: Optional["HeightDistrict"] = None,
    ) -> "Site":
        """頂点列と辺の設定（dict）から Site を作る。

        頂点の向きが時計回りでも自動で反時計回りに直し、辺の設定も
        追従させます。手入力やDXF読み込みの結果をそのまま渡せます。
        """
        pts = dedupe_ring(points)
        specs = list(edge_specs)
        levels = list(ground_levels) if ground_levels is not None else None
        if levels is not None and len(levels) != len(pts):
            raise ValueError(
                f"ground_levels の数({len(levels)})が頂点の数({len(pts)})と一致しません"
            )
        if len(specs) != len(pts):
            raise ValueError(f"辺の設定({len(specs)})が頂点の数({len(pts)})と一致しません")
        if polygon_signed_area(pts) < 0:
            # 反転すると「辺i = 点i→点i+1」の対応がずれるので付け替える
            n = len(pts)
            pts = pts[::-1]
            specs = [specs[(n - 2 - i) % n] for i in range(n)]
            if levels is not None:
                levels = levels[::-1]
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
            spec_road = data.pop("specified_road", None)
            if isinstance(spec_road, dict):
                spec_road = SpecifiedRoad(
                    width_m=float(spec_road.get("width_m", 0.0)),
                    distance_m=float(spec_road.get("distance_m", 0.0)),
                )
            edges.append(Boundary(
                p1=p1, p2=p2,
                relaxation=relax or Relaxation(),
                specified_road=spec_road or SpecifiedRoad(),
                **data,
            ))
        return cls(
            points=pts, edges=edges, zoning=zoning,
            north=north or NorthReference(), floor_height_m=floor_height_m, name=name,
            crs=crs, apply_article_134_2=apply_article_134_2,
            railway_is_adjacent_relaxation=railway_is_adjacent_relaxation,
            ground_levels=tuple(levels) if levels is not None else None,
            zone_split=zone_split,
            shadow_ground=shadow_ground or ShadowGroundRelaxation(),
            height_district=height_district,
        )


def _same(a: Point, b: Point, tol: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
