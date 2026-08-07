"""最大容積の探索（ボクセル法）.

## 手順

    敷地図 → 壁面後退線 → 建物外郭線 → メッシュ → 各マスの階数を決める

各マスは「X × Y × 階高」のボックスを積み上げる柱です。この柱の階数を
決めることが設計変数になります。

1. **上限まで積む**: 各マスに斜線制限（または絶対高さ制限）が許す最大階数を
   入れます。
2. **建蔽率で絞る**: 建築面積の上限を超える場合、使うマスを選び直します。
   このとき「積める階数が多いマス」を優先して残すので、同じ建築面積でも
   容積を大きく取れます。
3. **容積率で頭打ち**: 延床面積の上限を超えないよう、上の階から削ります。
4. **日影規制に合わせる**: 超過している測定点について、**その点を実際に
   日影にしているマスだけ**を特定して下げます。建物全体を一律に低くする
   ようなことはしません。

## 4がこの実装の要点

`shadow_index.py` が (測定点, 時刻, マス) ごとの「しきい値高さ」を持って
いるので、超過した測定点に対して

- どの時刻が日影になっているか
- その時刻に日影を作っているマスはどれか
- それらを何m下げれば日影が外れるか

を正確に出せます。時刻ごとに「解消コスト（失う体積）」を計算し、**最も安い
時刻から順に解消**していきます。結果として、日影に効いている北側や特定方向の
マスだけが段状に低くなり、他は上限のまま残ります。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon

from .far import FarResult, compute_far
from .massing import Block, footprint_area, max_height, total_floor_area, total_volume
from .mesh import BuildableArea, assign_height_limits, build_mesh
from .regulations.shadow import ShadowLineResult, ShadowRegulationSpec, compute_shadow_hours
from .shadow_index import ShadowIndex, build_shadow_index
from .site import Site


@dataclass
class OptimizeOptions:
    cell_size_x_m: float = 3.0
    cell_size_y_m: float = 3.0
    mesh_angle_deg: float = 0.0
    coverage_threshold: float = 0.5
    use_sky_ratio: bool = False
    max_iterations: int = 4000


@dataclass
class OptimizeResult:
    site: Site
    area: BuildableArea | None
    floors: np.ndarray                 # マスごとの階数
    blocks: list[Block]
    far: FarResult
    shadow_spec: ShadowRegulationSpec | None
    shadow_lines: list[ShadowLineResult] = field(default_factory=list)
    coverage_limited: bool = False
    far_limited: bool = False
    shadow_limited: bool = False
    volume_removed_by_shadow_m3: float = 0.0
    notes: list[str] = field(default_factory=list)

    # --- 集計 -------------------------------------------------------
    @property
    def volume_m3(self) -> float:
        return total_volume(self.blocks)

    @property
    def max_height_m(self) -> float:
        return max_height(self.blocks)

    @property
    def building_area_m2(self) -> float:
        return footprint_area(self.blocks)

    @property
    def total_floor_area_m2(self) -> float:
        return total_floor_area(self.blocks, self.site.floor_height_m)

    @property
    def far_achieved(self) -> float:
        return self.total_floor_area_m2 / self.site.area_m2 if self.site.area_m2 else 0.0

    @property
    def far_attainment(self) -> float:
        """指定容積率（道路幅員制限後）に対する達成率。"""
        target = self.far.effective_far
        return self.far_achieved / target if target > 0 else 0.0

    @property
    def shadow_ok(self) -> bool:
        return all(line.ok for line in self.shadow_lines) if self.shadow_lines else True

    def summary_lines_ja(self) -> list[str]:
        site = self.site
        lines = [
            f"敷地面積: {site.area_m2:.1f} m2",
            f"建築面積: {self.building_area_m2:.1f} m2"
            f"（建蔽率の上限 {site.max_building_area_m2():.1f} m2）",
            f"延床面積(概算): {self.total_floor_area_m2:.1f} m2"
            f"（容積率の上限 {site.max_total_floor_area_m2():.1f} m2）",
            f"達成容積率: {self.far_achieved * 100:.0f}%"
            f"（上限 {self.far.effective_far * 100:.0f}% に対して {self.far_attainment * 100:.0f}%）",
            f"最高高さ: {self.max_height_m:.2f} m",
            f"体積: {self.volume_m3:.1f} m3",
        ]
        if self.area is not None:
            used = int((self.floors > 0).sum())
            lines.append(
                f"メッシュ: {self.area.cell_size_x_m:.1f}m × {self.area.cell_size_y_m:.1f}m / "
                f"使用{used}マス（全{len(self.area.cells)}マス）/ "
                f"最高{int(self.floors.max()) if self.floors.size else 0}階"
            )
        binding = []
        if self.coverage_limited:
            binding.append("建蔽率")
        if self.far_limited:
            binding.append("容積率")
        if self.shadow_limited:
            binding.append("日影規制")
        lines.append("上限に達した規制: " + ("・".join(binding) if binding else "なし"))
        if self.shadow_limited:
            lines.append(f"　日影規制で削った体積: {self.volume_removed_by_shadow_m3:.1f} m3")
        for line in self.shadow_lines:
            label = "5m〜10m" if line.distance_m == 5.0 else "10m超"
            lines.append(
                f"　{label}の測定線（{line.max_hours}時間以内）: "
                f"{'適合' if line.ok else '不適合'} / 最大 {line.worst_hours:.2f}時間"
            )
        lines.extend(self.far.notes)
        lines.extend(self.notes)
        return lines


# --- 各段階 ---------------------------------------------------------

def _apply_coverage_cap(area: BuildableArea, floors: np.ndarray, max_area_m2: float) -> bool:
    """建築面積の上限に収まるよう、使うマスを選び直す。

    積める階数が多いマスを優先して残します。同じ建築面積なら、高く積める
    ところを使った方が容積を稼げるためです。
    """
    cell_areas = np.array([c.area_m2 for c in area.cells])
    used = floors > 0
    if not used.any():
        return False
    if float(cell_areas[used].sum()) <= max_area_m2 + 1e-9:
        return False

    # 階数の多い順（同数なら面積の小さい順）に、上限まで採用する
    order = sorted(
        (i for i in range(len(area.cells)) if used[i]),
        key=lambda i: (-floors[i], cell_areas[i]),
    )
    kept_area = 0.0
    keep = np.zeros(len(area.cells), dtype=bool)
    for i in order:
        if kept_area + cell_areas[i] <= max_area_m2 + 1e-9:
            keep[i] = True
            kept_area += cell_areas[i]
    floors[~keep] = 0
    return True


def _apply_far_cap(area: BuildableArea, floors: np.ndarray, max_floor_area_m2: float) -> bool:
    """延床面積の上限を超えないよう、高い柱から1階ずつ削る。"""
    cell_areas = np.array([c.area_m2 for c in area.cells])
    total = float((floors * cell_areas).sum())
    if total <= max_floor_area_m2 + 1e-9:
        return False
    while total > max_floor_area_m2 + 1e-9:
        candidates = np.where(floors > 0)[0]
        if candidates.size == 0:
            break
        # 最も高い柱から削る（低層部を残した方が形が素直になる）
        tallest = candidates[np.argmax(floors[candidates])]
        floors[tallest] -= 1
        total -= float(cell_areas[tallest])
    return True


def _resolve_shadow(
    area: BuildableArea, floors: np.ndarray, index: ShadowIndex,
    floor_height_m: float, max_iterations: int,
) -> tuple[bool, float, list[str]]:
    """超過している測定点について、原因となるマスだけを下げる。

    戻り値は (日影が制約になったか, 削った体積, メモ)。
    """
    cell_areas = np.array([c.area_m2 for c in area.cells])
    removed_volume = 0.0
    touched = False
    notes: list[str] = []

    for _ in range(max_iterations):
        heights = floors * floor_height_m
        worst = index.worst(heights)
        if worst is None:
            break
        touched = True
        distance, point_index, hours, excess = worst
        limit = (index.spec.line_5m_max_hours if distance == 5.0
                 else index.spec.line_10m_max_hours)

        thresh = index.thresholds[distance][point_index]      # (時刻, マス)
        shadowed_now = (heights[None, :] >= thresh)           # 各時刻のマス別判定
        active_times = np.where(shadowed_now.any(axis=1))[0]
        if active_times.size == 0:
            break

        # 解消しなければならない時刻数
        need = int(math.ceil((hours - limit) / index.step_hours - 1e-9))
        if need <= 0:
            break

        # 時刻ごとの解消コスト（その時刻の影を消すために失う体積）
        costs = []
        for ti in active_times:
            offenders = np.where(shadowed_now[ti])[0]
            cost = 0.0
            plan = []
            for ci in offenders:
                # しきい値をわずかに下回る階数まで下げる
                target_floors = int(math.floor((thresh[ti, ci] - 1e-6) / floor_height_m))
                target_floors = max(0, min(target_floors, int(floors[ci])))
                drop = int(floors[ci]) - target_floors
                if drop > 0:
                    cost += drop * float(cell_areas[ci]) * floor_height_m
                    plan.append((ci, target_floors))
            if plan:
                costs.append((cost, ti, plan))

        if not costs:
            notes.append(
                "日影規制を満たすためにマスを下げようとしましたが、"
                "これ以上下げられる柱がありません（メッシュを細かくすると改善する場合があります）。"
            )
            break

        costs.sort(key=lambda c: c[0])
        for cost, _ti, plan in costs[:need]:
            for ci, target_floors in plan:
                if floors[ci] > target_floors:
                    removed_volume += (floors[ci] - target_floors) * cell_areas[ci] * floor_height_m
                    floors[ci] = target_floors
    else:
        notes.append(
            f"日影規制の解消が{max_iterations}回の調整で収束しませんでした。"
            "メッシュを粗くするか、条件を見直してください。"
        )

    return touched, removed_volume, notes


def _floors_to_blocks(area: BuildableArea, floors: np.ndarray, floor_height_m: float) -> list[Block]:
    """階数配列を、階ごとにまとめたブロックへ変換する。

    同じ階に存在するマスを1つの多角形に結合するので、ブロック数が階数分に
    収まり、3D表示や作図が軽くなります。
    """
    if floors.size == 0:
        return []
    blocks: list[Block] = []
    max_floor = int(floors.max())
    for level in range(max_floor):
        members = [area.cells[i].polygon for i in range(len(area.cells)) if floors[i] > level]
        if not members:
            continue
        merged = members[0]
        for poly in members[1:]:
            merged = merged.union(poly)
        polygons = [merged] if merged.geom_type == "Polygon" else list(merged.geoms)
        for poly in polygons:
            if isinstance(poly, Polygon) and poly.area > 1e-9:
                blocks.append(Block(
                    footprint=poly,
                    z_bottom=level * floor_height_m,
                    z_top=(level + 1) * floor_height_m,
                ))
    return blocks


# --- 本体 -----------------------------------------------------------

def optimize(
    site: Site,
    shadow_spec: ShadowRegulationSpec | None = None,
    options: OptimizeOptions | None = None,
) -> OptimizeResult:
    """敷地に建てられる最大容積を求める。"""
    opt = options or OptimizeOptions()
    far = compute_far(site)
    notes: list[str] = []

    area = build_mesh(
        site,
        cell_size_x_m=opt.cell_size_x_m,
        cell_size_y_m=opt.cell_size_y_m,
        angle_deg=opt.mesh_angle_deg,
        coverage_threshold=opt.coverage_threshold,
    )
    if area is None or not area.cells:
        notes.append(
            "壁面後退線で囲まれた建物外郭線が取れませんでした。"
            "壁面後退距離が大きすぎないか確認してください。"
        )
        return OptimizeResult(
            site=site, area=None, floors=np.zeros(0), blocks=[], far=far,
            shadow_spec=shadow_spec, notes=notes,
        )

    assign_height_limits(area, use_sky_ratio=opt.use_sky_ratio)
    floor_h = site.floor_height_m

    # 1. 高さ制限まで積む
    floors = np.array([c.max_floors for c in area.cells], dtype=int)
    if not floors.any():
        notes.append("斜線制限により、1階分の高さも確保できませんでした。")

    # 2. 建蔽率
    coverage_limited = _apply_coverage_cap(area, floors, site.max_building_area_m2())

    # 3. 容積率
    far_limited = _apply_far_cap(area, floors, site.max_total_floor_area_m2())

    # 4. 日影規制（原因となるマスだけを下げる）
    shadow_limited = False
    removed = 0.0
    if shadow_spec is not None and floors.any():
        index = build_shadow_index(site, area, shadow_spec)
        shadow_limited, removed, shadow_notes = _resolve_shadow(
            area, floors, index, floor_h, opt.max_iterations)
        notes.extend(shadow_notes)
        # 日影で削った結果、容積率の余地が空くことがあるので積み直しを試みる
        if shadow_limited:
            _refill_after_shadow(area, floors, index, site, floor_h)

    blocks = _floors_to_blocks(area, floors, floor_h)
    shadow_lines = (compute_shadow_hours(site, blocks, shadow_spec)
                    if shadow_spec is not None else [])

    return OptimizeResult(
        site=site, area=area, floors=floors, blocks=blocks, far=far,
        shadow_spec=shadow_spec, shadow_lines=shadow_lines,
        coverage_limited=coverage_limited, far_limited=far_limited,
        shadow_limited=shadow_limited, volume_removed_by_shadow_m3=removed,
        notes=notes,
    )


def _refill_after_shadow(
    area: BuildableArea, floors: np.ndarray, index: ShadowIndex,
    site: Site, floor_height_m: float, max_passes: int = 200,
) -> None:
    """日影で削った後、まだ余裕のあるマスに積み直す。

    日影に効いていないマス（南側など）は、削る必要がなかったのに容積率の
    頭打ちで低く抑えられている場合があります。上限・建蔽率・容積率・日影の
    すべてを満たす範囲で1階ずつ戻します。
    """
    cell_areas = np.array([c.area_m2 for c in area.cells])
    max_floors = np.array([c.max_floors for c in area.cells], dtype=int)
    far_cap = site.max_total_floor_area_m2()
    coverage_cap = site.max_building_area_m2()

    for _ in range(max_passes):
        used_area = float(cell_areas[floors > 0].sum())
        floor_area = float((floors * cell_areas).sum())
        if floor_area >= far_cap - 1e-9:
            return

        # 積める余地があり、体積の増分が大きい順に試す
        candidates = [
            i for i in range(len(area.cells))
            if floors[i] < max_floors[i]
            and (floors[i] > 0 or used_area + cell_areas[i] <= coverage_cap + 1e-9)
            and floor_area + cell_areas[i] <= far_cap + 1e-9
        ]
        if not candidates:
            return
        candidates.sort(key=lambda i: -cell_areas[i])

        for i in candidates:
            floors[i] += 1
            if index.is_compliant(floors * floor_height_m):
                break  # 1階積めたので次のパスへ
            floors[i] -= 1
        else:
            return  # どれも積めない
