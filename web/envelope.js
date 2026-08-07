/* jwcad-volume 最大ボリューム探索（JavaScript版）
 *
 * Python版 jwcad_volume/envelope.py の移植。engine.js を先に読み込んで
 * おく必要があります（素の <script> で順に読み込む前提）。
 */
(function (global) {
  'use strict';

  const E = global.JwcadVolumeEngine;
  if (!E) throw new Error('engine.js を先に読み込んでください');

  const DEFAULT_SPLIT_FRACTIONS = [0.3, 0.5, 0.7];
  const DEFAULT_STAGE_INSETS_M = [0.0, 3.0, 6.0];
  const DEFAULT_MAX_STAGES = 2;

  const blockVolume = b => E.polygonArea(b.footprint) * (b.zTop - b.zBottom);
  const totalVolume = blocks => blocks.reduce((s, b) => s + blockVolume(b), 0);
  const maxHeight = blocks => blocks.reduce((m, b) => Math.max(m, b.zTop), 0);
  const totalFloorArea = (blocks, floorH) => totalVolume(blocks) / floorH;

  // 分割高さまでのポディウム。またぐ層は捨てずに切る（Python版と同じ）
  function podiumUpTo(baseline, splitHeight) {
    const out = [];
    for (const b of baseline) {
      if (b.zBottom >= splitHeight - 1e-9) break;
      out.push(b.zTop <= splitHeight + 1e-9
        ? b
        : { footprint: b.footprint, zBottom: b.zBottom, zTop: splitHeight });
    }
    return out;
  }

  function maxExtraHeightForSplit(site, baseline, splitHeight, mps, prValues, opt) {
    const podium = podiumUpTo(baseline, splitHeight);
    const dists = site.edges.map(e => E.requiredSetbackForHeight(e, splitHeight, site, 1.0));
    const baseFootprint = E.offsetPolygonByEdgeDistances(site.points, dists);
    if (!baseFootprint || E.polygonArea(baseFootprint) < 1e-6) return null;

    const allPass = blocks => {
      for (let i = 0; i < mps.length; i++) {
        const p = mps[i].point;
        if (E.skyRatioPercent([p[0], p[1], opt.measurementHeight], blocks, opt.nAzimuth) < prValues[i]) {
          return false;
        }
      }
      return true;
    };

    const tallestStage = (fixed, footprint, zBottom, hMax) => {
      const blocksFor = h => (h <= 1e-9 ? fixed : fixed.concat([{ footprint, zBottom, zTop: zBottom + h }]));
      if (allPass(blocksFor(hMax))) return hMax;
      let lo = 0, hi = hMax;
      for (let i = 0; i < opt.iterations; i++) {
        const mid = (lo + hi) / 2;
        if (allPass(blocksFor(mid))) lo = mid; else hi = mid;
      }
      return lo;
    };

    const stages = [];
    let blocks = podium.slice();
    let z = splitHeight;
    let remaining = opt.extraHMax;
    let cumulativeInset = 0;

    for (let s = 0; s < opt.maxStages; s++) {
      if (remaining <= 1e-6) break;
      let best = null;
      for (const inset of opt.stageInsetsM) {
        const totalInset = cumulativeInset + inset;
        const footprint = totalInset <= 0 ? baseFootprint : E.erodePolygon(baseFootprint, totalInset);
        if (!footprint) continue;
        const h = tallestStage(blocks, footprint, z, remaining);
        const gain = E.polygonArea(footprint) * h;
        if (h > 1e-6 && (!best || gain > best.gain)) best = { gain, totalInset, h, footprint };
      }
      if (!best || best.gain <= 1e-6) break;
      blocks = blocks.concat([{ footprint: best.footprint, zBottom: z, zTop: z + best.h }]);
      stages.push({
        insetM: best.totalInset, footprintAreaM2: E.polygonArea(best.footprint),
        zBottom: z, zTop: z + best.h, heightM: best.h,
      });
      cumulativeInset = best.totalInset;
      z += best.h;
      remaining -= best.h;
    }

    if (!stages.length) return null;
    return { splitHeightM: splitHeight, stages, blocks, volumeM3: totalVolume(blocks) };
  }

  function searchSkyRatioTower(site, baseline, opt) {
    if (!baseline.length) return { splitHeightM: 0, stages: [], blocks: [], volumeM3: 0 };
    const maxH = maxHeight(baseline);
    const extraHMax = opt.extraHMax == null ? maxH * 2 : opt.extraHMax;
    const mps = E.measurementPoints(site, opt.intervalM);
    const baselineVolume = totalVolume(baseline);
    let best = { splitHeightM: maxH, stages: [], blocks: baseline, volumeM3: baselineVolume };
    if (!mps.length) return best;

    const prValues = mps.map(mp =>
      E.skyRatioPercent([mp.point[0], mp.point[1], opt.measurementHeight], baseline, opt.nAzimuth));

    for (const frac of opt.splitFractions) {
      const cand = maxExtraHeightForSplit(site, baseline, maxH * frac, mps, prValues,
        Object.assign({}, opt, { extraHMax }));
      if (cand && cand.volumeM3 > best.volumeM3 + Math.max(1e-6, baselineVolume * 1e-9)) best = cand;
    }
    return best;
  }

  // 建蔽率: 全層を同じ距離だけ内側へ縮めて建築面積の上限に収める
  function applyCoverageCap(blocks, maxAreaM2) {
    if (!blocks.length) return blocks;
    const baseArea = E.polygonArea(blocks[0].footprint);
    if (baseArea <= maxAreaM2) return { blocks, applied: false };

    const areaAfter = d => {
      const p = E.erodePolygon(blocks[0].footprint, d);
      return p ? E.polygonArea(p) : 0;
    };
    let lo = 0, hi = Math.sqrt(baseArea / Math.PI);
    let guard = 0;
    while (areaAfter(hi) > maxAreaM2 && guard++ < 40) hi *= 2;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      if (areaAfter(mid) > maxAreaM2) lo = mid; else hi = mid;
    }
    const out = [];
    for (const b of blocks) {
      const eroded = E.erodePolygon(b.footprint, hi);
      if (eroded && E.polygonArea(eroded) > 1e-6) {
        out.push({ footprint: eroded, zBottom: b.zBottom, zTop: b.zTop });
      }
    }
    return { blocks: out, applied: true };
  }

  // 容積率: 上から切り詰める（体積 = 延床 x 階高 で数える）
  function applyFarCap(blocks, maxFarAreaM2, floorHeightM) {
    const maxVolume = maxFarAreaM2 * floorHeightM;
    const out = [];
    let used = 0;
    let applied = false;
    for (const b of blocks) {
      const v = blockVolume(b);
      if (used + v <= maxVolume) { out.push(b); used += v; continue; }
      applied = true;
      const remaining = maxVolume - used;
      const area = E.polygonArea(b.footprint);
      if (remaining > 1e-9 && area > 0) {
        const h = remaining / area;
        if (h > 1e-6) out.push({ footprint: b.footprint, zBottom: b.zBottom, zTop: b.zBottom + h });
      }
      break;
    }
    return { blocks: out, applied };
  }

  const scaleHeight = (blocks, k) =>
    blocks.map(b => ({ footprint: b.footprint, zBottom: b.zBottom * k, zTop: b.zTop * k }));

  // 日影規制: 違反していたら全体の高さを一律に下げて適合させる
  function reduceForShadow(site, blocks, shadowParams) {
    let checks = E.computeShadowHours(site, blocks, shadowParams);
    if (!blocks.length || checks.every(c => c.ok)) return { blocks, scale: 1, checks };
    let lo = 0, hi = 1;
    for (let i = 0; i < 16; i++) {
      const mid = (lo + hi) / 2;
      if (E.computeShadowHours(site, scaleHeight(blocks, mid), shadowParams).every(c => c.ok)) lo = mid;
      else hi = mid;
    }
    const scaled = scaleHeight(blocks, lo);
    return { blocks: scaled, scale: lo, checks: E.computeShadowHours(site, scaled, shadowParams) };
  }

  function computeMaxEnvelope(site, options) {
    const opt = Object.assign({
      nLayers: 10, intervalM: 4.0, nAzimuth: 45, measurementHeight: 0.0,
      splitFractions: DEFAULT_SPLIT_FRACTIONS, iterations: 12,
      stageInsetsM: DEFAULT_STAGE_INSETS_M, maxStages: DEFAULT_MAX_STAGES,
      useSkyRatio: true, shadowParams: null, extraHMax: null,
    }, options || {});

    const baseline = E.referenceBuildingBlocks(site, opt.nLayers, null);
    if (!baseline.length) {
      return {
        site, baselineBlocks: [], boostedBlocks: [], blocks: [],
        tower: { splitHeightM: 0, stages: [] }, skyRatioChecks: [],
        coverageCapApplied: false, farCapApplied: false,
        shadowChecks: null, shadowHeightScale: 1,
      };
    }

    const tower = opt.useSkyRatio
      ? searchSkyRatioTower(site, baseline, opt)
      : { splitHeightM: maxHeight(baseline), stages: [], blocks: baseline, volumeM3: totalVolume(baseline) };
    const boosted = tower.blocks;

    const cov = applyCoverageCap(boosted, E.polygonArea(site.points) * site.zoning.coverageRatio);
    const far = applyFarCap(cov.blocks, E.polygonArea(site.points) * site.zoning.farRatio, site.floorHeightM);

    let blocks = far.blocks;
    let shadowChecks = null;
    let shadowScale = 1;
    if (opt.shadowParams) {
      const red = reduceForShadow(site, blocks, opt.shadowParams);
      blocks = red.blocks; shadowScale = red.scale; shadowChecks = red.checks;
    }

    const skyRatioChecks = E.checkSkyRatio(
      site, blocks, baseline, opt.intervalM, opt.nAzimuth, opt.measurementHeight);

    return {
      site, baselineBlocks: baseline, boostedBlocks: boosted, blocks, tower,
      skyRatioChecks, coverageCapApplied: cov.applied, farCapApplied: far.applied,
      shadowChecks, shadowHeightScale: shadowScale,
    };
  }

  // Python版 EnvelopeResult.summary_lines_ja() と同じ内容
  function summaryLinesJa(result) {
    const site = result.site;
    const siteArea = E.polygonArea(site.points);
    const blocks = result.blocks;
    const footprint = blocks.length ? E.polygonArea(blocks[0].footprint) : 0;
    const floorArea = totalFloorArea(blocks, site.floorHeightM);
    const lines = [
      `敷地面積: ${siteArea.toFixed(1)} m2`,
      `建築面積: ${footprint.toFixed(1)} m2（建蔽率の上限 ${(siteArea * site.zoning.coverageRatio).toFixed(1)} m2）`,
      `延床面積(概算): ${floorArea.toFixed(1)} m2（容積率の上限 ${(siteArea * site.zoning.farRatio).toFixed(1)} m2）`,
      `最高高さ: ${maxHeight(blocks).toFixed(2)} m`,
      `体積: ${totalVolume(blocks).toFixed(1)} m3`,
    ];
    const stages = result.tower.stages || [];
    if (stages.length) {
      const extra = stages.reduce((s, x) => s + x.heightM, 0);
      lines.push(`天空率による割増: 高さ${result.tower.splitHeightM.toFixed(1)}mから上に${stages.length}段、計+${extra.toFixed(1)}m`);
      stages.forEach((s, i) => lines.push(
        `　${i + 1}段目: セットバック${s.insetM.toFixed(1)}m / ${s.footprintAreaM2.toFixed(1)} m2 / 高さ${s.heightM.toFixed(1)}m`));
    } else {
      lines.push('天空率による割増: なし（斜線制限のままが最大）');
    }
    const caps = [];
    if (result.coverageCapApplied) caps.push('建蔽率');
    if (result.farCapApplied) caps.push('容積率');
    lines.push('上限に達した規制: ' + (caps.length ? caps.join('・') : 'なし'));
    const okCount = result.skyRatioChecks.filter(c => c.ok).length;
    lines.push(`天空率の判定: ${okCount}/${result.skyRatioChecks.length} 点が適合`);
    if (result.shadowChecks) {
      lines.push(result.shadowHeightScale < 1
        ? `日影規制により高さを ${(result.shadowHeightScale * 100).toFixed(1)}% に縮小`
        : '日影規制による縮小: なし');
      for (const c of result.shadowChecks) {
        const label = c.lineName === 'line1' ? '第1種' : '第2種';
        lines.push(`　${label}測定線（${c.maxHours}時間以内）: ${c.ok ? '適合' : '不適合'} / 最大 ${c.worstHours.toFixed(2)}時間`);
      }
    }
    return lines;
  }

  global.JwcadVolumeEnvelope = {
    DEFAULT_SPLIT_FRACTIONS, DEFAULT_STAGE_INSETS_M, DEFAULT_MAX_STAGES,
    blockVolume, totalVolume, maxHeight, totalFloorArea,
    podiumUpTo, searchSkyRatioTower, applyCoverageCap, applyFarCap,
    reduceForShadow, computeMaxEnvelope, summaryLinesJa,
  };
})(typeof window !== 'undefined' ? window : globalThis);
