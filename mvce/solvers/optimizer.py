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
4・5. **日影規制と天空率に合わせる**: `use_sky_ratio` を使わない場合は日影
   規制だけを見ます。既定（`envelope_family: "voxel"`）は、超過している
   測定点について**その点を実際に日影にしているマスだけ**を特定して下げる
   自由形です。建物全体を一律に低くするようなことはしません。
   `envelope_family: "lean_to" | "ridge"` にすると、代わりに**逆日影**
   （屋根越し・棟状パターン）で規則正しい1〜2枚の勾配面に沿って後退させます
   （`inverse/shadow_envelope.py`）。容積は自由形よりやや少なくなりますが、結果が
   建築的に成立する量塊になります。

   日影と天空率を**両方**使う場合は、順に解決するのではなく**同時に**
   動かします。voxel では1手ずつ交互に解消し（`_resolve_shadow_and_sky_jointly`）、
   lean_to/ridge では棟の探索そのものが両方の適合を条件にします
   （`inverse/shadow_envelope.py` の「天空率との同時最適化」）。片方を先に解消し
   切ってから他方に移ると、一方の是正がもう一方も満たしていたことに
   気づけず、削り込みが重複する場合があるためです。
6. **積み直す**: 4・5で削った結果あいた容積率の余地に、規制を満たす範囲で
   積み直します（voxelのときだけ。屋根形状パターンでは規則正しい形を
   崩さないよう行いません）。

## 4・5がこの実装の要点

`index/shadow_index.py` が (測定点, 時刻, マス) ごとの「しきい値高さ」を持って
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

from ..far import FarResult, compute_far
from ..zoning import UndeterminedRegulation
from ..index.shadow_index import ShadowIndex, build_shadow_index
from ..index.sky_index import SkyIndex, SkyRatioSummary, build_sky_index, summarize
from ..inverse.shadow_envelope import RoofPlaneSpec, search_roof_envelope
from ..massing import Block, footprint_area, max_height, total_floor_area, total_volume
from ..mesh import BuildableArea, assign_height_limits, build_mesh
from ..regulations.shadow import ShadowLineResult, ShadowRegulationSpec, compute_shadow_hours
from ..site import Site

#: 日影規制への対応方法。
#:   voxel   … マスごとに独立に下げる自由形（既定・最も容積を稼げる）
#:   lean_to … 屋根越しパターン（片流れ）。逆日影の建築的な量塊
#:   ridge   … 棟状パターン（切妻）。lean_to を含む一般形
ENVELOPE_FAMILIES = ("voxel", "lean_to", "ridge")


