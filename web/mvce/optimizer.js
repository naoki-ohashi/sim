/* MVE ボクセル最適化（JavaScript版）
 *
 * Python版 mvce/solvers/optimizer.py の移植。engine.js を先に読み込んでください。
 *
 *   敷地 → 壁面後退線 → 建物外郭線 → メッシュ → 各マスの階数
 *
 * 日影規制を超えた場合は、しきい値インデックスで**原因になっているマスだけ**を
 * 特定して下げます（建物全体を一律に低くはしません）。
 */
(function (global) {
  'use strict';

  const E = global.MvceEngine;
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

  // 日影の是正を1手だけ進める（最も超過している測定点を1つ解消する）
  function shadowStep(area, floors, index, floorHeightM) {
    const areas = area.cells.map(c => c.areaM2);
    const n = index.nCells;
    const heights = floors.map(f => f * floorHeightM);
    const worst = E.worstViolation(index, heights);
    if (!worst) return { acted: false, removed: 0, note: null, done: true };

    const table = worst.line.tables[worst.pointIndex];
    const need = Math.ceil((worst.hours - worst.line.maxHours) / index.stepHours - 1e-9);
    if (need <= 0) return { acted: false, removed: 0, note: null, done: false };

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
      return { acted: false, removed: 0, note: '日影規制を満たすために下げられる柱がこれ以上ありません。'
               + 'メッシュを細かくすると改善する場合があります。', done: false };
    }
    costs.sort((a, b) => a.cost - b.cost);
    let removed = 0;
    for (const { plan } of costs.slice(0, need)) {
      for (const [ci, target] of plan) {
        if (floors[ci] > target) {
          removed += (floors[ci] - target) * areas[ci] * floorHeightM;
          floors[ci] = target;
        }
      }
    }
    return { acted: true, removed, note: null, done: false };
  }

  function resolveShadow(area, floors, index, floorHeightM, maxIterations) {
    let removed = 0, touched = false;
    const notes = [];
    for (let iter = 0; iter < maxIterations; iter++) {
      const { acted, removed: r, note, done } = shadowStep(area, floors, index, floorHeightM);
      if (note) notes.push(note);
      if (acted) { touched = true; removed += r; }
      if (done || !acted) break;
    }
    return { touched, removed, notes };
  }

  /* 天空率: Ps < Pr の測定点について、稜線を作っているマスだけを下げる。
   * 候補の中から「天空率の改善 / 失う体積」が最も大きいマスを1階ずつ下げる。
   */

  // 天空率の是正を1手だけ進める（稜線を作っているマスを1階だけ下げる）
  function skyStep(area, floors, index, floorHeightM) {
    const areas = area.cells.map(c => c.areaM2);
    const heights = floors.map(f => f * floorHeightM);
    const worst = E.skyWorst(index, heights);
    if (!worst) return { acted: false, removed: 0, note: null, done: true };

    const candidates = E.skyRidgeCells(index, worst.pointIndex, heights).filter(c => floors[c] > 0);
    let best = null;
    for (const ci of candidates) {
      const trial = heights.slice();
      trial[ci] -= floorHeightM;
      const gain = E.skyPsAt(index, worst.pointIndex, trial) - worst.ps;
      if (gain <= 1e-12) continue;
      const cost = areas[ci] * floorHeightM;
      const score = cost > 0 ? gain / cost : 0;
      if (!best || score > best.score) best = { score, ci, cost };
    }

    if (!best) {
      return { acted: false, removed: 0, note: '天空率を満たすためにマスを下げようとしましたが、'
               + 'これ以上下げても改善しませんでした（壁面後退距離を増やすと適合しやすくなります）。',
               done: false };
    }
    floors[best.ci] -= 1;
    return { acted: true, removed: best.cost, note: null, done: false };
  }

  function resolveSkyRatio(area, floors, index, floorHeightM, maxIterations) {
    let removed = 0, touched = false;
    const notes = [];
    let iter = 0;
    for (; iter < maxIterations; iter++) {
      const { acted, removed: r, note, done } = skyStep(area, floors, index, floorHeightM);
      if (note) notes.push(note);
      if (acted) { touched = true; removed += r; }
      if (done || !acted) break;
    }
    if (iter >= maxIterations) {
      notes.push(`天空率の解消が${maxIterations}回の調整で収束しませんでした。`
               + 'メッシュを粗くするか、条件を見直してください。');
    }
    return { touched, removed, notes };
  }

  /* 日影と天空率を1手ずつ交互に解消する（両方を同時に動かす1本の探索）。
   * 片方を先に解消し切ってから他方に移ると、一方の是正がもう一方も満たして
   * いた場合の重複した削り込みに気づけないため、常に両方の最新の状態を
   * 見ながら進める（Python版 _resolve_shadow_and_sky_jointly と同じ考え方）。
   */
  function resolveShadowAndSkyJointly(area, floors, shadowIndex, skyIndex, floorHeightM, maxIterations) {
    let removedShadow = 0, removedSky = 0;
    let shadowTouched = false, skyTouched = false;
    let shadowDone = false, skyDone = false;
    const notes = [];
    let brokeOut = false;

    for (let iter = 0; iter < maxIterations; iter++) {
      if (shadowDone && skyDone) { brokeOut = true; break; }
      if (!shadowDone) {
        const { acted, removed, note, done } = shadowStep(area, floors, shadowIndex, floorHeightM);
        if (note) notes.push(note);
        if (acted) { shadowTouched = true; removedShadow += removed; }
        shadowDone = done || !acted;
      }
      if (!skyDone) {
        const { acted, removed, note, done } = skyStep(area, floors, skyIndex, floorHeightM);
        if (note) notes.push(note);
        if (acted) { skyTouched = true; removedSky += removed; }
        skyDone = done || !acted;
      }
    }
    if (!brokeOut) {
      notes.push(`日影規制・天空率の同時解消が${maxIterations}回の調整で収束しませんでした。`
               + 'メッシュを粗くするか、条件を見直してください。');
    }
    return { shadowTouched, removedShadow, skyTouched, removedSky, notes };
  }

  // 1本の柱だけで容積率を使い切る階数を上限にする（use_sky_ratio で高さ上限が
  // 無限になり得るため、削り込みの回数が現実的な範囲で収まるよう先に頭を抑える）
  function capByFar(area, floors, maxFloorAreaM2) {
    area.cells.forEach((cell, i) => {
      if (cell.areaM2 <= 0) { floors[i] = 0; return; }
      const ceiling = Math.ceil(maxFloorAreaM2 / cell.areaM2);
      if (floors[i] > ceiling) floors[i] = ceiling;
    });
  }

  // 日影・天空率で削った後、まだ余裕のあるマスに積み直す（両方満たす範囲で）
  function refill(area, floors, site, floorHeightM, shadowIndex, skyIndex, maxPasses) {
    const areas = area.cells.map(c => c.areaM2);
    const caps = area.cells.map(c => c.maxFloors);
    const farCap = E.maxFloorArea(site);
    const coverageCap = E.maxBuildingArea(site);

    function feasible(heights) {
      if (shadowIndex && !E.isShadowCompliant(shadowIndex, heights)) return false;
      if (skyIndex && !E.skyIsCompliant(skyIndex, heights)) return false;
      return true;
    }

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
        if (feasible(floors.map(f => f * floorHeightM))) { placed = true; break; }
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
      skyRatioIntervalM: 4.0, skyRatioNAzimuth: 72,
    }, options || {});

    const far = E.computeFar(site);
    const notes = [];
    const area = E.buildMesh(site, opt);
    if (!area || !area.cells.length) {
      notes.push('壁面後退線で囲まれた建物外郭線が取れませんでした。'
               + '壁面後退距離が大きすぎないか確認してください。');
      return { site, area: null, floors: [], blocks: [], far, notes,
               shadowLines: [], coverageLimited: false, farLimited: false,
               shadowLimited: false, removedByShadow: 0,
               skyLimited: false, removedBySky: 0, skySummary: null };
    }

    E.assignHeightLimits(site, area, opt.useSkyRatio);
    const fh = site.floorHeightM;
    const floors = area.cells.map(c => c.maxFloors);
    if (!floors.some(f => f > 0)) notes.push('斜線制限により、1階分の高さも確保できませんでした。');
    // 天空率で斜線制限を外すと上限が無限になり得るので、1本の柱だけで容積率を
    // 使い切る階数で頭を抑える。以降の削り込みが現実的な回数で終わる。
    capByFar(area, floors, E.maxFloorArea(site));

    const coverageLimited = applyCoverageCap(area, floors, E.maxBuildingArea(site));
    const farLimited = applyFarCap(area, floors, E.maxFloorArea(site));

    let shadowIndex = null, skyIndex = null;
    let shadowLimited = false, skyLimited = false;
    let removed = 0, removedSky = 0;
    const hasShadow = !!shadowSpec && floors.some(f => f > 0);
    const hasSky = opt.useSkyRatio && floors.some(f => f > 0);

    if (hasShadow && hasSky) {
      // 日影と天空率を1手ずつ交互に解消する（片方を先に解消し切らない）
      shadowIndex = E.buildShadowIndex(site, area, shadowSpec);
      skyIndex = E.buildSkyIndex(site, area, opt.skyRatioIntervalM, opt.skyRatioNAzimuth);
      const joint = resolveShadowAndSkyJointly(area, floors, shadowIndex, skyIndex, fh, opt.maxIterations);
      shadowLimited = joint.shadowTouched; removed = joint.removedShadow;
      skyLimited = joint.skyTouched; removedSky = joint.removedSky;
      notes.push(...joint.notes);
    } else {
      if (hasShadow) {
        shadowIndex = E.buildShadowIndex(site, area, shadowSpec);
        const res = resolveShadow(area, floors, shadowIndex, fh, opt.maxIterations);
        shadowLimited = res.touched; removed = res.removed;
        notes.push(...res.notes);
      }
      if (hasSky) {
        skyIndex = E.buildSkyIndex(site, area, opt.skyRatioIntervalM, opt.skyRatioNAzimuth);
        const res = resolveSkyRatio(area, floors, skyIndex, fh, opt.maxIterations);
        skyLimited = res.touched; removedSky = res.removed;
        notes.push(...res.notes);
      }
    }

    // 削った結果あいた容積率の余地に、日影・天空率の両方を満たす範囲で積み直す
    if (shadowLimited || skyLimited) {
      refill(area, floors, site, fh, shadowIndex, skyIndex);
    }

    const shadowLines = shadowIndex ? E.shadowSummary(shadowIndex, floors.map(f => f * fh)) : [];
    const skySum = skyIndex ? E.skySummary(skyIndex, floors.map(f => f * fh)) : null;
    if (skySum && !skySum.ok) {
      notes.push(`天空率が不足したままです（最小余裕 ${fmtSigned(skySum.worstMargin)}%）。`
               + '壁面後退距離を増やすか、斜線制限のまま（use_sky_ratio: false）で検討してください。');
    }

    return {
      site, area, floors, blocks: floorsToBlocks(area, floors, fh), far,
      shadowLines, coverageLimited, farLimited, shadowLimited,
      removedByShadow: removed, skyLimited, removedBySky: removedSky,
      skySummary: skySum, notes,
    };
  }

  const fmtSigned = v => (v >= 0 ? '+' : '') + v.toFixed(2);

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
    if (result.skyLimited) binding.push('天空率');
    lines.push('上限に達した規制: ' + (binding.length ? binding.join('・') : 'なし'));
    if (result.shadowLimited) lines.push(`　日影規制で削った体積: ${result.removedByShadow.toFixed(1)} m3`);
    if (result.skyLimited) lines.push(`　天空率で削った体積: ${result.removedBySky.toFixed(1)} m3`);
    for (const line of result.shadowLines) {
      const label = line.distanceM === 5.0 ? '5m〜10m' : '10m超';
      // Python の float 表記に合わせる（5 は "5.0"、4.25 は "4.25"）。
      // JS の既定は末尾の .0 を落としてしまうため。
      const hours = Number.isInteger(line.maxHours) ? line.maxHours.toFixed(1) : String(line.maxHours);
      lines.push(`　${label}の測定線（${hours}時間以内）: ${line.ok ? '適合' : '不適合'} / 最大 ${line.worstHours.toFixed(2)}時間`);
    }
    if (result.skySummary) {
      const sky = result.skySummary;
      lines.push(`　天空率（法56条7項・${sky.nPoints}点で判定）: ${sky.ok ? '適合' : '不適合'} / `
        + `最小余裕 ${fmtSigned(sky.worstMargin)}%（Ps ${sky.worstPs.toFixed(2)}% ≧ Pr ${sky.worstPr.toFixed(2)}%）`);
    }
    lines.push(...result.far.notes, ...result.notes);
    return lines;
  }

  global.MvceOptimizer = {
    optimize, floorsToBlocks, totalVolume, buildingArea, totalFloorArea, maxHeight,
    summaryLinesJa, applyCoverageCap, applyFarCap, resolveShadow,
    shadowStep, skyStep, resolveSkyRatio, resolveShadowAndSkyJointly, refill,
  };
})(typeof window !== 'undefined' ? window : globalThis);
