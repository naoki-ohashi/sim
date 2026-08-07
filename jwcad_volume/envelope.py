"""Maximum legally-buildable volume: combine slant-line baseline, a 天空率
"podium + tower" search, 建蔽率 (coverage ratio) and 容積率 (FAR) caps.

This is a heuristic optimizer, not a global optimum -- see
docs/methodology.md for what a human designer could still improve on beyond
this single family of shapes.

Why "podium + tower" and not a simpler uniform stretch: the slant-line
reference building already touches the legal height limit *everywhere*, so
any candidate that is taller or bulkier than it at *every* point can never
satisfy Ps >= Pr (a strict superset always blocks at least as much sky).
Gaining real volume requires trading bulk somewhere for height elsewhere.
The family used here keeps the baseline (podium) exactly as-is up to a split
height -- this is important, because the baseline may already touch a
regulated boundary at distance 0 there (e.g. an 隣地斜線 wall with no
mandatory setback, legally up to 20m tall), and even a tiny height increase
right at distance ~0 swings the blocked elevation angle towards 90 degrees.
Leaving the podium untouched sidesteps that instability entirely. Above the
split, the baseline's own tapering continuation is replaced with a single
flat-footprint tower (the baseline's footprint at the split height, held
constant rather than continuing to shrink) extended upward as far as sky
ratio allows.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .massing import Block, max_height as blocks_max_height, total_floor_area, total_volume
from .regulations.combined import required_setback_for_height
from .geometry import offset_polygon_by_edge_distances
from .regulations.shadow import ShadowLineResult, ShadowRegulationParams, compute_shadow_hours
from .regulations.sky_ratio import SkyRatioCheck, check_sky_ratio, measurement_points, sky_ratio_percent
from .regulations.reference_building import reference_building_blocks
from .site import Site

DEFAULT_SPLIT_FRACTIONS = (0.3, 0.5, 0.7)


# 各段で試すセットバック量の候補(m)と、積む段数の上限。
# 30m角の敷地・既定精度での実測: 1段=+10.5% / 2段=+12.5% / 3段=+12.8%
# （いずれも斜線制限のみの体積に対する増分）。3段目の伸びは小さい割に
# 計算時間が倍近くになるため、既定は2段にしてある。最終確認では設定で
# max_stages を上げるとわずかに改善する。
DEFAULT_STAGE_INSETS_M = (0.0, 3.0, 6.0)
DEFAULT_MAX_STAGES = 2


@dataclass
class TowerStage:
    """タワー1段分。`inset_m` は分割高さでの平面形状から内側へ引いた量。"""

    inset_m: float
    footprint_area_m2: float
    z_bottom: float
    z_top: float

    @property
    def height_m(self) -> float:
        return self.z_top - self.z_bottom


@dataclass
class TowerCandidate:
    split_height_m: float
    stages: list[TowerStage]
    blocks: list[Block]

    @property
    def volume_m3(self) -> float:
        return total_volume(self.blocks)

    @property
    def extra_height_m(self) -> float:
        """ポディウム上端からタワー頂部までの高さ。"""
        return sum(s.height_m for s in self.stages)

    @property
    def tower_footprint_area_m2(self) -> float:
        """最下段タワーの平面積（段が無い場合は0）。"""
        return self.stages[0].footprint_area_m2 if self.stages else 0.0


def _podium_up_to(baseline: list[Block], split_height: float) -> list[Block]:
    """All baseline material up to split_height, clipping (not dropping) any
    single layer that straddles it -- keeping the full layer list filtered
    by z_top <= split_height alone would throw away legally-available
    volume from a straddling layer's lower portion, unnecessarily weakening
    the podium (and understating how much room is actually left for a
    tower)."""
    podium: list[Block] = []
    for b in baseline:
        if b.z_bottom >= split_height - 1e-9:
            break
        if b.z_top <= split_height + 1e-9:
            podium.append(b)
        else:
            podium.append(Block(footprint=b.footprint, z_bottom=b.z_bottom, z_top=split_height))
    return podium


def _inset(footprint, inset_m: float):
    """平面形状を内側へ inset_m だけ縮める（空になったら None）。"""
    if inset_m <= 0:
        return footprint
    shrunk = footprint.buffer(-inset_m)
    if shrunk.is_empty or shrunk.area < 1e-6:
        return None
    if shrunk.geom_type != "Polygon":
        shrunk = max(shrunk.geoms, key=lambda g: g.area)
    return shrunk


def _max_extra_height_for_split(
    site: Site,
    baseline: list[Block],
    split_height: float,
    mps,
    pr_values: list[float],
    n_azimuth: int,
    measurement_height: float,
    extra_h_max: float,
    iterations: int,
    stage_insets_m: tuple[float, ...] = DEFAULT_STAGE_INSETS_M,
    max_stages: int = DEFAULT_MAX_STAGES,
) -> TowerCandidate | None:
    """分割高さを決め打ちして、その上に載せられるタワーを段階的に探す。

    1段目を積んだら、その上にさらにセットバックした2段目を積めないかを
    順に試す貪欲法です。各段はセットバック量の候補ごとに「天空率が通る
    最大の高さ」を二分探索し、体積の増分が最大になる候補を採用します。
    セットバック0も候補に含めるので、結果は必ず単段の解以上になります
    （＝この探索を多段化しても解が悪くなることはない）。
    """
    podium = _podium_up_to(baseline, split_height)
    distances = [required_setback_for_height(e, split_height, site) for e in site.edges]
    base_footprint = offset_polygon_by_edge_distances(site.points, distances)
    if base_footprint is None or base_footprint.area < 1e-6:
        return None

    def all_pass(blocks: list[Block]) -> bool:
        for mp, pr in zip(mps, pr_values):
            ps = sky_ratio_percent((mp.point[0], mp.point[1], measurement_height), blocks, n_azimuth)
            if ps < pr:
                return False
        return True

    def tallest_stage(fixed: list[Block], footprint, z_bottom: float, h_max: float) -> float:
        """`fixed` の上に `footprint` の段を載せられる最大の高さ。"""
        def blocks_for(h: float) -> list[Block]:
            if h <= 1e-9:
                return fixed
            return fixed + [Block(footprint=footprint, z_bottom=z_bottom, z_top=z_bottom + h)]

        if all_pass(blocks_for(h_max)):
            return h_max
        lo, hi = 0.0, h_max
        for _ in range(iterations):
            mid = (lo + hi) / 2
            if all_pass(blocks_for(mid)):
                lo = mid
            else:
                hi = mid
        return lo

    stages: list[TowerStage] = []
    blocks = list(podium)
    z = split_height
    remaining = extra_h_max
    cumulative_inset = 0.0

    for _ in range(max_stages):
        if remaining <= 1e-6:
            break
        best = None  # (増えた体積, inset, 高さ, 平面形状)
        for inset in stage_insets_m:
            total_inset = cumulative_inset + inset
            footprint = _inset(base_footprint, total_inset)
            if footprint is None:
                continue
            h = tallest_stage(blocks, footprint, z, remaining)
            gain = footprint.area * h
            if h > 1e-6 and (best is None or gain > best[0]):
                best = (gain, total_inset, h, footprint)
        if best is None or best[0] <= 1e-6:
            break
        _, total_inset, h, footprint = best
        blocks = blocks + [Block(footprint=footprint, z_bottom=z, z_top=z + h)]
        stages.append(TowerStage(total_inset, footprint.area, z, z + h))
        cumulative_inset = total_inset
        z += h
        remaining -= h

    if not stages:
        return None
    return TowerCandidate(split_height, stages, blocks)


def search_sky_ratio_tower(
    site: Site,
    baseline: list[Block],
    interval_m: float,
    n_azimuth: int,
    measurement_height: float,
    split_fractions: tuple[float, ...] = DEFAULT_SPLIT_FRACTIONS,
    extra_h_max: float | None = None,
    iterations: int = 24,
    stage_insets_m: tuple[float, ...] = DEFAULT_STAGE_INSETS_M,
    max_stages: int = DEFAULT_MAX_STAGES,
) -> TowerCandidate:
    """分割高さの候補を順に試し、それぞれで多段タワーを探索して、
    最も体積の大きい組み合わせを返す。

    どの候補もベースライン（斜線制限そのもの）を下回らない場合は
    ベースラインをそのまま返します。ベースラインは常に合法なので、
    これが安全な下限になります。"""
    if not baseline:
        return TowerCandidate(0.0, [], [])
    max_h = blocks_max_height(baseline)
    if extra_h_max is None:
        extra_h_max = max_h * 2.0
    mps = measurement_points(site, interval_m)
    baseline_volume = total_volume(baseline)
    best = TowerCandidate(max_h, [], baseline)
    if not mps:
        return best
    pr_values = [
        sky_ratio_percent((mp.point[0], mp.point[1], measurement_height), baseline, n_azimuth) for mp in mps
    ]
    for frac in split_fractions:
        split_height = max_h * frac
        candidate = _max_extra_height_for_split(
            site, baseline, split_height, mps, pr_values, n_azimuth, measurement_height,
            extra_h_max, iterations, stage_insets_m, max_stages,
        )
        if candidate is not None and candidate.volume_m3 > best.volume_m3 + max(1e-6, baseline_volume * 1e-9):
            best = candidate
    return best


def _apply_coverage_cap(blocks: list[Block], max_area_m2: float, iterations: int = 40) -> list[Block]:
    """Uniformly erode every layer's footprint (same distance for all
    layers, so the massing stays properly nested) until the base layer's
    area is within the 建蔽率 cap."""
    if not blocks:
        return blocks
    base_area = blocks[0].footprint.area
    if base_area <= max_area_m2:
        return blocks

    def base_area_after_erosion(d: float) -> float:
        return blocks[0].footprint.buffer(-d).area

    lo, hi = 0.0, math.sqrt(base_area / math.pi)
    while base_area_after_erosion(hi) > max_area_m2:
        hi *= 2.0
        if hi > 1.0e5:
            break  # pathological input; stop trying rather than loop forever
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if base_area_after_erosion(mid) > max_area_m2:
            lo = mid
        else:
            hi = mid
    d = hi
    result = []
    for b in blocks:
        eroded = b.footprint.buffer(-d)
        if not eroded.is_empty and eroded.area > 1e-6:
            if eroded.geom_type != "Polygon":
                eroded = max(eroded.geoms, key=lambda g: g.area)
            result.append(Block(footprint=eroded, z_bottom=b.z_bottom, z_top=b.z_top))
    return result


def _apply_far_cap(blocks: list[Block], max_far_area_m2: float, floor_height_m: float) -> list[Block]:
    """Truncate the massing from the top once cumulative volume reaches the
    容積率 cap (volume / floor_height_m == floor area, matching
    massing.total_floor_area, so this stops exactly where that would report
    the cap reached). Truncating by height (a subset of each kept block's
    own range) rather than swapping in resampled floor slices keeps every
    kept block geometrically identical to its pre-cap self, so a shape
    already verified to pass the sky-ratio check stays passing after this."""
    max_volume = max_far_area_m2 * floor_height_m
    result: list[Block] = []
    used_volume = 0.0
    for b in blocks:
        if used_volume + b.volume <= max_volume:
            result.append(b)
            used_volume += b.volume
            continue
        remaining_volume = max_volume - used_volume
        if remaining_volume > 1e-9 and b.footprint.area > 0:
            new_height = remaining_volume / b.footprint.area
            if new_height > 1e-6:
                result.append(Block(footprint=b.footprint, z_bottom=b.z_bottom, z_top=b.z_bottom + new_height))
        break
    return result


def _scale_height(blocks: list[Block], scale: float) -> list[Block]:
    return [Block(footprint=b.footprint, z_bottom=b.z_bottom * scale, z_top=b.z_top * scale) for b in blocks]


def _reduce_for_shadow(
    site: Site, blocks: list[Block], params: ShadowRegulationParams, iterations: int = 16
) -> tuple[list[Block], float, list[ShadowLineResult]]:
    """If `blocks` violates the shadow regulation, uniformly scale its
    height down (from the ground) until it complies. This is a coarse,
    always-available fallback -- it does not know which specific part of the
    massing causes the violation, so a real design would likely do better by
    reshaping (e.g. pulling the tower away from the affected side) rather
    than shrinking everything uniformly."""
    checks = compute_shadow_hours(site, blocks, params)
    if all(c.ok for c in checks) or not blocks:
        return blocks, 1.0, checks

    def checks_for(scale: float) -> list[ShadowLineResult]:
        return compute_shadow_hours(site, _scale_height(blocks, scale), params)

    lo, hi = 0.0, 1.0
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if all(c.ok for c in checks_for(mid)):
            lo = mid
        else:
            hi = mid
    return _scale_height(blocks, lo), lo, checks_for(lo)


@dataclass
class EnvelopeResult:
    site: Site
    baseline_blocks: list[Block]  # slant-line-only envelope, no sky-ratio/coverage/FAR caps
    boosted_blocks: list[Block]  # podium + sky-ratio tower, before coverage/FAR caps
    blocks: list[Block]  # final buildable massing (after coverage + FAR caps + shadow reduction)
    tower: TowerCandidate
    sky_ratio_checks: list[SkyRatioCheck]
    coverage_cap_applied: bool
    far_cap_applied: bool
    shadow_checks: list[ShadowLineResult] | None = None
    shadow_height_scale: float = 1.0

    @property
    def footprint_area_m2(self) -> float:
        return self.blocks[0].footprint.area if self.blocks else 0.0

    @property
    def max_height_m(self) -> float:
        return blocks_max_height(self.blocks)

    @property
    def volume_m3(self) -> float:
        return total_volume(self.blocks)

    @property
    def total_floor_area_m2(self) -> float:
        return total_floor_area(self.blocks, self.site.floor_height_m)

    def summary_lines_ja(self) -> list[str]:
        """日本語のサマリー。文字コードを自前で管理できる出力先
        （HTMLビューア）専用です。DXFとコンソール出力は、JWWのDXF読込や
        Windowsコンソールの文字コードでの文字化けを避けるため、ASCIIの
        `summary_lines()` を使います。"""
        lines = [
            f"敷地面積: {self.site.area_m2:.1f} m2",
            f"建築面積: {self.footprint_area_m2:.1f} m2"
            f"（建蔽率の上限 {self.site.max_building_area_m2():.1f} m2）",
            f"延床面積(概算): {self.total_floor_area_m2:.1f} m2"
            f"（容積率の上限 {self.site.max_total_floor_area_m2():.1f} m2）",
            f"最高高さ: {self.max_height_m:.2f} m",
            f"体積: {self.volume_m3:.1f} m3",
        ]
        if self.tower.stages:
            lines.append(
                f"天空率による割増: 高さ{self.tower.split_height_m:.1f}mから上に"
                f"{len(self.tower.stages)}段、計+{self.tower.extra_height_m:.1f}m"
            )
            for i, stage in enumerate(self.tower.stages, 1):
                lines.append(
                    f"　{i}段目: セットバック{stage.inset_m:.1f}m / "
                    f"{stage.footprint_area_m2:.1f} m2 / 高さ{stage.height_m:.1f}m"
                )
        else:
            lines.append("天空率による割増: なし（斜線制限のままが最大）")
        caps = []
        if self.coverage_cap_applied:
            caps.append("建蔽率")
        if self.far_cap_applied:
            caps.append("容積率")
        lines.append("上限に達した規制: " + ("・".join(caps) if caps else "なし"))
        ok_count = sum(1 for c in self.sky_ratio_checks if c.ok)
        lines.append(f"天空率の判定: {ok_count}/{len(self.sky_ratio_checks)} 点が適合")
        if self.shadow_checks is not None:
            if self.shadow_height_scale < 1.0:
                lines.append(f"日影規制により高さを {self.shadow_height_scale:.1%} に縮小")
            else:
                lines.append("日影規制による縮小: なし")
            for c in self.shadow_checks:
                worst = c.worst_point[1]
                label = "第1種" if c.line_name == "line1" else "第2種"
                lines.append(
                    f"　{label}測定線（{c.max_hours}時間以内）: "
                    f"{'適合' if c.ok else '不適合'} / 最大 {worst:.2f}時間"
                )
        return lines

    def summary_lines(self) -> list[str]:
        lines = [
            f"site area: {self.site.area_m2:.1f} m2",
            f"footprint area: {self.footprint_area_m2:.1f} m2 (cap {self.site.max_building_area_m2():.1f} m2)",
            f"total floor area (est.): {self.total_floor_area_m2:.1f} m2 "
            f"(cap {self.site.max_total_floor_area_m2():.1f} m2)",
            f"max height: {self.max_height_m:.2f} m",
            f"volume: {self.volume_m3:.1f} m3",
            f"sky-ratio tower: split {self.tower.split_height_m:.1f}m, "
            f"{len(self.tower.stages)} stage(s), +{self.tower.extra_height_m:.1f}m total",
            f"coverage cap applied: {self.coverage_cap_applied}, FAR cap applied: {self.far_cap_applied}",
            f"sky-ratio checks: {sum(1 for c in self.sky_ratio_checks if c.ok)}/{len(self.sky_ratio_checks)} ok",
        ]
        if self.shadow_checks is not None:
            lines.append(f"shadow height scale applied: {self.shadow_height_scale:.3f}")
            for c in self.shadow_checks:
                worst = c.worst_point[1]
                lines.append(f"  {c.line_name} (<= {c.max_hours}h): {'OK' if c.ok else 'NG'}, worst {worst:.2f}h")
        return lines


def compute_max_envelope(
    # Defaults favor a quick (a few seconds) first look; the sky-ratio tower
    # search cost scales roughly with n_layers * (1/interval_m) * n_azimuth *
    # len(split_fractions) * search_iterations, so raise these (e.g.
    # n_layers=30, interval_m=2.0, n_azimuth=180, search_iterations=24) for a
    # more precise final check once the site/zoning parameters are settled.
    site: Site,
    n_layers: int = 10,
    interval_m: float = 4.0,
    n_azimuth: int = 45,
    measurement_height: float = 0.0,
    split_fractions: tuple[float, ...] = DEFAULT_SPLIT_FRACTIONS,
    search_iterations: int = 12,
    stage_insets_m: tuple[float, ...] = DEFAULT_STAGE_INSETS_M,
    max_stages: int = DEFAULT_MAX_STAGES,
    use_sky_ratio: bool = True,
    shadow_params: ShadowRegulationParams | None = None,
) -> EnvelopeResult:
    baseline = reference_building_blocks(site, n_layers=n_layers)
    if not baseline:
        empty: list[Block] = []
        empty_tower = TowerCandidate(0.0, [], [])
        return EnvelopeResult(site, empty, empty, empty, empty_tower, [], False, False)

    if use_sky_ratio:
        tower = search_sky_ratio_tower(
            site, baseline, interval_m, n_azimuth, measurement_height, split_fractions,
            iterations=search_iterations, stage_insets_m=stage_insets_m, max_stages=max_stages,
        )
    else:
        tower = TowerCandidate(blocks_max_height(baseline), [], baseline)
    boosted = tower.blocks

    coverage_capped = _apply_coverage_cap(boosted, site.max_building_area_m2())
    coverage_applied = len(coverage_capped) != len(boosted) or any(
        a.footprint.area != b.footprint.area for a, b in zip(coverage_capped, boosted)
    )

    final = _apply_far_cap(coverage_capped, site.max_total_floor_area_m2(), site.floor_height_m)
    far_applied = len(final) != len(coverage_capped)

    shadow_checks: list[ShadowLineResult] | None = None
    shadow_scale = 1.0
    if shadow_params is not None:
        final, shadow_scale, shadow_checks = _reduce_for_shadow(site, final, shadow_params)

    checks = check_sky_ratio(
        site, final, reference_blocks=baseline, interval_m=interval_m, n_azimuth=n_azimuth,
        measurement_height=measurement_height,
    )

    return EnvelopeResult(
        site=site,
        baseline_blocks=baseline,
        boosted_blocks=boosted,
        blocks=final,
        tower=tower,
        sky_ratio_checks=checks,
        coverage_cap_applied=coverage_applied,
        far_cap_applied=far_applied,
        shadow_checks=shadow_checks,
        shadow_height_scale=shadow_scale,
    )