@dataclass
class OptimizeOptions:
    cell_size_x_m: float = 3.0
    cell_size_y_m: float = 3.0
    mesh_angle_deg: float = 0.0
    coverage_threshold: float = 0.5
    use_sky_ratio: bool = False
    max_iterations: int = 4000
    #: 天空率の測定点の間隔(m)と方位の分割数（use_sky_ratio のときだけ使う）
    sky_ratio_interval_m: float = 4.0
    sky_ratio_n_azimuth: int = 72
    #: 日影規制への対応方法。ENVELOPE_FAMILIES のいずれか。
    envelope_family: str = "voxel"
    #: 屋根形状（lean_to/ridge）を探索するときのパラメータ。既定は inverse/shadow_envelope.py 参照。
    roof_angle_span_deg: float = 15.0
    roof_angle_step_deg: float = 7.5
    roof_offset_steps: int = 7
    roof_pitch_candidates_deg: tuple = (20.0, 27.0, 35.0, 45.0)
    roof_far_pitch_candidates_deg: tuple = (0.0, 20.0, 35.0)
    #: 棟の向きを固定したい場合（実務者が既に方向を決めている場合）に指定する
    roof_fixed_low_azimuth_deg: float | None = None


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
    sky_ratio_limited: bool = False
    volume_removed_by_shadow_m3: float = 0.0
    volume_removed_by_sky_ratio_m3: float = 0.0
    sky_ratio: SkyRatioSummary | None = None
    #: lean_to/ridge を使ったときの屋根形状。voxel（既定）では None。
    roof_spec: RoofPlaneSpec | None = None
    #: 屋根形状が天空率も同じ棟高で満たしたか（True なら追加のフリーフォーム
    #: 是正は無し＝完全に規則正しい形のまま）。roof_spec が None なら意味を持たない。
    roof_includes_sky_ratio: bool = False
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

    @property
    def sky_ratio_ok(self) -> bool:
        """天空率を使った場合に、すべての測定点で Ps ≧ Pr を満たしているか。

        天空率を使っていない場合（斜線制限をそのまま守っている場合）は、
        判定の必要がないので True を返します。
        """
        return self.sky_ratio.ok if self.sky_ratio is not None else True

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
        if self.sky_ratio_limited:
            binding.append("天空率")
        lines.append("上限に達した規制: " + ("・".join(binding) if binding else "なし"))
        if self.roof_spec is not None:
            tail = "（天空率も同じ棟高で同時に満たしています）" if self.roof_includes_sky_ratio else ""
            lines.append(f"　逆日影: {self.roof_spec.describe_ja()}{tail}")
        if self.shadow_limited:
            lines.append(f"　日影規制で削った体積: {self.volume_removed_by_shadow_m3:.1f} m3")
        if self.sky_ratio_limited:
            lines.append(f"　天空率で削った体積: {self.volume_removed_by_sky_ratio_m3:.1f} m3")
        for line in self.shadow_lines:
            label = "5m〜10m" if line.distance_m == 5.0 else "10m超"
            lines.append(
                f"　{label}の測定線（{line.max_hours}時間以内）: "
                f"{'適合' if line.ok else '不適合'} / 最大 {line.worst_hours:.2f}時間"
            )
        if self.sky_ratio is not None:
            sky = self.sky_ratio
            lines.append(
                f"　天空率（法56条7項・{sky.n_points}点で判定）: "
                f"{'適合' if sky.ok else '不適合'} / "
                f"最小余裕 {sky.worst_margin:+.2f}%"
                f"（Ps {sky.worst_ps:.2f}% ≧ Pr {sky.worst_pr:.2f}%）"
            )
        lines.extend(self.far.notes)
        lines.extend(self.notes)
        return lines


def _ground_plane_notes(site) -> list[str]:
    """令2条2項の地盤面についての注記。

    **高さはまだ Z=0 から測っています。** 地盤面の算定（`ground.py`）は
    できるようになりましたが、斜線・絶対高さ・日影の測定面をそこから測る
    ところまでは繋いでいません。平坦地では差が出ませんが、地盤の高さを
    与えた敷地では黙って無視するのが一番まずいので、注記を出します。
    """
    levels = getattr(site, "ground_levels", None)
    if not levels:
        return []
    span = max(levels) - min(levels)
    if span <= 1e-9:
        if abs(levels[0]) <= 1e-9:
            return []
        return [
            f"地盤の高さが一様に {levels[0]:+.2f}m ですが、高さはすべて"
            "Z=0 から測っています（一様なので相対的な結果は変わりません）。"
        ]
    try:
        plane = site.ground_plane()
    except UndeterminedRegulation as e:
        return [
            f"令2条2項の地盤面が求まりません: {e}",
            "**高さの判定は Z=0 を地盤面として行っています。**"
            "傾斜地では結果が実際とずれます。",
        ]
    return [
        f"令2条2項の平均地盤面: {plane.level_m:+.3f}m"
        f"（接地位置の高低差 {span:.2f}m）。"
        "**ただし高さの判定はまだ Z=0 から測っています。**"
        "斜線・絶対高さ・日影の測定面を平均地盤面から測るところまでは"
        "繋いでいないので、傾斜地では結果が実際とずれます。",
    ]


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


