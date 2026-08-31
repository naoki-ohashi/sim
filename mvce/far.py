"""容積率の算定（法52条1項・2項、法52条9項＋令135条の18）.

前面道路の幅員が12m未満のときは、指定容積率（都市計画で定めた容積率）と
「前面道路の幅員 × 低減係数」の**小さい方**が上限になります（法52条2項）。

    低減係数: 住居系 4/10、その他 6/10

前面道路が2以上ある場合は、**最大幅員**の道路で判定します。

## 法52条9項（特定道路による緩和）

幅員15m以上の道路（特定道路）に接続する幅員6m以上12m未満の前面道路で、
特定道路からの延長が70m以内の部分に敷地が接している場合、法52条2項の
「幅員」に令135条の18 の数値を加えて読み替えます。

    Ｗａ＝（１２－Ｗｒ）（７０－Ｌ）／７０

      Ｗｒ … 前面道路の幅員
      Ｌ  … 特定道路から、敷地が接する前面道路の部分の直近の端までの延長

**読み替えの範囲は「第二項から第七項まで」に限られます。** 斜線制限
（法56条・令132条・令134条）の幅員は実幅員のままです。混ざらないよう、
容積率側の幅員はこのモジュールの `far_road_width_m()` だけが返します。

**加算後の幅員で「12m未満」を判定します。** 読み替えは2項の「幅員」全部に
かかるので、12m未満の閾値も最大幅員の比較も加算後の値で見ます。L=0 のとき
Ｗａ＝12−Ｗｒ でちょうど12mになり、そこで2項が外れるので不連続はありません。

## 法52条2項各号の括弧書き（特定行政庁が指定する区域）

低減係数は号ごとに括弧書きを持ちます。**変わる向きが号で違います。**

    一号 低層住専・田園住居 …… 4/10（括弧書きなし）
    二号 中高層住専・住居系 …… 4/10（指定区域は 6/10）      → 緩和だけ
    三号 その他             …… 6/10（指定区域は 4/10 又は 8/10）→ 強化もある

三号の 4/10 が要注意で、指定を知らずに既定の 6/10 で計算すると**実際の限度の
1.5倍**を許します。`ZoningParams.far_road_coefficient_designated` で指定でき、
未指定なら `notes` に向き付きの注意書きが出ます。

（法52条8項・10項〜14項は未対応です。該当しそうな場合は `notes` に
注意書きが出ます。）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .zoning import FAR_ROAD_WIDTH_THRESHOLD_M, far_road_paragraph_2_item

#: 法52条9項: 特定道路の幅員の下限
SPECIFIED_ROAD_MIN_WIDTH_M = 15.0
#: 法52条9項: 緩和を受けられる前面道路の幅員の範囲（下限以上・上限未満）
SPECIFIED_ROAD_FRONT_MIN_M = 6.0
SPECIFIED_ROAD_FRONT_MAX_M = 12.0
#: 法52条9項・令135条の18: 特定道路からの延長の上限（式の分母でもある）
SPECIFIED_ROAD_MAX_DISTANCE_M = 70.0


def article_135_18_addition(front_width_m: float, distance_m: float) -> float:
    """令135条の18 の Ｗａ＝（12−Ｗｒ）（70−Ｌ）／70.

    条件判定はしません。適用条件を満たすかどうかは `road_far_width()` が
    見ます。ここは式だけです。
    """
    return (
        (SPECIFIED_ROAD_FRONT_MAX_M - front_width_m)
        * (SPECIFIED_ROAD_MAX_DISTANCE_M - distance_m)
        / SPECIFIED_ROAD_MAX_DISTANCE_M
    )


@dataclass
class RoadFarWidth:
    """法52条2項に使う、1本の前面道路の幅員（法52条9項の読み替え後）。"""

    actual_width_m: float          # 実幅員 Ｗｒ
    addition_m: float              # 令135条の18 の Ｗａ（適用外なら0）
    reason: str = ""               # 特定道路の申告があるのに効かなかった理由

    @property
    def width_m(self) -> float:
        return self.actual_width_m + self.addition_m

    @property
    def relaxed(self) -> bool:
        return self.addition_m > 0.0


def road_far_width(edge) -> RoadFarWidth:
    """1本の前面道路について、法52条2項に使う幅員を求める。

    特定道路（`edge.specified_road`）が申告されていても、条文の3条件
    （特定道路15m以上／前面道路6m以上12m未満／延長70m以内）を満たさなければ
    加算しません。満たさなかったときは `reason` に理由が入ります。
    """
    wr = edge.road_width_m
    spec = edge.specified_road
    if not spec.declared:
        return RoadFarWidth(wr, 0.0)

    if spec.width_m < SPECIFIED_ROAD_MIN_WIDTH_M:
        return RoadFarWidth(wr, 0.0, (
            f"特定道路の幅員が{spec.width_m:.1f}mで15m未満のため、"
            "法52条9項の特定道路にあたりません。"
        ))
    if wr < SPECIFIED_ROAD_FRONT_MIN_M:
        return RoadFarWidth(wr, 0.0, (
            f"前面道路の幅員が{wr:.1f}mで6m未満のため、法52条9項の対象外です。"
        ))
    if wr >= SPECIFIED_ROAD_FRONT_MAX_M:
        return RoadFarWidth(wr, 0.0, (
            f"前面道路の幅員が{wr:.1f}mで12m以上のため、"
            "そもそも法52条2項の低減を受けません。"
        ))
    if spec.distance_m > SPECIFIED_ROAD_MAX_DISTANCE_M:
        return RoadFarWidth(wr, 0.0, (
            f"特定道路からの延長が{spec.distance_m:.1f}mで70mを超えるため、"
            "法52条9項の対象外です。"
        ))

    return RoadFarWidth(wr, article_135_18_addition(wr, spec.distance_m))


def far_road_width_m(site) -> float:
    """法52条2項の「前面道路の幅員」（2以上あるときは最大のもの）。

    法52条9項の読み替えは2項の「幅員」全部にかかるので、**加算後の値で**
    最大を取ります。`site.max_road_width_m`（実幅員）とは別物です。
    """
    return max((road_far_width(e).width_m for e in site.road_edges), default=0.0)


def effective_far_limit(site) -> float:
    """法52条1項・2項・7項・9項による容積率の限度。**別表第三（ろ）欄の値**です。

        別表第三（ろ）欄
        第五十二条第一項、第二項、第七項及び第九項の規定による容積率の限度

    列挙されているのは1項（指定容積率）・2項（前面道路幅員による低減）・
    7項（またがりの按分）・9項（特定道路）で、**3項（地階の不算入）・8項
    （住宅の割増）・10〜14項（許可等）は入っていません**。MVCE が実装して
    いるのはちょうど 1項・2項・7項・9項 なので、この4つで決まる値がそのまま
    （ろ）欄の値になります。

    `compute_far()` と同じ値を返しますが、**説明文（notes）を作りません**。
    道路斜線の適用距離を引くのに点ごとに何万回も呼ばれるためです。
    """
    if site.zone_split is not None and not site.zone_split.is_single:
        return compute_far(site).effective_far
    designated = site.zoning.far_ratio
    width = far_road_width_m(site)
    if width <= 0 or width >= FAR_ROAD_WIDTH_THRESHOLD_M:
        return designated
    return min(designated, width * site.zoning.far_road_coefficient())


@dataclass
class FarResult:
    designated_far: float          # 都市計画で定められた容積率（比）
    road_far: float | None         # 前面道路幅員による上限（比）。12m以上なら None
    effective_far: float           # 実際に適用される容積率（比）
    max_road_width_m: float        # 法52条2項に使った幅員（9項の加算込み）
    coefficient: float | None
    notes: list[str]
    #: 法52条9項の加算が効いた道路（辺の番号 → RoadFarWidth）
    specified_road_additions: dict[int, RoadFarWidth] = field(default_factory=dict)

    @property
    def limited_by_road(self) -> bool:
        return self.road_far is not None and self.road_far < self.designated_far


def _specified_road_notes(site) -> tuple[dict[int, RoadFarWidth], list[str]]:
    """法52条9項の加算とその説明を集める。"""
    additions: dict[int, RoadFarWidth] = {}
    notes: list[str] = []
    for i, edge in enumerate(site.edges):
        if not edge.is_road or not edge.specified_road.declared:
            continue
        w = road_far_width(edge)
        if w.relaxed:
            additions[i] = w
            notes.append(
                f"法52条9項・令135条の18: 辺{i}（幅員{w.actual_width_m:.1f}m）は"
                f"幅員{edge.specified_road.width_m:.1f}mの特定道路から"
                f"{edge.specified_road.distance_m:.1f}mの位置にあるため、"
                f"Wa=(12−{w.actual_width_m:.1f})×(70−"
                f"{edge.specified_road.distance_m:.1f})/70"
                f"={w.addition_m:.2f}m を加算して"
                f"{w.width_m:.2f}mとみなします。"
            )
        elif w.reason:
            notes.append(f"法52条9項: 辺{i}は加算しません。{w.reason}")
    if additions:
        notes.append(
            "この加算は法52条2項〜7項（容積率）だけに効きます。"
            "道路斜線（令132条・令134条）の幅員は実幅員のままです。"
        )
    return additions, notes


def compute_far(site) -> FarResult:
    """敷地に適用される容積率を求める。"""
    if site.zone_split is not None and not site.zone_split.is_single:
        return _compute_far_split(site)

    designated = site.zoning.far_ratio
    additions, notes = _specified_road_notes(site)
    max_width = far_road_width_m(site)

    if max_width <= 0:
        notes.append(
            "前面道路が設定されていません。法52条2項の判定ができないため"
            "指定容積率をそのまま使っています（接道義務の確認も別途必要です）。"
        )
        return FarResult(designated, None, designated, 0.0, None, notes, additions)

    if max_width >= FAR_ROAD_WIDTH_THRESHOLD_M:
        notes.append(
            f"前面道路の最大幅員が{max_width:.1f}mで12m以上のため、"
            "法52条2項による低減はありません。"
        )
        return FarResult(designated, None, designated, max_width, None, notes, additions)

    coefficient = site.zoning.far_road_coefficient()
    road_far = max_width * coefficient
    effective = min(designated, road_far)

    notes.append(
        f"法52条2項: 前面道路の最大幅員{max_width:.1f}m × {coefficient:.1f} "
        f"= {road_far * 100:.0f}%（指定容積率 {designated * 100:.0f}%）"
    )
    if road_far < designated:
        notes.append(
            f"→ 前面道路幅員により容積率が {effective * 100:.0f}% に制限されます。"
        )
    if len(site.road_edges) > 1:
        notes.append(
            f"前面道路が{len(site.road_edges)}本あるため、最大幅員"
            f"{max_width:.1f}mで判定しています。"
        )
    if not additions:
        notes.append(
            "特定道路による緩和（法52条9項）は、特定道路を指定した辺がないため"
            "見ていません。幅員15m以上の道路に接続する前面道路（6m以上12m未満）"
            "に接している敷地では、その辺に特定道路の幅員と延長を入れてください。"
        )
    notes.extend(_designation_notes(site, coefficient))
    notes.append(
        "法52条8項（住宅の割増）・10項〜14項（計画道路・壁面線・許可）は"
        "未対応です。該当する可能性がある場合は別途確認してください。"
    )
    return FarResult(
        designated, road_far, effective, max_width, coefficient, notes, additions,
    )


_ITEM_JA = {1: "一", 2: "二", 3: "三"}


def _designation_notes(site, coefficient: float) -> list[str]:
    """法52条2項各号の括弧書き（指定区域）についての注意書き。

    **向きを正しく言うことが大事です。** 二号（中高層住専・住居系）の指定は
    4/10 → 6/10 の緩和なので、知らずに既定で計算しても厳しい側に出るだけです。
    三号（その他）の指定は 6/10 → **4/10 または 8/10** で、4/10 なら
    既定の 6/10 は実際の限度の1.5倍。**緩い側＝危険**です。
    """
    item = far_road_paragraph_2_item(site.zoning.zone_type)
    if site.zoning.far_road_coefficient_designated is not None:
        return [
            f"法52条2項第{_ITEM_JA[item]}号の指定区域として、"
            f"係数 {coefficient:.1f} を指定されています（括弧書き）。"
        ]
    if item == 1:
        return []           # 一号に括弧書きは無い
    if item == 2:
        return [
            "法52条2項第二号の指定区域（係数が4/10→6/10になる）には該当しない"
            "ものとして計算しています。該当する場合は "
            "far_road_coefficient_designated に 0.6 を指定してください"
            "（容積率が上がります）。"
        ]
    return [
        "⚠ 法52条2項第三号の指定区域（係数が6/10→**4/10 または 8/10**になる）"
        "には該当しないものとして、6/10 で計算しています。"
        "**4/10 の指定区域だと、この結果は実際の限度の1.5倍です。**"
        "都市計画図で確認し、該当する場合は "
        "far_road_coefficient_designated に 0.4 か 0.8 を指定してください。"
    ]


def _compute_far_split(site) -> FarResult:
    """法52条7項: 敷地が容積率の制限の異なる区域の2以上にわたる場合。

    各区域の限度（法52条1項・2項）を面積割合で按分します。前面道路の幅員は
    敷地に1つですが、**乗ずる係数（4/10・6/10）は用途地域ごとに違う**ので、
    区域ごとに `min(指定容積率, 幅員×係数)` を出してから按分します。

    法52条9項（特定道路）の読み替えは「第二項から第七項まで」なので、
    ここで使う幅員も加算後の値です。
    """
    from .zone_split import weighted_far_limit

    split = site.zone_split
    additions, notes = _specified_road_notes(site)
    max_width = far_road_width_m(site)

    effective, split_notes = weighted_far_limit(split, max_width)
    notes.extend(split_notes)

    # 按分後の値は「1項及び2項による限度を按分したもの」そのもので、
    # 指定容積率と道路による低減のどちらか一方ではない。designated には
    # 道路による低減を掛けない側（1項だけ）の按分を入れておく。
    designated = sum(
        p.zoning.far_ratio * p.area_m2 for p in split.parts
    ) / split.total_area_m2
    road_far = effective if effective < designated - 1e-12 else None
    if road_far is not None:
        notes.append(
            f"→ 前面道路幅員（法52条2項）が効いている区域があるため、"
            f"按分後の容積率は {effective * 100:.1f}% です"
            f"（1項だけを按分すると {designated * 100:.1f}%）。"
        )
    if len(site.road_edges) > 1:
        notes.append(
            f"前面道路が{len(site.road_edges)}本あるため、最大幅員"
            f"{max_width:.1f}mで判定しています。"
        )
    notes.append(
        "**斜線制限と日影規制は按分しません。** 隣地・北側は法56条5項が"
        "「建築物」を「建築物の部分」と読み替え、道路は別表第三（い）欄が"
        "「建築物がある地域」ごと、日影は令135条の13 が「各区域内に"
        "それぞれ対象建築物があるものとして適用」と定めています。"
    )
    return FarResult(
        designated, road_far, effective, max_width, None, notes, additions,
    )


def effective_far_ratio(site) -> float:
    return compute_far(site).effective_far
