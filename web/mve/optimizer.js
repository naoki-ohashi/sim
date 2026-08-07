/* MVE ボクセル最適化（JavaScript版）
 *
 * Python版 mve/optimizer.py の移植。engine.js を先に読み込んでください。
 *
 *   敷地 → 壁面後退線 → 建物外郭線 → メッシュ → 各マスの階数
 *
 * 日影規制を超えた場合は、しきい値インデックスで**原因になっているマスだけ**を
 * 特定して下げます（建物全体を一律に低くはしません）。
 */
(function (global) {
  'use strict';

  const E = global.MveEngine;
  if (!E) throw new Error('engine.js を先に読み込んでください');

  // 建蔽率: 積める階数が多いマスを優先して残す
  function applyCoverageCap(area, floors, maxAreaM2) {
    const areas = area.cells.map(c => c.areaM2);
    let used = 0;
    for (let i = 0; i < floors.length; i++) if (floors[i] > 0) used += areas[i];
    if (used <= maxAreaM2 + 1e-9) return false;

    const order = [];
    for (let i = 0; i < floors.length; i++) if (floors[i] > 0) order.push(i);
    order.sort((a, b) => (floors[b] - floors[a]) || (areas[a] - areas[b]));

    const keep = new Uint8Array(floors.length);
    let kept = 0;
    for (const i of order) {
      if (kept + areas[i] <= maxAreaM2 + 1e-9) { keep[i] = 1; kept += areas[i]; }
    }
    for (let i = 0; i < floors.length; i++) if (!keep[i]) floors[i] = 0;
    return true;
  }

  // 容積率: 高い柱から1階ずつ削る
  function applyFarCap(area, floors, maxFloorAreaM2) {
    const areas = area.cells.map(c => c.areaM2);
    let total = 0;
    for (let i = 0; i < floors.length; i++) total += floors[i] * areas[i];
    if (total <= maxFloorAreaM2 + 1e-9) return false;
    while (total > maxFloorAreaM2 + 1e-9) {
      let best = -1;
      for (let i = 0; i < floors.length; i++) {
        if (floors[i] > 0 && (best < 0 || floors[i] > floors[best])) best = i;
      }
      if (best < 0) break;
      floors[best] -= 1;
      total -= areas[best];
    }
    return true;
  }

  /* 日影: 超過している測定点について、原因のマスだけを下げる。
   * 時刻ごとに「その時刻の日影を消すために失う体積」を出し、安い順に処理する。
   */
  function resolveShadow(area, floors, index, floorHeightM, maxIterations) {
    const areas = area.cells.map(c => c.areaM2);
    const n = index.nCells;
    let removed = 0, touched = false;
    const notes = [];

    for (let iter = 0; iter < maxIterations; iter++) {
      const heights = floors.map(f => f * floorHeightM);
      const worst = E.worstViolation(index, heights);
      if (!worst) break;
      touched = true;

      const table = worst.line.tables[worst.pointIndex];
      const need = Math.ceil((worst.hours - worst.line.maxHours) / index.stepHours - 1e-9);
      if (need <= 0) break;

      const costs = [];
      for (let ti = 0; ti < index.hours.length; ti++) {
        const base = ti * n;
        const plan = [];
        let cost = 0;
        let shadowed = false;
        for (let ci = 0; ci < n; ci++) {
          if (heights[ci] >= table[base + ci]) {
            shadowed = true;
            const target = Math.max(0, Math.min(
              Math.floor((table[base + ci] - 1e-6) / floorHeightM), floors[ci]));
            const drop = floors[ci] - target;
            if (drop > 0) { cost += drop * areas[ci] * floorHeightM; plan.push([ci, target]); }
          }
        }
        if (shadowed && plan.length) costs.push({ cost, plan });
      }

      if (!costs.length) {
        notes.push('日影規制を満たすために下げられる柱がこれ以上ありません。'
                 + 'メッシュを細かくすると改善する場合があります。');
        break;
      }
      costs.sort((a, b) => a.cost - b.cost);
      for (const { plan } of costs.slice(0, need)) {
        for (const [ci, target] of plan) {
          if (floors[ci] > target) {
            removed += (floors[ci] - target) * areas[ci] * floorHeightM;
            floors[ci] = target;
          }
        }
      }
    }
    return { touched, removed, notes };
  }

  // 日影で削った後、効いていないマスに積み直す
  function refillAfterShadow(area, floors, index, site, floorHeightM, maxPasses) {
    const areas = area.cells.map(c => c.areaM2);
    const caps = area.cells.map(c => c.maxFloors);
    const farCap = E.maxFloorArea(site);
    const coverageCap = E.maxBuildingArea(site);

    for (let pass = 0; pass < (maxPasses || 200); pass++) {
      let usedArea = 0, floorArea = 0;
      for (let i = 0; i < floors.length; i++) {
        if (floors[i] > 0) usedArea += areas[i];
        floorArea += floors[i] * areas[i];
      }
      if (floorArea >= farCap - 1e-9) return;

      const candidates = [];
      for (let i = 0; i < floors.length; i++) {
        if (floors[i] >= caps[i]) continue;
        if (floors[i] === 0 && usedArea + areas[i] > coverageCap + 1e-9) continue;
        if (floorArea + areas[i] > farCap + 1e-9) continue;
        candidates.push(i);
      }
      if (!candidates.length) return;
      candidates.sort((a, b) => areas[b] - areas[a]);

      let placed = false;
      for (const i of candidates) {
        floors[i] += 1;
        if (E.isShadowCompliant(index, floors.map(f => f * floorHeightM))) { placed = true; break; }
        floors[i] -= 1;
      }
      if (!placed) return;
    }
  }

  // 階ごとにマスをまとめてブロック化（3D表示用）
  function floorsToBlocks(area, floors, floorHeightM) {
    const maxFloor = floors.reduce((m, f) => Math.max(m, f), 0);
    const blocks = [];
    for (let level = 0; level < maxFloor; level++) {
      const rects = [];
      for (let i = 0; i < floors.length; i++) if (floors[i] > level) rects.push(area.cells[i].rect);
      if (rects.length) {
        blocks.push({ rects, zBottom: level * floorHeightM, zTop: (level + 1) * floorHeightM });
      }
    }
    return blocks;
  }

  function optimize(site, shadowSpec, options) {
    const opt = Object.assign({
      cellSizeXM: 3.0, cellSizeYM: 3.0, coverageThreshold: 0.5,
      useSkyRatio: false, maxIterations: 4000,
    }, options || {});

    const far = E.computeFar(site);
    const notes = [];
    const area = E.buildMesh(site, opt);
    if (!area || !area.cells.length) {
      notes.push('壁面後退線で囲まれた建物外郭線が取れませんでした。'
               + '壁面後退距離が大きすぎないか確認してください。');
      return { site, area: null, floors: [], blocks: [], far, notes,
               shadowLines: [], coverageLimited: false, farLimited: false,
               shadowLimited: false, removedByShadow: 0 };
    }

    E.assignHeightLimits(site, area, opt.useSkyRatio);
    const fh = site.floorHeightM;
    const floors = area.cells.map(c => c.maxFloors);
    if (!floors.some(f => f > 0)) notes.push('斜線制限により、1階分の高さも確保できませんでした。');

    const coverageLimited = applyCoverageCap(area, floors, E.maxBuildingArea(site));
    const farLimited = applyFarCap(area, floors, E.maxFloorArea(site));

    let shadowLimited = false, removed = 0, shadowLines = [];
    if (shadowSpec && floors.some(f => f > 0)) {
      const index = E.buildShadowIndex(site, area, shadowSpec);
      const res = resolveShadow(area, floors, index, fh, opt.maxIterations);
      shadowLimited = res.touched;
      removed = res.removed;
      notes.push(...res.notes);
      if (shadowLimited) refillAfterShadow(area, floors, index, site, fh);
      shadowLines = E.shadowSummary(index, floors.map(f => f * fh));
    }

    return {
      site, area, floors, blocks: floorsToBlocks(area, floors, fh), far,
      shadowLines, coverageLimited, farLimited, shadowLimited,
      removedByShadow: removed, notes,
    };
  }

  // ===== 集計とサマリー ===============================================
  function totalVolume(result) {
    const areas = result.area ? result.area.cells.map(c => c.areaM2) : [];
    let v = 0;
    for (let i = 0; i < result.floors.length; i++) v += result.floors[i] * areas[i] * result.site.floorHeightM;
    return v;
  }
  function buildingArea(result) {
    const areas = result.area ? result.area.cells.map(c => c.areaM2) : [];
    let a = 0;
    for (let i = 0; i < result.floors.length; i++) if (result.floors[i] > 0) a += areas[i];
    return a;
  }
  const totalFloorArea = r => totalVolume(r) / r.site.floorHeightM;
  const maxHeight = r => (r.floors.length ? Math.max(...r.floors) * r.site.floorHeightM : 0);

  function summaryLinesJa(result) {
    const site = result.site;
    const area = E.siteArea(site);
    const lines = [
      `敷地面積: ${area.toFixed(1)} m2`,
      `建築面積: ${buildingArea(result).toFixed(1)} m2（建蔽率の上限 ${E.maxBuildingArea(site).toFixed(1)} m2）`,
      `延床面積(概算): ${totalFloorArea(result).toFixed(1)} m2（容積率の上限 ${E.maxFloorArea(site).toFixed(1)} m2）`,
    ];
    const achieved = area > 0 ? totalFloorArea(result) / area : 0;
    const target = result.far.effective;
    lines.push(`達成容積率: ${(achieved * 100).toFixed(0)}%（上限 ${(target * 100).toFixed(0)}% に対して ${target > 0 ? ((achieved / target) * 100).toFixed(0) : 0}%）`);
    lines.push(`最高高さ: ${maxHeight(result).toFixed(2)} m`);
    lines.push(`体積: ${totalVolume(result).toFixed(1)} m3`);
    if (result.area) {
      const used = result.floors.filter(f => f > 0).length;
      const top = result.floors.length ? Math.max(...result.floors) : 0;
      lines.push(`メッシュ: ${result.area.cellSizeXM.toFixed(1)}m × ${result.area.cellSizeYM.toFixed(1)}m / 使用${used}マス（全${result.area.cells.length}マス）/ 最高${top}階`);
    }
    const binding = [];
    if (result.coverageLimited) binding.push('建蔽率');
    if (result.farLimited) binding.push('容積率');
    if (result.shadowLimited) binding.push('日影規制');
    lines.push('上限に達した規制: ' + (binding.length ? binding.join('・') : 'なし'));
    if (result.shadowLimited) lines.push(`　日影規制で削った体積: ${result.removedByShadow.toFixed(1)} m3`);
    for (const line of result.shadowLines) {
      const label = line.distanceM === 5.0 ? '5m〜10m' : '10m超';
      // Python の float 表記に合わせる（5 は "5.0"、4.25 は "4.25"）。
      // JS の既定は末尾の .0 を落としてしまうため。
      const hours = Number.isInteger(line.maxHours) ? line.maxHours.toFixed(1) : String(line.maxHours);
      lines.push(`　${label}の測定線（${hours}時間以内）: ${line.ok ? '適合' : '不適合'} / 最大 ${line.worstHours.toFixed(2)}時間`);
    }
    lines.push(...result.far.notes, ...result.notes);
    return lines;
  }

  global.MveOptimizer = {
    optimize, floorsToBlocks, totalVolume, buildingArea, totalFloorArea, maxHeight,
    summaryLinesJa, applyCoverageCap, applyFarCap, resolveShadow,
  };
})(typeof window !== 'undefined' ? window : globalThis);