def _shadow_step(
    area: BuildableArea, floors: np.ndarray, index: ShadowIndex, floor_height_m: float,
) -> tuple[bool, float, str | None, bool]:
    """日影規制の是正を1手だけ進める（最も超過している測定点を1つ解消する）。

    戻り値は (何か直したか, 削った体積, 追記するメモ, 完全に解消したか)。
    `_resolve_shadow` と `_resolve_shadow_and_sky_jointly` の両方から使う、
    最小の作業単位です。
    """
    cell_areas = np.array([c.area_m2 for c in area.cells])
    heights = floors * floor_height_m
    worst = index.worst(heights)
    if worst is None:
        return False, 0.0, None, True

    distance, point_index, hours, excess = worst
    limit = (index.spec.line_5m_max_hours if distance == 5.0
             else index.spec.line_10m_max_hours)

    thresh = index.thresholds[distance][point_index]      # (時刻, マス)
    shadowed_now = (heights[None, :] >= thresh)           # 各時刻のマス別判定
    active_times = np.where(shadowed_now.any(axis=1))[0]
    if active_times.size == 0:
        return False, 0.0, None, False

    # 解消しなければならない時刻数
    need = int(math.ceil((hours - limit) / index.step_hours - 1e-9))
    if need <= 0:
        return False, 0.0, None, False

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
        return False, 0.0, (
            "日影規制を満たすためにマスを下げようとしましたが、"
            "これ以上下げられる柱がありません（メッシュを細かくすると改善する場合があります）。"
        ), False

    costs.sort(key=lambda c: c[0])
    removed = 0.0
    for cost, _ti, plan in costs[:need]:
        for ci, target_floors in plan:
            if floors[ci] > target_floors:
                removed += (floors[ci] - target_floors) * cell_areas[ci] * floor_height_m
                floors[ci] = target_floors
    return True, removed, None, False


def _resolve_shadow(
    area: BuildableArea, floors: np.ndarray, index: ShadowIndex,
    floor_height_m: float, max_iterations: int,
) -> tuple[bool, float, list[str]]:
    """超過している測定点について、原因となるマスだけを下げる。

    戻り値は (日影が制約になったか, 削った体積, メモ)。
    """
    removed_volume = 0.0
    touched = False
    notes: list[str] = []

    for _ in range(max_iterations):
        acted, removed, note, done = _shadow_step(area, floors, index, floor_height_m)
        if note:
            notes.append(note)
        if acted:
            touched = True
            removed_volume += removed
        if done or not acted:
            break
    else:
        notes.append(
            f"日影規制の解消が{max_iterations}回の調整で収束しませんでした。"
            "メッシュを粗くするか、条件を見直してください。"
        )

    return touched, removed_volume, notes


def _sky_step(
    area: BuildableArea, floors: np.ndarray, index: SkyIndex, floor_height_m: float,
) -> tuple[bool, float, str | None, bool]:
    """天空率の是正を1手だけ進める（稜線を作っているマスを1階だけ下げる）。

    戻り値は (何か直したか, 削った体積, 追記するメモ, 完全に解消したか)。
    """
    cell_areas = np.array([c.area_m2 for c in area.cells])
    heights = floors * floor_height_m
    worst = index.worst(heights)
    if worst is None:
        return False, 0.0, None, True

    point_index, ps_now, _deficit = worst
    candidates = [c for c in index.ridge_cells(point_index, heights) if floors[c] > 0]
    best = None
    for ci in candidates:
        trial = heights.copy()
        trial[ci] -= floor_height_m
        gain = index.ps_at(point_index, trial) - ps_now
        if gain <= 1e-12:
            continue
        cost = float(cell_areas[ci]) * floor_height_m
        score = gain / cost if cost > 0 else 0.0
        if best is None or score > best[0]:
            best = (score, ci, cost)

    if best is None:
        return False, 0.0, (
            "天空率を満たすためにマスを下げようとしましたが、"
            "これ以上下げても改善しませんでした（壁面後退距離を増やすと"
            "適合しやすくなります）。"
        ), False

    _score, ci, cost = best
    floors[ci] -= 1
    return True, cost, None, False


