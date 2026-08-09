"""逆日影計算：屋根越しパターン・棟状パターン.

## 位置づけ

`optimizer.py` の既定（ボクセル貪欲法）は、超過している測定点ごとに
「そこを日影にしているマスだけ」を個別に下げます。容積は最大化されますが、
結果は**マスごとにばらばらな段の階段状**になり、そのままでは建築的な量塊
（片流れ屋根・切妻屋根のような規則正しい形）として使えません。

本モジュールは、**日影の最も厳しい方位から見た1枚〜2枚の勾配面**で建物の
天端を規則正しく段状に後退させる、逆日影の別解を提供します。

    屋根越しパターン … 1枚の勾配面で敷地全体を後退させる（片流れ屋根に相当）
    棟状パターン     … 棟（稜線）を挟んで2枚の勾配面を持つ（切妻屋根に相当）

どちらも、`shadow_index.py` の「しきい値高さ」インデックスをそのまま使い、
容積を最大化するようメッシュを細かく刻んだ**規則正しい段**を探索します。
段の粗さはメッシュの階高（`floor_height_m`）で決まり、階数は必ず整数です
（実在の建物と同じく、床は半階刻みにはなりません）。

## 棟の向きの決め方

自由に探索すると計算量が爆発するうえ、敷地形状だけからは決め手がありません。
そこで、**日影規制を最も厳しくしている太陽方位**を先に特定し、その方位を
中心にした狭い範囲だけを探索します。

1. 現在の高さ配列（斜線制限・建蔽率・容積率までを適用した状態）で、最も
   規制超過が大きい測定点を求める（`ShadowIndex.worst`）。
2. その測定点を日影にしている時刻のうち、**解消に最も体積を要する時刻**
   （＝最も影響が大きい時刻）の太陽方位角を「臨界方位」とする。
3. 臨界方位から見て建物の低い側（測定点に面する側）が、屋根の低勾配側に
   なるようにする。太陽の方向 = 臨界方位なので、低い側が向く方位は
   `(臨界方位 + 180°) % 360`（測定点は太陽と反対側にある）。
4. 棟の向き（＝低い側が向く方位）は、この値を中心に ±`angle_span_deg` の
   範囲で探索する。「方位に合わせて探索する」という設計判断を、固定では
   なく**狭い範囲の探索**として反映している。

## 屋根越しパターンとの関係

屋根越しパターンは、棟状パターンの特殊形（棟を外郭線の外側まで押し出し、
敷地全体が「低い側」になったもの）として実装します。同じ計算式を使うため、
2つのパターンで結果の比較がそのまま公平にできます。

## 検証

インデックス上の判定に加えて、`regulations.shadow.compute_shadow_hours`
（shapely を使う独立した実装）で必ず再確認します
（`tests/mve/test_roof_envelope.py`）。天空率で行った検証と同じ考え方です。

## 天空率との同時最適化

`sky_index` を渡すと、棟高の二分探索が**日影と天空率の両方**を条件にします
（`optimizer.py` の従来の実装は、屋根形状で日影を解消したあとに天空率だけを
自由形で別途削る2段階でした。これだと天空率の是正が屋根の規則正しい形を
崩してしまいます）。

候補（方位・棟位置・両側の勾配）ごとに、**日影と天空率の両方が適合する
棟高**を二分探索で求め、その中で延床面積が最大のものを採用します。
下げる操作はどちらの適合にも悪影響を与えないため（単調性）、二分探索は
天空率単独のときと同じ理屈で安全に行えます。

離散的な候補の中に両方を満たす組み合わせが1つも無い場合は、**日影だけを
満たす形に戻します**（`sky_ratio_included=False`）。この場合、天空率の
是正は呼び出し側（`optimizer.py`）が別途フリーフォームで行います。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geometry import Point
from .mesh import BuildableArea
from .regulations.shadow import ShadowRegulationSpec
from .shadow_index import ShadowIndex, build_shadow_index
from .site import Site
from .sky_index import SkyIndex

#: 棟の向きを探索する範囲（臨界方位を中心に ±この角度）
DEFAULT_ANGLE_SPAN_DEG = 15.0
DEFAULT_ANGLE_STEP_DEG = 7.5

#: 棟位置の候補数（棟状パターンのみ。屋根越しパターンは1つに固定）
DEFAULT_OFFSET_STEPS = 7

#: 勾配の候補（度）。建築で一般的な範囲を既定にしている。
DEFAULT_PITCH_CANDIDATES_DEG = (20.0, 27.0, 35.0, 45.0)
#: 棟の反対側（日影に効かない側）の勾配候補。0は「制限なし（元の高さ制限のまま）」
DEFAULT_FAR_PITCH_CANDIDATES_DEG = (0.0, 20.0, 35.0)

#: 棟の高さを絞り込む二分探索の回数
DEFAULT_HEIGHT_BISECTION_STEPS = 18


@dataclass
class RoofPlaneSpec:
    """屋根形状のパラメータ（棟状パターンが一般形。屋根越しパターンはその特殊形）。"""

    pattern: str                     # "lean_to"（屋根越し） | "ridge"（棟状）
    low_azimuth_deg: float           # 低勾配側が向く方位（真北基準・時計回り）
    ridge_offset_m: float            # 棟の位置（外郭線の重心から low_azimuth 方向への符号付き距離）
    pitch_near_deg: float            # 低勾配側（日影の厳しい側）の勾配
    pitch_far_deg: float             # 反対側の勾配。0なら制限なし（lean_toでは未使用）
    ridge_height_m: float            # 棟の高さ（GLから）
    critical_azimuth_deg: float | None = None   # 探索の基準にした太陽方位角（記録用）

    def describe_ja(self) -> str:
        name = "屋根越しパターン（片流れ）" if self.pattern == "lean_to" else "棟状パターン（切妻）"
        low = f"低勾配側 方位{self.low_azimuth_deg:.0f}° 勾配{self.pitch_near_deg:.0f}度"
        if self.pattern == "lean_to":
            return f"{name} / 棟高{self.ridge_height_m:.2f}m / {low}"
        far = ("反対側は元の高さ制限のまま" if self.pitch_far_deg <= 0
               else f"反対側 勾配{self.pitch_far_deg:.0f}度")
        return f"{name} / 棟高{self.ridge_height_m:.2f}m / {low} / {far}"


@dataclass
class RoofSearchResult:
    spec: RoofPlaneSpec | None       # 屋根形状なしで既に適合していれば None
    floors: np.ndarray
    #: 天空率も同じ棟高で満たしたか（False なら別途フリーフォームの是正が要る）
    sky_ratio_included: bool = False
    notes: list[str] = field(default_factory=list)


def _low_normal(site: Site, low_azimuth_deg: float) -> Point:
    return site.north.vector_for_azimuth(low_azimuth_deg)


def _critical_azimuth_deg(index: ShadowIndex, heights: np.ndarray) -> float | None:
    """規制超過を解消するのに最も体積を要する時刻の、太陽方位角。"""
    worst = index.worst(heights)
    if worst is None:
        return None
    distance, point_index, _hours, _excess = worst

    best_time: int | None = None
    best_cost = -1.0
    for ti in index.active_hours(distance, point_index, heights):
        if index.sun_azimuths_deg[ti] is None:
            continue
        cells = index.offending_cells(distance, point_index, int(ti), heights)
        cost = float(len(cells))    # マス数を体積の代理指標にする（面積は後段で正確に評価する）
        if cost > best_cost:
            best_cost, best_time = cost, int(ti)
    if best_time is None:
        return None
    return index.sun_azimuths_deg[best_time]


def _height_caps(
    centers: np.ndarray, low_normal: Point, ridge_point: np.ndarray,
    ridge_height_m: float, pitch_near_deg: float, pitch_far_deg: float,
) -> np.ndarray:
    """マス中心ごとの、この屋根形状による高さ上限。"""
    n = np.array(low_normal)
    s = (centers - ridge_point) @ n     # 正: 低勾配側（臨界方位を向く側）
    near_cap = ridge_height_m - math.tan(math.radians(pitch_near_deg)) * np.maximum(s, 0.0)
    if pitch_far_deg > 0:
        far_cap = ridge_height_m - math.tan(math.radians(pitch_far_deg)) * np.maximum(-s, 0.0)
    else:
        far_cap = np.full_like(s, np.inf)
    return np.where(s >= 0, near_cap, far_cap)


def _max_floors_for_ridge_height(
    ridge_height_m: float, base_floors: np.ndarray, floor_h: float,
    centers: np.ndarray, low_normal: Point, ridge_point: np.ndarray,
    pitch_near_deg: float, pitch_far_deg: float,
) -> np.ndarray:
    caps = _height_caps(centers, low_normal, ridge_point, ridge_height_m,
                        pitch_near_deg, pitch_far_deg)
    # inf（無制限側）を先に大きな有限値へ丸めてから整数化する（inf→intは未定義動作）
    finite_caps = np.minimum(caps, base_floors.max() * floor_h + 1.0)
    capped = np.floor(finite_caps / floor_h + 1e-9).astype(int)
    return np.clip(np.minimum(base_floors, capped), 0, None)


def _best_ridge_height(
    index: ShadowIndex, lo: float, hi: float, base_floors: np.ndarray, floor_h: float,
    centers: np.ndarray, low_normal: Point, ridge_point: np.ndarray,
    pitch_near_deg: float, pitch_far_deg: float, steps: int,
    sky_index: SkyIndex | None = None,
) -> tuple[float, np.ndarray] | None:
    """棟高を hi から下げていき、適合する最大の棟高を二分探索で求める。

    棟を下げるほど各マスの高さ上限は単調に下がる（または変わらない）ので、
    日影の適合状態も単調に改善する（悪化しない）。この単調性が二分探索の
    前提になっている。`sky_index` を渡すと、**日影と天空率の両方**が適合
    する棟高を探す（天空率も同じ理由で単調なので、そのまま条件に加えられる）。
    """
    def floors_at(h: float) -> np.ndarray:
        return _max_floors_for_ridge_height(
            h, base_floors, floor_h, centers, low_normal, ridge_point,
            pitch_near_deg, pitch_far_deg)

    def compliant(h: float) -> bool:
        heights = floors_at(h) * floor_h
        if not index.is_compliant(heights):
            return False
        return sky_index is None or sky_index.is_compliant(heights)

    if compliant(hi):
        return hi, floors_at(hi)
    if not compliant(lo):
        return None    # 最も低くしても適合しない＝この形状では無理

    for _ in range(steps):
        mid = (lo + hi) / 2.0
        if compliant(mid):
            lo = mid
        else:
            hi = mid
    return lo, floors_at(lo)


def _search_ridge_candidates(
    site: Site, area: BuildableArea, index: ShadowIndex,
    base_floors: np.ndarray, floor_h: float, pattern: str,
    center_azimuth: float, critical_azimuth: float | None,
    angle_span_deg: float, angle_step_deg: float, offset_steps: int,
    pitch_candidates_deg: tuple, far_pitch_candidates_deg: tuple,
    height_bisection_steps: int, fixed_low_azimuth_deg: float | None,
    sky_index: SkyIndex | None,
) -> tuple[float, RoofPlaneSpec, np.ndarray] | None:
    """棟の向き・位置・両側の勾配を総当たりし、延床面積が最大の組み合わせを返す。"""
    centers = np.array([c.center for c in area.cells])
    outline_centroid = np.array(area.outline.centroid.coords[0])
    max_h = float(base_floors.max()) * floor_h

    angle_offsets = ([0.0] if fixed_low_azimuth_deg is not None else
                     list(np.arange(-angle_span_deg, angle_span_deg + 1e-6, angle_step_deg)))
    far_pitches = (0.0,) if pattern == "lean_to" else far_pitch_candidates_deg

    best: tuple[float, RoofPlaneSpec, np.ndarray] | None = None
    for da in angle_offsets:
        low_azimuth = (center_azimuth + da) % 360.0
        low_normal = np.array(_low_normal(site, low_azimuth))
        s_all = (centers - outline_centroid) @ low_normal

        if pattern == "lean_to":
            # 棟を外郭線の外側まで押し出し、全マスを低勾配側にする
            offsets = [float(s_all.min()) - 1.0]
        else:
            smin, smax = float(s_all.min()), float(s_all.max())
            offsets = [smin] if smax <= smin else list(np.linspace(smin, smax, offset_steps))

        for offset in offsets:
            ridge_point = outline_centroid + offset * low_normal
            for pitch_near in pitch_candidates_deg:
                for pitch_far in far_pitches:
                    result = _best_ridge_height(
                        index, 0.0, max_h, base_floors, floor_h, centers, low_normal,
                        ridge_point, pitch_near, pitch_far, height_bisection_steps,
                        sky_index=sky_index)
                    if result is None:
                        continue
                    ridge_height, floors = result
                    area_m2 = float(sum(
                        floors[i] * area.cells[i].area_m2 for i in range(len(area.cells))))
                    if best is None or area_m2 > best[0]:
                        spec = RoofPlaneSpec(
                            pattern=pattern, low_azimuth_deg=low_azimuth,
                            ridge_offset_m=offset,
                            pitch_near_deg=pitch_near, pitch_far_deg=pitch_far,
                            ridge_height_m=ridge_height,
                            critical_azimuth_deg=critical_azimuth,
                        )
                        best = (area_m2, spec, floors)
    return best


def search_roof_envelope(
    site: Site, area: BuildableArea, shadow_spec: ShadowRegulationSpec,
    base_floors: np.ndarray, floor_h: float, pattern: str = "ridge",
    angle_span_deg: float = DEFAULT_ANGLE_SPAN_DEG,
    angle_step_deg: float = DEFAULT_ANGLE_STEP_DEG,
    offset_steps: int = DEFAULT_OFFSET_STEPS,
    pitch_candidates_deg: tuple = DEFAULT_PITCH_CANDIDATES_DEG,
    far_pitch_candidates_deg: tuple = DEFAULT_FAR_PITCH_CANDIDATES_DEG,
    height_bisection_steps: int = DEFAULT_HEIGHT_BISECTION_STEPS,
    fixed_low_azimuth_deg: float | None = None,
    sky_index: SkyIndex | None = None,
) -> RoofSearchResult:
    """屋根越しパターン・棟状パターンで、日影規制に適合する最大容積を探す。

    `base_floors` は斜線制限・建蔽率・容積率までを適用した後の階数配列
    （`optimizer.optimize` のステップ1〜3の結果）。ここからさらに、屋根形状
    による規則正しい後退だけで日影規制を満たす形に絞り込みます。

    `sky_index` を渡すと、**日影と天空率を同時に満たす**棟高だけを探します
    （モジュールdocstringの「天空率との同時最適化」を参照）。候補の中に
    両方を満たすものが無かった場合は、日影だけを満たす形に戻します
    （`RoofSearchResult.sky_ratio_included=False`）。
    """
    if pattern not in ("lean_to", "ridge"):
        raise ValueError('pattern は "lean_to" か "ridge" にしてください')
    if not area.cells or not base_floors.any():
        return RoofSearchResult(None, base_floors.copy())

    index = build_shadow_index(site, area, shadow_spec)
    heights0 = base_floors * floor_h
    if index.is_compliant(heights0):
        return RoofSearchResult(
            None, base_floors.copy(),
            notes=["日影規制は屋根形状を使わなくても既に適合しています。"])

    critical_azimuth = _critical_azimuth_deg(index, heights0)
    if critical_azimuth is None:
        return RoofSearchResult(
            None, base_floors.copy(),
            notes=["日影が超過している原因の方位を特定できませんでした。"])
    center_azimuth = (fixed_low_azimuth_deg if fixed_low_azimuth_deg is not None
                      else (critical_azimuth + 180.0) % 360.0)

    common_args = dict(
        site=site, area=area, index=index, base_floors=base_floors, floor_h=floor_h,
        pattern=pattern, center_azimuth=center_azimuth, critical_azimuth=critical_azimuth,
        angle_span_deg=angle_span_deg, angle_step_deg=angle_step_deg,
        offset_steps=offset_steps, pitch_candidates_deg=pitch_candidates_deg,
        far_pitch_candidates_deg=far_pitch_candidates_deg,
        height_bisection_steps=height_bisection_steps,
        fixed_low_azimuth_deg=fixed_low_azimuth_deg,
    )

    if sky_index is not None:
        best = _search_ridge_candidates(sky_index=sky_index, **common_args)
        if best is not None:
            _area_m2, spec, floors = best
            return RoofSearchResult(spec, floors, sky_ratio_included=True)
        # 両方を満たす組み合わせが候補の中に無かった。日影だけを満たす形に
        # 戻し、天空率は呼び出し側のフリーフォームの是正に任せる。
        best = _search_ridge_candidates(sky_index=None, **common_args)
        if best is None:
            return RoofSearchResult(
                None, np.zeros(len(area.cells), dtype=int),
                notes=["屋根形状のどの候補でも日影規制を満たせませんでした。"
                      "メッシュを細かくするか、階高・敷地条件を見直してください。"])
        _area_m2, spec, floors = best
        return RoofSearchResult(spec, floors, sky_ratio_included=False, notes=[
            "屋根形状の候補の中に、日影と天空率を同時に満たすものがありませんでした。"
            "日影だけを満たす形にしたうえで、天空率は個別のマスの調整で対応します"
            "（屋根の規則正しい形が一部崩れることがあります）。"
        ])

    best = _search_ridge_candidates(sky_index=None, **common_args)
    if best is None:
        return RoofSearchResult(
            None, np.zeros(len(area.cells), dtype=int),
            notes=["屋根形状のどの候補でも日影規制を満たせませんでした。"
                  "メッシュを細かくするか、階高・敷地条件を見直してください。"])
    _area_m2, spec, floors = best
    return RoofSearchResult(spec, floors)
