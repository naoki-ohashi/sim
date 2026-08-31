"""高度地区（法58条）.

    第五十八条　高度地区内においては、建築物の高さは、高度地区に関する
    都市計画において定められた内容に適合するものでなければならない。

**法本体は数値を一切定めていません。** 制限の内容はすべて各自治体の
都市計画で決まります。したがって勾配も立上りも最高限度も、コードに
書いてはいけません（原則A・G）。このモジュールは**利用者が転記した
都市計画の内容を受け取って評価するだけ**です。

## 天空率では外れません

法56条7項が適用除外にするのは法56条1項第1号〜第3号（道路・隣地・北側の
各斜線）だけで、**法58条は入っていません**（照合台帳の食い違い G で
法56条7項の原文により確認済み）。なので `use_sky_ratio=True` でも
高度地区の制限は効かせます。ここを外すと系統的に過大な結果が出ます。

## 令135条の4の緩和は自動では効きません

後退緩和・高低差緩和・水面等の緩和は、いずれも法56条1項3号（北側斜線）に
ついて令135条の4が定めているもので、**法58条には及びません**。高度地区の
緩和は都市計画が定めるものなので、自動では一切適用しません（厳しい側）。

都市計画が後退緩和を定めている場合だけ `setback_relaxation_m` に
その距離を入れてください。高低差緩和を定めている都市計画には
まだ対応していません。

## 第2項は許可規定なので実装しません（2026-08-30、現行版で確認）

    ２　前項の都市計画において建築物の高さの最高限度が定められた高度地区内に
    おいては、再生可能エネルギー源の利用に資する設備の設置のため必要な屋根に
    関する工事その他の屋外に面する建築物の部分に関する工事を行う建築物で
    構造上やむを得ないものとして国土交通省令で定めるものであつて、特定行政庁が
    市街地の環境を害するおそれがないと認めて許可したものの高さは、同項の規定に
    かかわらず、その許可の範囲内において、当該最高限度を超えるものとすることが
    できる。

以前は原文を取得できず「許可規定と推測されるが推測では実装しない」と
書いていました。現行版が手に入り、推測どおりでした。

**許可は個別判断で、エンジンが敷地情報から計算する話ではありません。**
該当する計画では、**許可後の高さを `max_height_m` に入れてください**。
そのほうが「許可を受けた前提で検討している」ことが入力に残ります。

第3項は法44条2項（許可の手続）の準用です。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..geometry import Point
from ..site import Site
from . import north_slant

_EPS = 1e-9


@dataclass(frozen=True)
class HeightDistrictTier:
    """高度地区の北側高度斜線の1段。

    真北方向の水平距離 L が `[from_distance_m, to_distance_m)` にあるとき

        H = start_height_m + slope × L

    **都市計画の文言をそのまま転記してください。** 多段の制限を持つ
    高度地区があるので、段ごとに範囲を明示する形にしています。範囲を
    利用者に書かせるのは、段の切り方をこちらで推測しないためです。

    `slope = 0` なら、その範囲では `start_height_m` の水平な上限です。
    """

    start_height_m: float
    slope: float
    from_distance_m: float = 0.0
    to_distance_m: Optional[float] = None   # None なら以遠すべて

    def __post_init__(self) -> None:
        if self.start_height_m < 0:
            raise ValueError("start_height_m は0以上にしてください")
        if self.slope < 0:
            raise ValueError("slope は0以上にしてください")
        if self.from_distance_m < 0:
            raise ValueError("from_distance_m は0以上にしてください")
        if self.to_distance_m is not None and self.to_distance_m <= self.from_distance_m:
            raise ValueError(
                f"to_distance_m ({self.to_distance_m}) は "
                f"from_distance_m ({self.from_distance_m}) より大きくしてください"
            )

    def contains(self, distance_m: float) -> bool:
        if distance_m < self.from_distance_m - _EPS:
            return False
        if self.to_distance_m is None:
            return True
        return distance_m < self.to_distance_m - _EPS

    def height_at(self, distance_m: float) -> float:
        return self.start_height_m + self.slope * distance_m


@dataclass(frozen=True)
class HeightDistrict:
    """高度地区の内容（都市計画で定められたもの）。

    - `name` … 「第一種高度地区」など。図面と注記に出すだけ
    - `max_height_m` … 最高限度（定めがなければ None）
    - `min_height_m` … 最低限度（定めがなければ None）。**上限ではない**ので
      ボリュームは制約しません。下回っていれば注記を出します
    - `north_tiers` … 北側高度斜線の段。空なら北側の制限なし
    - `include_road_width` … 北側が前面道路のとき、真北方向の距離を
      **道路の反対側の境界線**から測るか。**既定値はありません。**
      都市計画の文言を確認して明示してください（原則H）
    - `setback_relaxation_m` … 都市計画が定める後退緩和の距離。
      既定は0（緩和なし）。令135条の4の後退緩和は法58条には及びません
    """

    north_tiers: tuple[HeightDistrictTier, ...] = ()
    include_road_width: Optional[bool] = None
    name: str = ""
    max_height_m: Optional[float] = None
    min_height_m: Optional[float] = None
    setback_relaxation_m: float = 0.0

    def __post_init__(self) -> None:
        if self.setback_relaxation_m < 0:
            raise ValueError("setback_relaxation_m は0以上にしてください")
        if (self.max_height_m is not None and self.min_height_m is not None
                and self.min_height_m > self.max_height_m):
            raise ValueError("min_height_m が max_height_m を超えています")
        if self.north_tiers:
            if self.include_road_width is None:
                raise ValueError(
                    "北側高度斜線を指定する場合は include_road_width を明示して"
                    "ください。北側が前面道路のとき真北方向の距離を道路の反対側から"
                    "測るかは都市計画の定め方によるので、既定値を置きません。"
                )
            _check_tiers(self.north_tiers)

    @property
    def has_north_slant(self) -> bool:
        return bool(self.north_tiers)

    def tier_at(self, distance_m: float) -> Optional[HeightDistrictTier]:
        for tier in self.north_tiers:
            if tier.contains(distance_m):
                return tier
        return None

    def describe_ja(self) -> str:
        parts = []
        if self.name:
            parts.append(self.name)
        if self.max_height_m is not None:
            parts.append(f"最高限度 {self.max_height_m:.1f}m")
        if self.min_height_m is not None:
            parts.append(f"最低限度 {self.min_height_m:.1f}m")
        for tier in self.north_tiers:
            upper = "以遠" if tier.to_distance_m is None else f"〜{tier.to_distance_m:.1f}m"
            parts.append(
                f"北側 {tier.from_distance_m:.1f}m{upper}: "
                f"{tier.start_height_m:.1f}m + {tier.slope:.2f}×L"
            )
        return " / ".join(parts) if parts else "（内容の指定なし）"


def _check_tiers(tiers: tuple[HeightDistrictTier, ...]) -> None:
    """段が距離0から隙間なく、重なりなく並んでいるか。

    隙間があるとその距離で制限が消え、重なるとどちらを取るか決まりません。
    どちらも黙って進めると誤るので弾きます。
    """
    ordered = sorted(tiers, key=lambda t: t.from_distance_m)
    if abs(ordered[0].from_distance_m) > _EPS:
        raise ValueError(
            f"北側高度斜線の最初の段は距離0から始めてください"
            f"（いまは {ordered[0].from_distance_m}m から）"
        )
    for a, b in zip(ordered, ordered[1:]):
        if a.to_distance_m is None:
            raise ValueError("以遠すべてを受け持つ段の先に、別の段があります")
        if abs(a.to_distance_m - b.from_distance_m) > _EPS:
            raise ValueError(
                f"段の範囲が繋がっていません（{a.to_distance_m}m と "
                f"{b.from_distance_m}m の間）。隙間も重なりも許しません。"
            )
    if ordered[-1].to_distance_m is not None:
        raise ValueError(
            f"最後の段は to_distance_m を None にして以遠すべてを"
            f"受け持たせてください（いまは {ordered[-1].to_distance_m}m まで）"
        )


# === 敷地への適用 =====================================================

def applies(site: Site) -> bool:
    return site.height_district is not None


def edge_height_limit(site: Site, edge_index: int, point: Point) -> float:
    """1つの北側境界線による高度地区の制限。"""
    district = site.height_district
    if district is None or not district.has_north_slant:
        return math.inf
    edge = site.edges[edge_index]

    distance = north_slant._north_distance(site, edge, point)
    distance += district.setback_relaxation_m
    if edge.is_road and district.include_road_width:
        distance += edge.road_width_m

    tier = district.tier_at(distance)
    if tier is None:      # _check_tiers が通っていれば起きない
        return math.inf
    return tier.height_at(distance)


def height_limit_at(site: Site, point: Point) -> float:
    """点における高度地区の高さ制限。

    最高限度と北側高度斜線の**厳しい方**。天空率では外れません。
    """
    district = site.height_district
    if district is None:
        return math.inf

    limits = [math.inf if district.max_height_m is None else district.max_height_m]
    if district.has_north_slant:
        limits.extend(
            edge_height_limit(site, i, point) for i in north_slant.north_edges(site)
        )
    return min(limits)


def required_setback_for_height(site: Site, edge_index: int, height_m: float) -> float:
    """高さ `height_m` に必要な、北側境界線からの真北方向の距離。

    北側斜線（法56条1項3号）と同じく真北方向で測ります。
    """
    district = site.height_district
    if district is None or not district.has_north_slant or height_m <= 0:
        return 0.0
    if district.max_height_m is not None and height_m > district.max_height_m + _EPS:
        return math.inf      # 最高限度を超えるので、どこまで下がっても不可

    edge = site.edges[edge_index]
    base = district.setback_relaxation_m
    if edge.is_road and district.include_road_width:
        base += edge.road_width_m

    # 各段で「その段の範囲内で height_m を満たす最小の距離」を求め、
    # 段をまたいで最小を取る。段の境目で制限が下がることがあるので、
    # 全体としては単調とは限らない。だから全段を見る。
    best = math.inf
    for tier in district.north_tiers:
        upper = tier.to_distance_m
        if tier.slope <= _EPS:
            if tier.start_height_m + _EPS < height_m:
                continue          # この段ではどこまで下がっても届かない
            candidate = tier.from_distance_m
        else:
            candidate = max(tier.from_distance_m,
                            (height_m - tier.start_height_m) / tier.slope)
        if upper is not None and candidate > upper - _EPS:
            continue              # その段の範囲を出てしまう
        best = min(best, candidate)

    if not math.isfinite(best):
        return math.inf
    return max(0.0, best - base)


def compliance_notes(site: Site, max_height_m: float) -> list[str]:
    """高度地区についての注記。最低限度のチェックを含む。"""
    district = site.height_district
    if district is None:
        return []
    notes = [f"高度地区（法58条）: {district.describe_ja()}"]
    notes.append(
        "高度地区は天空率（法56条7項）では緩和されません"
        "（法56条7項の適用除外は法56条1項1号〜3号のみ）。"
    )
    if district.min_height_m is not None and max_height_m + _EPS < district.min_height_m:
        notes.append(
            f"**最高高さ {max_height_m:.2f}m が高度地区の最低限度 "
            f"{district.min_height_m:.1f}m を下回っています。** 最低限度は"
            "ボリュームの上限ではないので探索では考慮していません。"
            "計画として満たせるか確認してください。"
        )
    return notes