def _resolve_sky_ratio(
    area: BuildableArea, floors: np.ndarray, index: SkyIndex,
    floor_height_m: float, max_iterations: int,
) -> tuple[bool, float, list[str]]:
    """Ps < Pr の測定点について、稜線を作っているマスだけを下げる。

    日影の解消（`_resolve_shadow`）と同じ考え方です。ある測定点の天空率は
    **各方位の稜線を作っているマス**だけで決まるので、そこに含まれないマスを
    いくら下げても改善しません。候補の中から「天空率の改善 / 失う体積」が
    最も大きいマスを1階ずつ下げます。

    戻り値は (天空率が制約になったか, 削った体積, メモ)。
    """
    removed_volume = 0.0
    touched = False
    notes: list[str] = []

    for _ in range(max_iterations):
        acted, removed, note, done = _sky_step(area, floors, index, floor_height_m)
        if note:
            notes.append(note)
        if acted:
            touched = True
            removed_volume += removed
        if done or not acted:
            break
    else:
        notes.append(
            f"天空率の解消が{max_iterations}回の調整で収束しませんでした。"
            "メッシュを粗くするか、条件を見直してください。"
        )

    return touched, removed_volume, notes


def _resolve_shadow_and_sky_jointly(
    area: BuildableArea, floors: np.ndarray,
    shadow_index: ShadowIndex, sky_index: SkyIndex,
    floor_height_m: float, max_iterations: int,
) -> tuple[bool, float, bool, float, list[str]]:
    """日影と天空率を**1手ずつ交互に**解消する（両方を同時に動かす1本の探索）。

    従来は「日影をすべて解消してから天空率をすべて解消する」という2段階
    でした。この順番だと、日影の是正で下げた1手が天空率もついでに満たして
    いたとしても、それが分かるのは天空率のフェーズに入ってからで、既に
    別のマスを下げて払ってしまった分は戻せません（逆に天空率が先でも同様）。

    1手ずつ交互に進めれば、次の手を選ぶときには常に**両方の最新の状態**を
    見て判断できます。どちらの手も高さを**下げる**方向にしか動かさないので、
    片方の是正がもう片方を悪化させることはありません
    （`index/shadow_index.py` / `index/sky_index.py` の単調性）。これが交互に進めても
    安全な理由です。

    戻り値は (日影が制約になったか, 日影で削った体積,
             天空率が制約になったか, 天空率で削った体積, メモ)。
    """
    removed_shadow = 0.0
    removed_sky = 0.0
    shadow_touched = False
    sky_touched = False
    shadow_done = False
    sky_done = False
    notes: list[str] = []

    for _ in range(max_iterations):
        if shadow_done and sky_done:
            break
        if not shadow_done:
            acted, removed, note, done = _shadow_step(area, floors, shadow_index, floor_height_m)
            if note:
                notes.append(note)
            if acted:
                shadow_touched = True
                removed_shadow += removed
            shadow_done = done or not acted
        if not sky_done:
            acted, removed, note, done = _sky_step(area, floors, sky_index, floor_height_m)
            if note:
                notes.append(note)
            if acted:
                sky_touched = True
                removed_sky += removed
            sky_done = done or not acted
    else:
        notes.append(
            f"日影規制・天空率の同時解消が{max_iterations}回の調整で収束しませんでした。"
            "メッシュを粗くするか、条件を見直してください。"
        )

    return shadow_touched, removed_shadow, sky_touched, removed_sky, notes


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
    if opt.envelope_family not in ENVELOPE_FAMILIES:
        raise ValueError(f"envelope_family は {'/'.join(ENVELOPE_FAMILIES)} のいずれかにしてください")
    far = compute_far(site)
    notes: list[str] = []
    notes.extend(_ground_plane_notes(site))
    if shadow_spec is not None:
        from ..regulations.shadow import deemed_average_ground_level_m

        notes.extend(deemed_average_ground_level_m(site)[1])

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
    # 天空率で斜線制限を外すと上限が無限になり得るので、1本の柱だけで容積率を
    # 使い切る階数で頭を抑える。以降の削り込みが現実的な回数で終わる。
    _cap_by_far(area, floors, site.max_total_floor_area_m2())

    # 2. 建蔽率
    coverage_limited = _apply_coverage_cap(area, floors, site.max_building_area_m2())

    # 3. 容積率
    far_limited = _apply_far_cap(area, floors, site.max_total_floor_area_m2())

    # 4・5. 日影規制と天空率
    shadow_index = None
    sky_index = None
    shadow_limited = False
    sky_limited = False
    removed = 0.0
    removed_sky = 0.0
    roof_spec: RoofPlaneSpec | None = None
    roof_includes_sky_ratio = False
    use_roof_pattern = opt.envelope_family != "voxel"
    has_shadow = shadow_spec is not None and floors.any()
    has_sky = opt.use_sky_ratio and floors.any()

    if use_roof_pattern:
        if has_shadow:
            # 屋根越し／棟状パターン：規則正しい1〜2枚の勾配面で後退させる。
            # 天空率も同時に使う場合は、同じ棟の探索に天空率の適合も条件として
            # 加える（inverse/shadow_envelope.py の「天空率との同時最適化」）。1本の探索で
            # 両方満たせなければ、日影だけを満たす形に戻し、天空率は後段で
            # フリーフォームに補う。
            before = floors.copy()
            if has_sky:
                sky_index = build_sky_index(
                    site, area, interval_m=opt.sky_ratio_interval_m,
                    n_azimuth=opt.sky_ratio_n_azimuth)
            roof_result = search_roof_envelope(
                site, area, shadow_spec, floors, floor_h,
                pattern=opt.envelope_family,
                angle_span_deg=opt.roof_angle_span_deg,
                angle_step_deg=opt.roof_angle_step_deg,
                offset_steps=opt.roof_offset_steps,
                pitch_candidates_deg=opt.roof_pitch_candidates_deg,
                far_pitch_candidates_deg=opt.roof_far_pitch_candidates_deg,
                fixed_low_azimuth_deg=opt.roof_fixed_low_azimuth_deg,
                sky_index=sky_index,
            )
            floors = roof_result.floors
            roof_spec = roof_result.spec
            roof_includes_sky_ratio = roof_result.sky_ratio_included
            shadow_limited = roof_spec is not None
            cell_areas = np.array([c.area_m2 for c in area.cells])
            removed = float(((before - floors) * cell_areas).sum()) * floor_h
            notes.extend(roof_result.notes)
        elif has_sky:
            sky_index = build_sky_index(
                site, area, interval_m=opt.sky_ratio_interval_m,
                n_azimuth=opt.sky_ratio_n_azimuth)

        # 天空率がまだ解消されていなければ（日影の指定が無かった、または
        # 屋根形状の探索が両立する組み合わせを見つけられなかった）フリー
        # フォームで補う。屋根形状が既に両立している場合はここを飛ばす。
        if has_sky and sky_index is not None and not roof_includes_sky_ratio and floors.any():
            sky_limited, removed_sky, sky_notes = _resolve_sky_ratio(
                area, floors, sky_index, floor_h, opt.max_iterations)
            notes.extend(sky_notes)

    elif has_shadow and has_sky:
        # ボクセル自由形：日影と天空率を**1手ずつ交互に**解消する（両方を
        # 同時に動かす1本の探索）。片方を先に解消し切ってから他方に移ると、
        # 一方の是正がもう一方も満たしていた場合の重複した削り込みに
        # 気づけない（`_resolve_shadow_and_sky_jointly` のdocstring参照）。
        shadow_index = build_shadow_index(site, area, shadow_spec)
        sky_index = build_sky_index(
            site, area, interval_m=opt.sky_ratio_interval_m,
            n_azimuth=opt.sky_ratio_n_azimuth)
        shadow_limited, removed, sky_limited, removed_sky, joint_notes = (
            _resolve_shadow_and_sky_jointly(
                area, floors, shadow_index, sky_index, floor_h, opt.max_iterations))
        notes.extend(joint_notes)

    else:
        if has_shadow:
            shadow_index = build_shadow_index(site, area, shadow_spec)
            shadow_limited, removed, shadow_notes = _resolve_shadow(
                area, floors, shadow_index, floor_h, opt.max_iterations)
            notes.extend(shadow_notes)
        if has_sky:
            sky_index = build_sky_index(
                site, area, interval_m=opt.sky_ratio_interval_m,
                n_azimuth=opt.sky_ratio_n_azimuth)
            sky_limited, removed_sky, sky_notes = _resolve_sky_ratio(
                area, floors, sky_index, floor_h, opt.max_iterations)
            notes.extend(sky_notes)

    # 6. 削った結果あいた容積率の余地に積み直す（日影・天空率の両方を守る）
    #    屋根形状パターンでは行わない。積み直すと規則正しい形が崩れるうえ、
    #    このパスには日影のフリーフォーム版インデックス（shadow_index）が無く、
    #    積み直しの適合チェックが日影を見落とす恐れがあるため。
    if not use_roof_pattern and (shadow_limited or sky_limited):
        _refill(area, floors, site, floor_h, shadow_index, sky_index)

    blocks = _floors_to_blocks(area, floors, floor_h)
    shadow_lines = (compute_shadow_hours(site, blocks, shadow_spec)
                    if shadow_spec is not None else [])
    sky_summary = (summarize(sky_index, floors * floor_h)
                   if sky_index is not None else None)
    if sky_summary is not None and not sky_summary.ok:
        notes.append(
            f"天空率が不足したままです（最小余裕 {sky_summary.worst_margin:+.2f}%）。"
            "壁面後退距離を増やすか、斜線制限のまま（use_sky_ratio: false）で"
            "検討してください。"
        )

    return OptimizeResult(
        site=site, area=area, floors=floors, blocks=blocks, far=far,
        shadow_spec=shadow_spec, shadow_lines=shadow_lines,
        coverage_limited=coverage_limited, far_limited=far_limited,
        shadow_limited=shadow_limited, sky_ratio_limited=sky_limited,
        volume_removed_by_shadow_m3=removed,
        volume_removed_by_sky_ratio_m3=removed_sky,
        sky_ratio=sky_summary, roof_spec=roof_spec,
        roof_includes_sky_ratio=roof_includes_sky_ratio, notes=notes,
    )


