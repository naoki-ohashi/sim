/* MVE 等時間日影図（等時間日影線） — マーチングスクエア法によるJS実装
 *
 * Python版 mve/isochrone.py（+ mve/shadow_index.py の grid_shadow_hours）の
 * 移植。外部ライブラリは使わない。engine.js を先に読み込んでください。
 */
(function (global) {
  'use strict';

  const E = global.MveEngine;
  if (!E) throw new Error('engine.js を先に読み込んでください');

  const FALLBACK_MARGIN_M = 10.0;
  const WINTER_SOLSTICE_DOY = E.dayOfYear(12, 22);

  // 太陽高度と建物高さから、影が届きうる最大水平距離を見積もる
  // （グリッドが敷地の外側にどれだけ広がっている必要があるか）
  function defaultGridMarginM(spec, maxHeightM) {
    const dec = E.solarDeclinationDeg(WINTER_SOLSTICE_DOY);
    let minAltitude = null;
    for (const hour of E.trueSolarHours(spec)) {
      const [alt] = E.solarPositionDeg(spec.latitudeDeg, dec, hour);
      if (alt > 0 && (minAltitude === null || alt < minAltitude)) minAltitude = alt;
    }
    const effectiveHeight = maxHeightM - spec.measurementHeightM;
    if (minAltitude === null || effectiveHeight <= 0) return FALLBACK_MARGIN_M;
    return effectiveHeight / Math.tan((minAltitude * Math.PI) / 180);
  }

  // 各グリッド点の、冬至における実際の日影時間(h)
  function gridShadowHours(site, area, floors, spec, gridPoints) {
    const n = gridPoints.length;
    const shadowedHours = new Float64Array(n);
    if (!area || !area.cells.length || !n) return shadowedHours;

    const boxes = area.cells.map(c => c.bounds);
    const heights = floors.map(f => f * site.floorHeightM);
    const dec = E.solarDeclinationDeg(WINTER_SOLSTICE_DOY);
    const step = spec.timeStepMinutes / 60;

    for (const hour of E.trueSolarHours(spec)) {
      const [alt, az] = E.solarPositionDeg(spec.latitudeDeg, dec, hour);
      if (alt <= 0) continue;
      const [dx, dy] = E.vectorForAzimuth(az, site.northAngleDeg);
      const tanAlt = Math.tan((alt * Math.PI) / 180);
      for (let gi = 0; gi < n; gi++) {
        const [gx, gy] = gridPoints[gi];
        let shadowed = false;
        for (let ci = 0; ci < boxes.length; ci++) {
          const r = E.rayBoxEntry(gx, gy, dx, dy, boxes[ci]);
          if (!isFinite(r)) continue;
          if (heights[ci] >= spec.measurementHeightM + r * tanAlt) { shadowed = true; break; }
        }
        if (shadowed) shadowedHours[gi] += step;
      }
    }
    return shadowedHours;
  }

  // マーチングスクエア法のケース→つなぐ辺のペア。
  // 辺番号: 0=下(BL-BR) 1=右(BR-TR) 2=上(TR-TL) 3=左(TL-BL)
  // ケース番号のビット: bit0=BL bit1=BR bit2=TR bit3=TL（各値がlevel以上なら1）
  const CASE_EDGES = {
    0: [], 15: [],
    1: [[3, 0]], 14: [[3, 0]],
    2: [[0, 1]], 13: [[0, 1]],
    3: [[1, 3]], 12: [[1, 3]],
    4: [[1, 2]], 11: [[1, 2]],
    6: [[0, 2]], 9: [[0, 2]],
    7: [[2, 3]], 8: [[2, 3]],
    5: 'saddle',   // BL,TR が level以上（BR,TLは未満）
    10: 'saddle',  // BR,TL が level以上（BL,TRは未満）
  };

  function roundPoint(p) {
    return [Math.round(p[0] * 1e6) / 1e6, Math.round(p[1] * 1e6) / 1e6];
  }
  const keyOf = p => p[0] + ',' + p[1];

  // 線分の集まりを、端点でつないだポリラインにまとめる。
  // 戻り値は [ポリライン, 閉曲線か] のリスト。
  function segmentsToPolylines(segments) {
    const pointSegs = new Map();
    segments.forEach((seg, idx) => {
      for (const p of seg) {
        const k = keyOf(p);
        if (!pointSegs.has(k)) pointSegs.set(k, []);
        pointSegs.get(k).push(idx);
      }
    });
    const visited = new Array(segments.length).fill(false);

    function otherPoint(segIdx, p) {
      const [a, b] = segments[segIdx];
      return keyOf(a) === keyOf(p) ? b : a;
    }
    function walk(startPoint, startSeg) {
      const chain = [startPoint];
      let curPoint = startPoint, curSeg = startSeg;
      for (;;) {
        visited[curSeg] = true;
        const nxt = otherPoint(curSeg, curPoint);
        chain.push(nxt);
        const candidates = (pointSegs.get(keyOf(nxt)) || []).filter(s => !visited[s]);
        if (!candidates.length) return chain;
        curSeg = candidates[0];
        curPoint = nxt;
      }
    }

    const polylines = [];
    // 開いた線（端点=次数1の点）から先にたどる
    for (const [k, segs] of pointSegs) {
      const unvisited = segs.filter(s => !visited[s]);
      if (segs.length === 1 && unvisited.length === 1) {
        const point = segments[unvisited[0]].find(p => keyOf(p) === k);
        polylines.push([walk(point, unvisited[0]), false]);
      }
    }
    // 残りは閉じた等高線
    for (let idx = 0; idx < segments.length; idx++) {
      if (visited[idx]) continue;
      const chain = walk(segments[idx][0], idx);
      if (chain.length > 1 && keyOf(chain[chain.length - 1]) === keyOf(chain[0])) chain.pop();
      polylines.push([chain, true]);
    }
    return polylines;
  }

  // マーチングスクエア法で等高線を抽出する。
  // values[j][i] は座標 (gridX[i], gridY[j]) の値。
  // 戻り値は { level: [ポリライン, 閉曲線か][] }（levelは数値キー→文字列化される）。
  function computeIsochrones(gridX, gridY, values, levels) {
    const nx = gridX.length, ny = gridY.length;
    const result = {};

    for (const level of levels) {
      const segments = [];
      for (let j = 0; j < ny - 1; j++) {
        const y0 = gridY[j], y1 = gridY[j + 1];
        for (let i = 0; i < nx - 1; i++) {
          const x0 = gridX[i], x1 = gridX[i + 1];
          const vBl = values[j][i], vBr = values[j][i + 1];
          const vTr = values[j + 1][i + 1], vTl = values[j + 1][i];

          const c = (vBl >= level ? 1 : 0) | (vBr >= level ? 2 : 0)
                  | (vTr >= level ? 4 : 0) | (vTl >= level ? 8 : 0);
          if (c === 0 || c === 15) continue;

          const interp = (va, vb, pa, pb) => {
            let t = va === vb ? 0.5 : (level - va) / (vb - va);
            t = Math.min(1, Math.max(0, t));
            return [pa[0] + t * (pb[0] - pa[0]), pa[1] + t * (pb[1] - pa[1])];
          };
          const edgePoints = {
            0: () => interp(vBl, vBr, [x0, y0], [x1, y0]),
            1: () => interp(vBr, vTr, [x1, y0], [x1, y1]),
            2: () => interp(vTr, vTl, [x1, y1], [x0, y1]),
            3: () => interp(vTl, vBl, [x0, y1], [x0, y0]),
          };

          let pairs = CASE_EDGES[c];
          if (pairs === 'saddle') {
            const center = (vBl + vBr + vTr + vTl) / 4;
            if (c === 5) pairs = center < level ? [[3, 0], [1, 2]] : [[0, 1], [2, 3]];
            else pairs = center < level ? [[0, 3], [1, 2]] : [[0, 1], [2, 3]];
          }
          for (const [a, b] of pairs) {
            const pa = roundPoint(edgePoints[a]());
            const pb = roundPoint(edgePoints[b]());
            if (pa[0] !== pb[0] || pa[1] !== pb[1]) segments.push([pa, pb]);
          }
        }
      }
      result[level] = segmentsToPolylines(segments);
    }
    return result;
  }

  // grid_shadow_hours + compute_isochrones をまとめた入口。
  function siteIsochrones(site, area, floors, spec, levels, intervalM, marginM) {
    const empty = {};
    for (const l of levels || []) empty[l] = [];
    if (!levels || !levels.length || !area || !area.cells.length) return empty;

    const heights = floors.map(f => f * site.floorHeightM);
    const maxHeight = heights.length ? Math.max(...heights) : 0;
    const margin = marginM != null ? marginM : defaultGridMarginM(spec, maxHeight);

    const xs = site.points.map(p => p[0]), ys = site.points.map(p => p[1]);
    const xMin = Math.min(...xs) - margin, xMax = Math.max(...xs) + margin;
    const yMin = Math.min(...ys) - margin, yMax = Math.max(...ys) + margin;
    const interval = intervalM || 2.0;

    const nx = Math.max(2, Math.ceil((xMax - xMin) / interval) + 1);
    const ny = Math.max(2, Math.ceil((yMax - yMin) / interval) + 1);
    const gridX = Array.from({ length: nx }, (_, i) => xMin + (xMax - xMin) * (nx === 1 ? 0 : i / (nx - 1)));
    const gridY = Array.from({ length: ny }, (_, j) => yMin + (yMax - yMin) * (ny === 1 ? 0 : j / (ny - 1)));

    const gridPoints = [];
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) gridPoints.push([gridX[i], gridY[j]]);

    const hoursFlat = gridShadowHours(site, area, floors, spec, gridPoints);
    const values = [];
    for (let j = 0; j < ny; j++) values.push(Array.from(hoursFlat.subarray(j * nx, (j + 1) * nx)));

    return computeIsochrones(gridX, gridY, values, levels);
  }

  global.MveIsochrone = { defaultGridMarginM, gridShadowHours, computeIsochrones, siteIsochrones };
})(typeof window !== 'undefined' ? window : globalThis);
