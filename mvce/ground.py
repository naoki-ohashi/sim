"""平均地盤面の算定（令2条2項）.

    第二条
    ２　前項第二号、第六号又は第七号の「地盤面」とは、建築物が周囲の地面と
    接する位置の平均の高さにおける水平面をいい、その接する位置の高低差が
    三メートルを超える場合においては、その高低差三メートル以内ごとの
    平均の高さにおける水平面をいう。

適用先は令2条1項の第二号（建築面積）・第六号（建築物の高さ）・第七号
（軒の高さ）です。**床面積・延べ面積には出てきません。**

## 「敷地の地面」ではなく「建築物が接する位置」

条文は「**建築物が**周囲の地面と接する位置」です。敷地の地面の平均では
ありません。同じ敷地でも建物の置き方で地盤面が変わります。

MVCE のボリューム探索は建物の輪郭を後から決めるので、地盤面を求めるには
「どの輪郭で接するか」を呼び出し側が渡す必要があります。このモジュールは
**接地線（`ContactPoint` の並び）を受け取るだけ**にして、どの輪郭を使うかは
呼び出し側の判断にしています。敷地境界いっぱいに建つ前提でよければ
`Site.ground_contour()` がそれを返します。

## 条文が決めていない2点

### 1. 「平均の高さ」の取り方 — 接地線に沿った長さ加重平均を既定にしました

条文は「平均の高さ」としか書いていません。頂点の単純平均か、接地線の
長さで重み付けした平均かで答えが変わります。

実務では接地線に沿った長さ加重平均（＝接地部分の立面の断面積 ÷ 接地長）を
使うので、これを既定にしました。**条文の文言そのものではなく解釈です。**
`weighted=False` で頂点の単純平均に切り替えられます。将来
`ComplianceProfile` から差し替えられるよう、定数ではなく引数にしています。

長さ加重平均は、辺ごとに地面の高さが直線的に変わるとみて

    ∫z ds / ∫ds = Σ(辺の長さ × 両端の高さの平均) / Σ(辺の長さ)

で厳密に出ます（台形則と一致）。

### 2. 高低差が3mを超えるときの区分の切り方 — `UNDETERMINED` で止めます

条文は「その高低差三メートル以内ごとの平均の高さ」としか書いておらず、
**どこで切るかを指定していません**。標高で切るのか、建物を平面的に区切る
のかも書き分けられていません（令135条の7第3項の「高低差区分区域」は
「敷地を区分した区域」と平面的な区分を明示していて、書きぶりが違います）。

切り方で答えが変わるので、既定値では埋めません。高低差が3mを超える接地線を
そのまま渡すと `UndeterminedRegulation` で止まります。呼び出し側が区分を
決めたうえで、

- `split_by_elevation(contour, cuts)` … 標高で切る読み方
- `ground_planes(sections)` … 平面的に切った接地線を直接渡す

のどちらかで渡してください。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .geometry import Point
from .zoning import UndeterminedRegulation

#: 令2条2項: これを「超える」と地盤面を分ける
GROUND_PLANE_BAND_M = 3.0

_EPS = 1e-9


@dataclass(frozen=True)
class ContactPoint:
    """建築物が周囲の地面と接する位置の1点。

    - `point` … 平面座標 (x, y)。単位m
    - `level_m` … その位置の地面の高さ（GL）。Z=0 を基準にした符号つき
    """

    point: Point
    level_m: float


@dataclass(frozen=True)
class GroundPlane:
    """令2条2項の「地盤面」1つ。"""

    level_m: float          # 平均の高さ（この水平面が地盤面）
    contact_length_m: float  # この地盤面が受け持つ接地線の長さ
    lowest_m: float          # 受け持つ範囲の地面の高さの最低
    highest_m: float         # 同じく最高
    label: str = ""

    @property
    def span_m(self) -> float:
        """受け持つ範囲の高低差。令2条2項の3m判定に使う値。"""
        return self.highest_m - self.lowest_m


@dataclass(frozen=True)
class GroundPlaneSet:
    """令2条2項の算定結果。

    `kind`:
      - `flat`   … 接地位置に高低差が無い（平坦地）
      - `single` … 高低差はあるが3m以内。地盤面は1つ
      - `multi`  … 3mを超えるので分けた。地盤面が複数
    """

    kind: str
    planes: tuple[GroundPlane, ...]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.planes:
            raise ValueError("地盤面が1つもありません")
        if self.kind not in ("flat", "single", "multi"):
            raise ValueError(f"不明な kind: {self.kind!r}")
        if self.kind != "multi" and len(self.planes) != 1:
            raise ValueError(f"kind={self.kind} なのに地盤面が{len(self.planes)}個あります")

    @property
    def level_m(self) -> float:
        """地盤面が1つのときのその高さ。

        `multi` のときは「どの地盤面か」が場所で変わるので、単一の値を
        返すのは誤りです。呼び出し側に判断させるため例外にします。
        """
        if self.kind == "multi":
            raise UndeterminedRegulation(
                "令2条2項により地盤面が複数あります"
                f"（{len(self.planes)}個）。どの地盤面で測るかは部位ごとに"
                "決まるので、単一の値では答えられません。`planes` を見てください。"
            )
        return self.planes[0].level_m

    @property
    def is_flat(self) -> bool:
        return self.kind == "flat"


# === 平均の高さ =======================================================

def _segments(contour: Sequence[ContactPoint], closed: bool):
    n = len(contour)
    last = n if closed else n - 1
    for i in range(last):
        yield contour[i], contour[(i + 1) % n]


def average_ground_level(
    contour: Sequence[ContactPoint],
    *,
    closed: bool = True,
    weighted: bool = True,
) -> float:
    """接地線の「平均の高さ」。

    `weighted=True`（既定）は接地線に沿った長さ加重平均、`False` は頂点の
    単純平均です。どちらを取るかは条文が決めていません（モジュール
    docstring 参照）。
    """
    if not contour:
        raise ValueError("接地線が空です")
    if len(contour) == 1:
        return contour[0].level_m

    if not weighted:
        return sum(c.level_m for c in contour) / len(contour)

    total_len = 0.0
    total = 0.0
    for a, b in _segments(contour, closed):
        length = math.dist(a.point, b.point)
        if length <= _EPS:
            continue
        total_len += length
        total += length * (a.level_m + b.level_m) / 2.0
    if total_len <= _EPS:
        # 全部同じ位置。長さで重み付けできないので単純平均に落とす
        return sum(c.level_m for c in contour) / len(contour)
    return total / total_len


def contact_length_m(contour: Sequence[ContactPoint], *, closed: bool = True) -> float:
    return sum(math.dist(a.point, b.point) for a, b in _segments(contour, closed))


def _span(contour: Sequence[ContactPoint]) -> tuple[float, float]:
    levels = [c.level_m for c in contour]
    return min(levels), max(levels)


# === 地盤面 ===========================================================

def ground_plane(
    contour: Sequence[ContactPoint],
    *,
    closed: bool = True,
    weighted: bool = True,
) -> GroundPlaneSet:
    """接地線から令2条2項の地盤面を求める。

    高低差が3mを**超える**場合は、区分の切り方を条文が決めていないので
    `UndeterminedRegulation` を送出します。区分を決めたうえで
    `split_by_elevation()` か `ground_planes()` を使ってください。
    """
    if not contour:
        raise ValueError("接地線が空です")
    low, high = _span(contour)
    span = high - low

    if span > GROUND_PLANE_BAND_M + _EPS:
        raise UndeterminedRegulation(
            f"建築物が地面と接する位置の高低差が{span:.2f}mで3mを超えます。"
            "令2条2項により地盤面を「高低差三メートル以内ごと」に分ける必要が"
            "ありますが、条文はどこで切るかを定めていません。"
            "split_by_elevation() で標高の切り位置を与えるか、"
            "ground_planes() に区分済みの接地線を渡してください。"
        )

    level = average_ground_level(contour, closed=closed, weighted=weighted)
    plane = GroundPlane(
        level_m=level,
        contact_length_m=contact_length_m(contour, closed=closed),
        lowest_m=low,
        highest_m=high,
    )
    flat = span <= _EPS
    notes = [
        f"令2条2項: 建築物が地面と接する位置の平均の高さ {level:.3f}m を"
        "地盤面としました。"
    ]
    if flat:
        notes.append("接地位置に高低差がありません（平坦地）。")
    else:
        notes.append(
            f"接地位置の高低差は{span:.2f}mで3m以内なので、地盤面は1つです。"
        )
        notes.append(
            "「平均の高さ」は接地線に沿った長さ加重平均で取りました"
            if weighted else
            "「平均の高さ」は接地位置の単純平均で取りました"
        )
        notes.append(
            "（条文は「平均の高さ」としか定めておらず、取り方は解釈です）"
        )
    return GroundPlaneSet("flat" if flat else "single", (plane,), tuple(notes))


def ground_planes(
    sections: Sequence[Sequence[ContactPoint]],
    *,
    closed: bool = False,
    weighted: bool = True,
    labels: Sequence[str] | None = None,
) -> GroundPlaneSet:
    """区分済みの接地線から地盤面を作る（令2条2項の後段）。

    区分は呼び出し側の判断です。各区分の高低差が3mを超えていたら、
    区分として成立していないので弾きます。

    `closed` の既定が `False` なのは、区分された接地線は普通は開いた
    折れ線だからです。
    """
    if not sections:
        raise ValueError("区分が1つもありません")
    if labels is not None and len(labels) != len(sections):
        raise ValueError("labels の数が区分の数と一致しません")

    planes = []
    for i, section in enumerate(sections):
        if not section:
            raise ValueError(f"区分{i}の接地線が空です")
        low, high = _span(section)
        if high - low > GROUND_PLANE_BAND_M + _EPS:
            raise ValueError(
                f"区分{i}の高低差が{high - low:.2f}mで3mを超えています。"
                "令2条2項は「高低差三メートル以内ごと」なので、"
                "この区分では条文を満たしません。"
            )
        planes.append(GroundPlane(
            level_m=average_ground_level(section, closed=closed, weighted=weighted),
            contact_length_m=contact_length_m(section, closed=closed),
            lowest_m=low, highest_m=high,
            label=labels[i] if labels else f"区分{i + 1}",
        ))

    if len(planes) == 1:
        p = planes[0]
        kind = "flat" if p.span_m <= _EPS else "single"
        return GroundPlaneSet(kind, (planes[0],), (
            f"令2条2項: 平均の高さ {p.level_m:.3f}m を地盤面としました。",
        ))

    notes = [
        f"令2条2項: 接地位置の高低差が3mを超えるため、地盤面を"
        f"{len(planes)}つに分けました。",
        "区分の切り方は条文が定めていないため、呼び出し側から受け取った"
        "区分をそのまま使っています。",
    ]
    notes.extend(
        f"  {p.label}: 平均 {p.level_m:.3f}m"
        f"（範囲 {p.lowest_m:.2f}〜{p.highest_m:.2f}m、接地長 {p.contact_length_m:.2f}m）"
        for p in planes
    )
    return GroundPlaneSet("multi", tuple(planes), tuple(notes))


def split_by_elevation(
    contour: Sequence[ContactPoint],
    cuts: Sequence[float],
) -> list[list[ContactPoint]]:
    """接地線を標高で区分する（令2条2項後段の読み方の1つ）。

    `cuts` は区切りの標高。`[low, cuts..., high]` の各区間に接地点を
    振り分けます。標高が区切りにちょうど乗る点は**下の区間**に入れます。

    **これは条文が指定した切り方ではありません。** 「高低差三メートル
    以内ごと」を標高で切る読み方の実装です。建物を平面的に区切る読み方を
    取るなら `ground_planes()` に区分済みの接地線を直接渡してください。
    """
    if not contour:
        raise ValueError("接地線が空です")
    low, high = _span(contour)
    ordered = sorted(cuts)
    for c in ordered:
        if not (low - _EPS <= c <= high + _EPS):
            raise ValueError(
                f"切り位置 {c} が接地位置の高さの範囲（{low}〜{high}）の外です"
            )
    bounds = [low, *ordered, high]
    for a, b in zip(bounds, bounds[1:]):
        if b - a > GROUND_PLANE_BAND_M + _EPS:
            raise ValueError(
                f"標高 {a}〜{b} の区間が{b - a:.2f}mで3mを超えています。"
                "令2条2項の「三メートル以内ごと」を満たすように"
                "切り位置を足してください。"
            )

    sections: list[list[ContactPoint]] = [[] for _ in range(len(bounds) - 1)]
    for c in contour:
        idx = 0
        for j, upper in enumerate(bounds[1:]):
            if c.level_m <= upper + _EPS:
                idx = j
                break
        else:  # pragma: no cover - 上の範囲チェックで届かないはず
            idx = len(sections) - 1
        sections[idx].append(c)

    empty = [i for i, s in enumerate(sections) if not s]
    if empty:
        raise ValueError(
            f"区間 {empty} に接地点が1つもありません。切り位置を見直してください。"
        )
    return sections


def flat_ground_plane(level_m: float = 0.0) -> GroundPlaneSet:
    """平坦地の地盤面。地盤の情報が無いときの既定。"""
    return GroundPlaneSet(
        "flat",
        (GroundPlane(level_m=level_m, contact_length_m=0.0,
                     lowest_m=level_m, highest_m=level_m),),
        (f"地盤の高さが与えられていないため、Z={level_m:.1f} を地盤面と"
         "みなしています（令2条2項の算定はしていません）。",),
    )