def _cap_by_far(area: BuildableArea, floors: np.ndarray, max_floor_area_m2: float) -> None:
    """1本の柱だけで容積率を使い切る階数を上限にする。

    `use_sky_ratio` で斜線制限を外すと高さ上限が無限になることがあり、
    そのままでは削り込みの回数が現実的でなくなります。容積率を超える階数は
    どのみち残らないので、先に頭を抑えます。
    """
    for i, cell in enumerate(area.cells):
        if cell.area_m2 <= 0:
            floors[i] = 0
            continue
        ceiling = int(math.ceil(max_floor_area_m2 / cell.area_m2))
        if floors[i] > ceiling:
            floors[i] = ceiling


def _refill(
    area: BuildableArea, floors: np.ndarray, site: Site, floor_height_m: float,
    shadow_index: ShadowIndex | None = None, sky_index: SkyIndex | None = None,
    max_passes: int = 200,
) -> None:
    """日影・天空率で削った後、まだ余裕のあるマスに積み直す。

    規制に効いていないマス（南側など）は、削る必要がなかったのに容積率の
    頭打ちで低く抑えられている場合があります。上限・建蔽率・容積率に加えて
    **日影と天空率の両方**を満たす範囲で1階ずつ戻します。
    """
    def feasible(heights: np.ndarray) -> bool:
        if shadow_index is not None and not shadow_index.is_compliant(heights):
            return False
        if sky_index is not None and not sky_index.is_compliant(heights):
            return False
        return True

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
            if feasible(floors * floor_height_m):
                break  # 1階積めたので次のパスへ
            floors[i] -= 1
        else:
            return  # どれも積めない
