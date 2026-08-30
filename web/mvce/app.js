/* MVE 入力UI（画面 ⇔ 計算エンジン ⇔ 平面図/3D）
 *
 * 計算は engine.js / optimizer.js（Python版の移植）が担当し、3D表示は
 * viewer.js（Python版の出力と共通）が担当します。ここは画面まわりだけです。
 */
(function () {
  'use strict';

  const E = window.MvceEngine;
  const O = window.MvceOptimizer;
  const I = window.MvceIsochrone;
  const $ = id => document.getElementById(id);

  const KIND_LABELS = { road: '道路境界線', adjacent: '隣地境界線', none: '規制の対象外' };
  const RELAX_LABELS = { none: 'なし', park: '公園・広場', water: '水面（河川等）', railway: '線路敷' };

  let lastResult = null;
  let lastShadowSpec = null;
  let lastIsochroneHours = [];
  let lastIsochrones = null;

  // 平面図のズーム・パン（ホイールでズーム）。null は「自動フィット」を表す。
  let planZoom = 1;
  let planCenter = null;
  let lastPlanView = null; // 直近に描いた変換パラメータ（ホイールでのズーム中心計算に使う）
  const resetPlanView = () => { planZoom = 1; planCenter = null; };

  // ===== 入力の読み取り ===============================================
  function sitePoints() {
    if ($('shape-mode').value === 'rect') {
      const w = +$('width').value, d = +$('depth').value;
      if (!(w > 0) || !(d > 0)) throw new Error('間口と奥行は正の数で入力してください');
      return [[0, 0], [w, 0], [w, d], [0, d]];
    }
    const pts = $('poly-points').value.trim().split('\n')
      .map(line => line.split(',').map(s => parseFloat(s.trim())))
      .filter(p => p.length === 2 && p.every(Number.isFinite));
    if (pts.length < 3) throw new Error('敷地の頂点が3つ以上必要です');
    return E.ensureCCW(E.dedupeRing(pts));
  }

  /* 各辺の入力欄を組み立てる。頂点数が変わるたびに作り直すが、
   * すでに入力済みの値はできるだけ引き継ぐ。 */
  function rebuildEdgeInputs() {
    let pts;
    try { pts = sitePoints(); } catch (e) { return; }
    const container = $('edges');
    const previous = readEdgeInputs();
    container.innerHTML = '';

    // 長方形の既定: 下=道路 / 右・上・左=隣地
    const defaults = pts.length === 4 ? ['road', 'adjacent', 'adjacent', 'adjacent'] : [];

    pts.forEach((_, i) => {
      const prev = previous[i] || {};
      const kind = prev.kind || defaults[i] || 'none';
      const div = document.createElement('div');
      div.className = 'edge';
      div.innerHTML = `
        <div class="edge-head">
          <span class="no">${i + 1}</span>
          <select data-f="kind">${optionsFor(KIND_LABELS, kind)}</select>
        </div>
        <div class="row road-only"><label>道路の幅員</label>
          <input type="number" data-f="roadWidth" value="${prev.roadWidth != null ? prev.roadWidth : 6}"
                 min="0.5" step="0.5" style="width:80px"><span class="unit">m</span></div>
        <div class="row road-only"><label title="法52条9項の特定道路。この前面道路が接続している幅員15m以上の道路の幅員。0なら緩和を見込みません">特定道路の幅員</label>
          <input type="number" data-f="specRoadWidth" value="${prev.specRoadWidth != null ? prev.specRoadWidth : 0}"
                 min="0" step="0.5" style="width:80px"><span class="unit">m</span></div>
        <div class="row road-only"><label title="令135条の18 の L。特定道路から、敷地が接する前面道路の部分の直近の端までの延長。70m以内でないと効きません">特定道路からの延長</label>
          <input type="number" data-f="specRoadDist" value="${prev.specRoadDist != null ? prev.specRoadDist : 0}"
                 min="0" step="1" style="width:80px"><span class="unit">m</span></div>
        <div class="row"><label>壁面後退</label>
          <input type="number" data-f="setback" value="${prev.setback != null ? prev.setback : ''}"
                 placeholder="既定" min="0" step="0.5" style="width:80px"><span class="unit">m</span></div>
        <div class="row"><label>外側にあるもの</label>
          <select data-f="relaxKind" style="width:110px">${optionsFor(RELAX_LABELS, prev.relaxKind || 'none')}</select></div>
        <div class="row relax-only"><label>その幅</label>
          <input type="number" data-f="relaxWidth" value="${prev.relaxWidth != null ? prev.relaxWidth : 4}"
                 min="0.5" step="0.5" style="width:80px"><span class="unit">m</span></div>
        <div class="row"><label title="正なら外側（路面・隣地）が高い＝敷地が低い。負なら敷地が高い。道路斜線の緩和（令135条の2）は敷地が高いとき、隣地・北側（令135条の3/4）は敷地が低いときに効きます">高低差（正=敷地が低い）</label>
          <input type="number" data-f="levelDiff" value="${prev.levelDiff != null ? prev.levelDiff : 0}"
                 step="0.5" style="width:80px"><span class="unit">m</span></div>
      `;
      container.appendChild(div);
      div.querySelectorAll('select, input').forEach(el => {
        el.addEventListener('change', () => { updateEdgeVisibility(div); drawPlan(); });
      });
      updateEdgeVisibility(div);
    });
  }

  function optionsFor(labels, selected) {
    return Object.entries(labels)
      .map(([v, t]) => `<option value="${v}"${v === selected ? ' selected' : ''}>${t}</option>`)
      .join('');
  }

  // 種別に関係ない欄は隠して、入力を分かりやすくする
  function updateEdgeVisibility(div) {
    const kind = div.querySelector('[data-f=kind]').value;
    const relax = div.querySelector('[data-f=relaxKind]').value;
    div.querySelectorAll('.road-only').forEach(el => {
      el.style.display = kind === 'road' ? '' : 'none';
    });
    div.querySelector('.relax-only').style.display = relax === 'none' ? 'none' : '';
  }

  function readEdgeInputs() {
    return Array.from(document.querySelectorAll('#edges .edge')).map(div => {
      const get = f => div.querySelector(`[data-f=${f}]`);
      return {
        kind: get('kind').value,
        roadWidth: parseFloat(get('roadWidth').value),
        setback: get('setback').value === '' ? null : parseFloat(get('setback').value),
        relaxKind: get('relaxKind').value,
        relaxWidth: parseFloat(get('relaxWidth').value),
        specRoadWidth: parseFloat(get('specRoadWidth').value) || 0,
        specRoadDist: parseFloat(get('specRoadDist').value) || 0,
        levelDiff: parseFloat(get('levelDiff').value) || 0,
      };
    });
  }

  function buildSite() {
    const pts = sitePoints();
    const specs = readEdgeInputs();
    const defaultSetback = +$('setback').value || 0;
    const abs = $('abs-height').value === '' ? null : +$('abs-height').value;

    const edges = pts.map((p1, i) => {
      const s = specs[i] || {};
      const relaxKind = s.relaxKind || 'none';
      return {
        p1, p2: pts[(i + 1) % pts.length],
        kind: s.kind || 'none',
        roadWidthM: s.kind === 'road' ? (s.roadWidth || 6) : 0,
        wallSetbackM: s.setback != null && Number.isFinite(s.setback) ? s.setback : defaultSetback,
        groundLevelDiffM: s.levelDiff || 0,
        relaxation: { kind: relaxKind, widthM: relaxKind === 'none' ? 0 : (s.relaxWidth || 0) },
        // 法52条9項の特定道路。容積率（法52条2項〜7項）だけに効く
        specifiedRoad: s.kind === 'road'
          ? { widthM: s.specRoadWidth || 0, distanceM: s.specRoadDist || 0 }
          : { widthM: 0, distanceM: 0 },
      };
    });

    return {
      points: pts, edges,
      zoning: {
        zoneType: $('zone').value,
        farRatio: +$('far').value / 100,
        coverageRatio: +$('coverage').value / 100,
        absoluteHeightLimitM: abs,
      },
      northAngleDeg: +$('north-angle').value || 0,
      floorHeightM: +$('floor-height').value || 3.2,
    };
  }

  function buildShadowSpec() {
    if (!$('shadow-on').checked) return null;
    return {
      measurementHeightM: +$('mh').value,
      line5mMaxHours: +$('h5').value,
      line10mMaxHours: +$('h10').value,
      latitudeDeg: +$('lat').value,
      hokkaido: $('hokkaido').checked,
      timeStepMinutes: 20,
      sampleIntervalM: 4,
      applyDeemedBoundary: true,
    };
  }

  // 等時間日影図の時間（カンマ区切り、空欄なら計算しない）
  function isochroneHours() {
    return $('iso-hours').value.split(',')
      .map(s => parseFloat(s.trim())).filter(v => Number.isFinite(v) && v > 0);
  }

  const meshOptions = () => ({
    cellSizeXM: +$('cell-x').value, cellSizeYM: +$('cell-y').value, coverageThreshold: 0.5,
    useSkyRatio: $('sky-on').checked,
    // 空欄なら条文の間隔（令135条の9〜11）。入れるとそこまで細かくできる
    skyRatioIntervalM: +$('sky-interval').value || null,
    skyRatioNAzimuth: +$('sky-n-azimuth').value || 72,
  });

  // ===== 平面図 =======================================================
  const planCanvas = $('cplan');
  const planCtx = planCanvas.getContext('2d');

  function css(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

  function drawPlan() {
    const w = planCanvas.clientWidth, h = planCanvas.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    planCanvas.width = Math.round(w * dpr);
    planCanvas.height = Math.round(h * dpr);
    planCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    planCtx.clearRect(0, 0, w, h);

    let site;
    try { site = buildSite(); } catch (e) { return; }

    // 道路の帯まで含めた範囲に収める
    const all = site.points.slice();
    site.edges.forEach(e => {
      if (e.kind !== 'road') return;
      const n = E.interiorNormal(e.p1, e.p2);
      all.push([e.p1[0] - e.roadWidthM * n[0], e.p1[1] - e.roadWidthM * n[1]]);
      all.push([e.p2[0] - e.roadWidthM * n[0], e.p2[1] - e.roadWidthM * n[1]]);
    });
    const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    const minx = Math.min(...xs), maxx = Math.max(...xs);
    const miny = Math.min(...ys), maxy = Math.max(...ys);
    const pad = 56;
    const baseScale = Math.min((w - pad * 2) / Math.max(maxx - minx, 1e-6),
                               (h - pad * 2) / Math.max(maxy - miny, 1e-6));
    const scale = baseScale * planZoom;
    const cx0 = planCenter ? planCenter.x : (minx + maxx) / 2;
    const cy0 = planCenter ? planCenter.y : (miny + maxy) / 2;
    const T = p => [w / 2 + (p[0] - cx0) * scale, h / 2 - (p[1] - cy0) * scale];
    lastPlanView = { baseScale, cx0, cy0, w, h };

    const path = (pts, close) => {
      planCtx.beginPath();
      pts.forEach((p, i) => { const s = T(p); i ? planCtx.lineTo(s[0], s[1]) : planCtx.moveTo(s[0], s[1]); });
      if (close) planCtx.closePath();
    };

    // 道路
    planCtx.fillStyle = css('--road');
    site.edges.forEach(e => {
      if (e.kind !== 'road') return;
      const n = E.interiorNormal(e.p1, e.p2), d = e.roadWidthM;
      path([e.p1, e.p2, [e.p2[0] - d * n[0], e.p2[1] - d * n[1]],
            [e.p1[0] - d * n[0], e.p1[1] - d * n[1]]], true);
      planCtx.fill();
    });

    // 建物（計算済みなら階数ごとの濃さで塗る）
    if (lastResult && lastResult.area) {
      const maxF = Math.max(1, ...lastResult.floors);
      lastResult.area.cells.forEach((cell, i) => {
        const f = lastResult.floors[i];
        if (!f) return;
        planCtx.fillStyle = `rgba(201,139,75,${0.25 + 0.6 * (f / maxF)})`;
        path(cell.rect, true);
        planCtx.fill();
        if (scale * lastResult.area.cellSizeXM > 22) {
          const c = T(cell.center);
          planCtx.fillStyle = '#3a2a17';
          planCtx.font = `${Math.min(13, scale * 0.55)}px sans-serif`;
          planCtx.textAlign = 'center'; planCtx.textBaseline = 'middle';
          planCtx.fillText(String(f), c[0], c[1]);
        }
      });
    }

    // 壁面後退線
    const outline = E.buildingOutline(site);
    if (outline && site.edges.some(e => e.wallSetbackM > 0)) {
      planCtx.strokeStyle = css('--accent'); planCtx.lineWidth = 1.2;
      planCtx.setLineDash([6, 4]);
      path(outline, true); planCtx.stroke();
      planCtx.setLineDash([]);
    }

    // 敷地境界（辺の種別で色分け）
    planCtx.lineWidth = 2.5;
    site.edges.forEach(e => {
      planCtx.strokeStyle = e.kind === 'road' ? '#2f6fd0'
                          : e.kind === 'adjacent' ? css('--site') : '#aaa';
      path([e.p1, e.p2], false); planCtx.stroke();
    });

    // 辺の番号
    planCtx.font = '11px sans-serif';
    planCtx.textAlign = 'center'; planCtx.textBaseline = 'middle';
    site.edges.forEach((e, i) => {
      const mid = [(e.p1[0] + e.p2[0]) / 2, (e.p1[1] + e.p2[1]) / 2];
      const n = E.interiorNormal(e.p1, e.p2);
      const s = T([mid[0] - n[0] * 1.6, mid[1] - n[1] * 1.6]);
      planCtx.fillStyle = css('--panel');
      planCtx.beginPath(); planCtx.arc(s[0], s[1], 9, 0, Math.PI * 2); planCtx.fill();
      planCtx.strokeStyle = css('--border'); planCtx.lineWidth = 1; planCtx.stroke();
      planCtx.fillStyle = css('--text');
      planCtx.fillText(String(i + 1), s[0], s[1]);
    });

    drawNorth(w, h, site.northAngleDeg);
  }

  function drawNorth(w, h, angleDeg) {
    const [nx, ny] = E.northVector(angleDeg);
    // 右上は #status パネル（計算結果）と重なるので、左上の空きに置く
    const cx = 42, cy = 42, r = 21;
    planCtx.strokeStyle = css('--border'); planCtx.lineWidth = 1;
    planCtx.beginPath(); planCtx.arc(cx, cy, r, 0, Math.PI * 2); planCtx.stroke();
    planCtx.strokeStyle = '#e05252'; planCtx.lineWidth = 2.2;
    planCtx.beginPath(); planCtx.moveTo(cx, cy); planCtx.lineTo(cx + nx * r, cy - ny * r); planCtx.stroke();
    planCtx.fillStyle = '#e05252'; planCtx.font = 'bold 11px sans-serif';
    planCtx.textAlign = 'center'; planCtx.textBaseline = 'middle';
    planCtx.fillText('N', cx + nx * (r + 9), cy - ny * (r + 9));
  }

  // ===== 3D用データ ===================================================
  function viewerData(result, shadowSpec, isochroneResult) {
    const site = result.site;
    const xs = site.points.map(p => p[0]), ys = site.points.map(p => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    // ビューアは +Y を北として描くので、真北のずれぶん回してから渡す
    const a = (site.northAngleDeg * Math.PI) / 180;
    const ca = Math.cos(a), sa = Math.sin(a);
    const T = (x, y) => [Math.round(((x - cx) * ca + (y - cy) * sa) * 1000) / 1000,
                         Math.round((-(x - cx) * sa + (y - cy) * ca) * 1000) / 1000];

    const faces = [];
    for (const block of result.blocks) {
      for (const rect of block.rects) {
        const ring = rect.map(p => T(p[0], p[1]));
        const zb = block.zBottom, zt = block.zTop;
        for (let i = 0; i < ring.length; i++) {
          const p = ring[i], q = ring[(i + 1) % ring.length];
          faces.push({ k: 'wall', v: [[p[0], p[1], zb], [q[0], q[1], zb], [q[0], q[1], zt], [p[0], p[1], zt]] });
        }
        faces.push({ k: 'top', v: ring.map(p => [p[0], p[1], zt]) });
        faces.push({ k: 'bottom', v: ring.slice().reverse().map(p => [p[0], p[1], zb]) });
      }
    }

    // 斜線制限のエンベロープ（比較用）を階段状に作る
    const envelope = [];
    const fh = site.floorHeightM;
    const topLimit = Math.max(...result.area.cells.map(c => isFinite(c.heightLimitM) ? c.heightLimitM : 0), fh);
    const layers = 14;
    for (let k = 0; k < layers; k++) {
      const zb = (topLimit * k) / layers, zt = (topLimit * (k + 1)) / layers;
      for (const cell of result.area.cells) {
        if (cell.heightLimitM <= zb + 1e-9) continue;
        const ring = cell.rect.map(p => T(p[0], p[1]));
        const top = Math.min(zt, cell.heightLimitM);
        if (top <= zb) continue;
        envelope.push({ k: 'top', v: ring.map(p => [p[0], p[1], top]) });
        for (let i = 0; i < ring.length; i++) {
          const p = ring[i], q = ring[(i + 1) % ring.length];
          envelope.push({ k: 'wall', v: [[p[0], p[1], zb], [q[0], q[1], zb], [q[0], q[1], top], [p[0], p[1], top]] });
        }
      }
    }

    const roads = site.edges
      .map((e, i) => (e.kind === 'road' ? { i, e } : null))
      .filter(Boolean)
      .map(({ i, e }) => {
        const n = E.interiorNormal(e.p1, e.p2), w = e.roadWidthM;
        const quad = [e.p1, e.p2,
          [e.p2[0] - w * n[0], e.p2[1] - w * n[1]],
          [e.p1[0] - w * n[0], e.p1[1] - w * n[1]]].map(p => T(p[0], p[1]));
        return {
          widthM: w, quad,
          opposite: E.oppositeBoundaryLine(site, i).map(p => T(p[0], p[1])),
        };
      });

    const shadowLines = shadowSpec ? {
      m5: E.shadowMeasurementPoints(site, shadowSpec, 5.0).map(p => T(p[0], p[1])),
      m10: E.shadowMeasurementPoints(site, shadowSpec, 10.0).map(p => T(p[0], p[1])),
    } : null;

    // 等時間日影図（ビューア座標系の { レベル: [{points, closed}, ...] } に変換する）
    const isochrones = {};
    if (isochroneResult) {
      for (const [level, polylines] of Object.entries(isochroneResult)) {
        isochrones[level] = polylines.map(([points, closed]) => ({
          points: points.map(p => T(p[0], p[1])), closed,
        }));
      }
    }

    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys),
                          O.maxHeight(result), 10);
    return {
      site: site.points.map(p => T(p[0], p[1])),
      final: faces, baseline: envelope, roads, shadowLines, isochrones,
      summary: O.summaryLinesJa(result),
      radius: span * 0.75 || 1,
    };
  }

  // ===== 実行 =========================================================
  function run() {
    $('run').disabled = true;
    $('status').textContent = '計算中です…';
    setTimeout(() => {
      try {
        const site = buildSite();
        const shadowSpec = buildShadowSpec();
        lastResult = O.optimize(site, shadowSpec, meshOptions());
        lastShadowSpec = shadowSpec;
        renderSummary(O.summaryLinesJa(lastResult));

        lastIsochroneHours = shadowSpec ? isochroneHours() : [];
        lastIsochrones = (lastIsochroneHours.length && lastResult.area)
          ? I.siteIsochrones(lastResult.site, lastResult.area, lastResult.floors, shadowSpec,
                              lastIsochroneHours, +$('iso-interval').value || 2.0)
          : null;

        window.JwcadVolumeViewer.setData(viewerData(lastResult, shadowSpec, lastIsochrones));
        drawPlan();
        const fa = O.totalFloorArea(lastResult);
        $('status').textContent = fa > 0
          ? `延床 ${fa.toFixed(0)} m2 / 最高 ${O.maxHeight(lastResult).toFixed(1)} m / ${Math.max(...lastResult.floors)}階`
          : '建てられるボリュームがありません。条件を見直してください。';
      } catch (err) {
        $('status').textContent = 'エラー: ' + err.message;
        console.error(err);
      } finally {
        $('run').disabled = false;
      }
    }, 30);
  }

  function renderSummary(lines) {
    $('summary-body').innerHTML = lines.map((s, i) => {
      const safe = s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
      return `<div${i < 4 && i > 1 ? ' class="big"' : ''}>${safe}</div>`;
    }).join('');
  }

  // 容積率が道路幅員で下がる場合に、その場で気づけるようにする
  function updateFarNote() {
    try {
      const far = E.computeFar(buildSite());
      $('far-note').textContent = far.notes.length ? far.notes[0] : '';
      $('far-note').className = far.roadFar != null && far.roadFar < far.designated ? 'hint warn' : 'hint';
    } catch (e) { $('far-note').textContent = ''; }
  }

  // ===== 設定YAML =====================================================
  function toYaml() {
    const site = buildSite();
    const spec = buildShadowSpec();
    const z = site.zoning;
    const out = [
      '# MVE 設定ファイル（Web版から書き出し）',
      'site:',
      '  points:',
      ...site.points.map(p => `    - [${p[0]}, ${p[1]}]`),
      `  north_angle_deg: ${site.northAngleDeg}`,
      '  edges:',
    ];
    for (const e of site.edges) {
      out.push(`    - kind: ${e.kind}`);
      if (e.kind === 'road') out.push(`      road_width_m: ${e.roadWidthM}`);
      out.push(`      wall_setback_m: ${e.wallSetbackM}`);
      // 符号つき。負なら敷地が外側より高い（道路斜線の緩和はこちら向き）
      if (e.groundLevelDiffM) out.push(`      ground_level_diff_m: ${e.groundLevelDiffM}`);
      if (e.relaxation.kind !== 'none') {
        out.push('      relaxation:', `        kind: ${e.relaxation.kind}`,
                 `        width_m: ${e.relaxation.widthM}`);
      }
      if (e.specifiedRoad && e.specifiedRoad.widthM > 0) {
        out.push('      specified_road:', `        width_m: ${e.specifiedRoad.widthM}`,
                 `        distance_m: ${e.specifiedRoad.distanceM}`);
      }
    }
    out.push('  zoning:',
      `    zone_type: ${z.zoneType}`,
      `    far_ratio: ${z.farRatio}`,
      `    coverage_ratio: ${z.coverageRatio}`,
      `    absolute_height_limit_m: ${z.absoluteHeightLimitM === null ? 'null' : z.absoluteHeightLimitM}`,
      `  floor_height_m: ${site.floorHeightM}`,
      '', 'mesh:',
      `  cell_size_x_m: ${+$('cell-x').value}`,
      `  cell_size_y_m: ${+$('cell-y').value}`);
    if ($('sky-on').checked) {
      out.push(
        '  use_sky_ratio: true',
        `  sky_ratio_interval_m: ${+$('sky-interval').value || 4.0}`,
        `  sky_ratio_n_azimuth: ${+$('sky-n-azimuth').value || 72}`);
    }
    if (spec) {
      out.push('', 'shadow:',
        `  measurement_height_m: ${spec.measurementHeightM}`,
        `  line_5m_max_hours: ${spec.line5mMaxHours}`,
        `  line_10m_max_hours: ${spec.line10mMaxHours}`,
        `  latitude_deg: ${spec.latitudeDeg}`,
        `  hokkaido: ${spec.hokkaido}`,
        `  time_step_minutes: ${spec.timeStepMinutes}`,
        `  sample_interval_m: ${spec.sampleIntervalM}`);
      const hours = isochroneHours();
      if (hours.length) {
        out.push(`  isochrone_hours: [${hours.join(', ')}]`,
          `  isochrone_grid_interval_m: ${+$('iso-interval').value || 2.0}`);
      }
    }
    out.push('', 'output:', '  dxf_path: 結果.dxf', '  html_path: 結果_3d.html', '');
    return out.join('\n');
  }

  function fromYaml(text) {
    // ブラウザ版は敷地に用途地域1つの前提。zone_split（法52条7項・法53条2項の
    // 按分）と ground_levels（令2条2項）は Python 版のみで、黙って無視すると
    // 数字が間違うので止める。
    if (/^\s*zone_split:/m.test(text)) {
      throw new Error(
        'この設定は敷地が用途地域の2以上にわたります（zone_split）。'
        + 'ブラウザ版は用途地域1つの前提なので、読み込むと容積率・建蔽率が'
        + '間違います。法52条7項・法53条2項の按分に対応した Python 版'
        + '（mvce コマンド）を使ってください。');
    }
    if (/^\s*ground_levels:/m.test(text)) {
      throw new Error(
        'この設定は地盤の高さ（ground_levels）を持っています。'
        + 'ブラウザ版は令2条2項の平均地盤面に対応していないので、'
        + 'Python 版（mvce コマンド）を使ってください。');
    }
    if (/^\s*height_district:/m.test(text)) {
      throw new Error(
        'この設定は高度地区（height_district、法58条）を持っています。'
        + 'ブラウザ版は未対応で、読み込むと高度地区を無視した過大な結果に'
        + 'なります。Python 版（mvce コマンド）を使ってください。');
    }
    if (/^\s*shadow_ground:/m.test(text)) {
      throw new Error(
        'この設定は日影の高低差緩和（shadow_ground、令135条の12第3項第2号）を'
        + '持っています。ブラウザ版は未対応で、読み込むと緩和を見込まない'
        + '厳しい側の結果になります。Python 版（mvce コマンド）を'
        + '使ってください。');
    }
    resetPlanView();
    const num = re => { const m = text.match(re); return m ? parseFloat(m[1]) : null; };
    const str = re => { const m = text.match(re); return m ? m[1].trim() : null; };

    const pts = [];
    const section = text.match(/points:\s*\n((?:\s*-\s*\[.*\]\s*\n)+)/);
    if (section) {
      for (const line of section[1].split('\n')) {
        const m = line.match(/\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]/);
        if (m) pts.push([parseFloat(m[1]), parseFloat(m[2])]);
      }
    }
    if (pts.length >= 3) {
      $('shape-mode').value = 'poly';
      $('poly-points').value = pts.map(p => `${p[0]},${p[1]}`).join('\n');
      toggleShapeMode();
    }

    const zone = str(/zone_type:\s*(\S+)/); if (zone) $('zone').value = zone;
    const far = num(/far_ratio:\s*([\d.]+)/); if (far !== null) $('far').value = far <= 20 ? far * 100 : far;
    const cov = num(/coverage_ratio:\s*([\d.]+)/); if (cov !== null) $('coverage').value = cov <= 1 ? cov * 100 : cov;
    const na = num(/north_angle_deg:\s*(-?[\d.]+)/); if (na !== null) $('north-angle').value = na;
    const fh = num(/floor_height_m:\s*([\d.]+)/); if (fh !== null) $('floor-height').value = fh;
    const abs = str(/absolute_height_limit_m:\s*(\S+)/);
    $('abs-height').value = (abs && abs !== 'null') ? abs : '';
    const cx = num(/cell_size_x_m:\s*([\d.]+)/); if (cx !== null) $('cell-x').value = cx;
    const cy = num(/cell_size_y_m:\s*([\d.]+)/); if (cy !== null) $('cell-y').value = cy;

    $('sky-on').checked = /use_sky_ratio:\s*true/.test(text);
    if ($('sky-on').checked) {
      const si = num(/sky_ratio_interval_m:\s*([\d.]+)/); if (si !== null) $('sky-interval').value = si;
      const sn = num(/sky_ratio_n_azimuth:\s*([\d.]+)/); if (sn !== null) $('sky-n-azimuth').value = sn;
    }
    toggleSky();

    const hasShadow = /\nshadow:/.test(text);
    $('shadow-on').checked = hasShadow;
    if (hasShadow) {
      const mh = num(/measurement_height_m:\s*([\d.]+)/); if (mh !== null) $('mh').value = String(mh);
      const h5 = num(/line_5m_max_hours:\s*([\d.]+)/); if (h5 !== null) $('h5').value = h5;
      const h10 = num(/line_10m_max_hours:\s*([\d.]+)/); if (h10 !== null) $('h10').value = h10;
      const lat = num(/latitude_deg:\s*([\d.]+)/); if (lat !== null) $('lat').value = lat;
      $('hokkaido').checked = /hokkaido:\s*true/.test(text);
      const isoHours = text.match(/isochrone_hours:\s*\[([^\]]*)\]/);
      $('iso-hours').value = isoHours ? isoHours[1].split(',').map(s => s.trim()).filter(Boolean).join(',') : '';
      const isoInterval = num(/isochrone_grid_interval_m:\s*([\d.]+)/);
      if (isoInterval !== null) $('iso-interval').value = isoInterval;
    }
    toggleShadow();
    rebuildEdgeInputs();

    // 辺ごとの設定を流し込む
    const blocks = text.split(/-\s*kind:/).slice(1);
    const divs = document.querySelectorAll('#edges .edge');
    blocks.forEach((block, i) => {
      const div = divs[i];
      if (!div) return;
      const get = f => div.querySelector(`[data-f=${f}]`);
      const kind = (block.match(/^\s*(\w+)/) || [])[1];
      if (kind) get('kind').value = kind;
      const rw = block.match(/road_width_m:\s*([\d.]+)/);
      if (rw) get('roadWidth').value = rw[1];
      const sb = block.match(/wall_setback_m:\s*([\d.]+)/);
      if (sb) get('setback').value = sb[1];
      // relaxation の width_m は kind とセットで読む。単独の /width_m:/ だと
      // road_width_m にも当たってしまう
      const rk = block.match(/relaxation:\s*\n\s*kind:\s*(\w+)\s*\n\s*width_m:\s*([\d.]+)/);
      if (rk) { get('relaxKind').value = rk[1]; get('relaxWidth').value = rk[2]; }
      // 法52条9項の特定道路
      const sr = block.match(/specified_road:\s*\n\s*width_m:\s*([\d.]+)\s*\n\s*distance_m:\s*([\d.]+)/);
      get('specRoadWidth').value = sr ? sr[1] : 0;
      get('specRoadDist').value = sr ? sr[2] : 0;
      const ld = block.match(/ground_level_diff_m:\s*(-?[\d.]+)/);
      if (ld) get('levelDiff').value = ld[1];
      updateEdgeVisibility(div);
    });
    drawPlan();
    updateFarNote();
  }

  // ===== 敷地JSON/CSV読み込み ===========================================
  // 解析ロジックはsite_import.js（DOM非依存・parity検証あり）。ここでは
  // 解析結果を画面に反映するだけ。
  const SI = window.MvceSiteImport;

  function applyImportedSite(imported) {
    const { points, edges, notes } = imported;
    if (points.length < 3) throw new Error('敷地の頂点が3つ以上必要です');
    resetPlanView();
    $('shape-mode').value = 'poly';
    $('poly-points').value = points.map(p => `${p[0]},${p[1]}`).join('\n');
    toggleShapeMode();
    rebuildEdgeInputs();

    if (edges) {
      const divs = document.querySelectorAll('#edges .edge');
      edges.forEach((e, i) => {
        const div = divs[i];
        if (!div) return;
        const get = f => div.querySelector(`[data-f=${f}]`);
        get('kind').value = e.kind;
        if (e.kind === 'road' && e.roadWidthM != null) get('roadWidth').value = e.roadWidthM;
        if (e.wallSetbackM != null) get('setback').value = e.wallSetbackM;
        if (e.relaxation && e.relaxation.kind && e.relaxation.kind !== 'none') {
          get('relaxKind').value = e.relaxation.kind;
          if (e.relaxation.widthM != null) get('relaxWidth').value = e.relaxation.widthM;
        }
        if (e.groundLevelDiffM != null) get('levelDiff').value = e.groundLevelDiffM;
        updateEdgeVisibility(div);
      });
    }
    drawPlan();
    updateFarNote();
    $('status').textContent = notes.length ? notes.join(' ') : '設定を読み込みました';
  }

  function download(name, text, mime) {
    const blob = new Blob([text], { type: mime || 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ===== 画面の初期化 =================================================
  function toggleShapeMode() {
    const rect = $('shape-mode').value === 'rect';
    $('rect-inputs').style.display = rect ? '' : 'none';
    $('poly-inputs').style.display = rect ? 'none' : '';
  }
  const toggleShadow = () => {
    $('shadow-inputs').style.display = $('shadow-on').checked ? '' : 'none';
  };
  const toggleSky = () => {
    $('sky-inputs').style.display = $('sky-on').checked ? '' : 'none';
  };

  function switchTab(view) {
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === view));
    document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + view));
    $('controls3d').style.display = view === 'v3d' ? '' : 'none';
    $('legend').style.display = view === 'plan' ? '' : 'none';
    // 隠れている間は canvas の幅が0なので、表示に切り替えてから測り直す
    if (view === 'plan') drawPlan(); else window.JwcadVolumeViewer.resize();
  }

  $('shape-mode').addEventListener('change', () => { resetPlanView(); toggleShapeMode(); rebuildEdgeInputs(); drawPlan(); });
  $('poly-points').addEventListener('change', () => { resetPlanView(); rebuildEdgeInputs(); drawPlan(); });
  $('shadow-on').addEventListener('change', toggleShadow);
  $('sky-on').addEventListener('change', toggleSky);
  $('run').addEventListener('click', run);
  ['width', 'depth', 'north-angle', 'setback', 'cell-x', 'cell-y'].forEach(id =>
    $(id).addEventListener('input', drawPlan));
  ['zone', 'far', 'coverage'].forEach(id => $(id).addEventListener('input', updateFarNote));
  document.querySelectorAll('.tab').forEach(t =>
    t.addEventListener('click', () => switchTab(t.dataset.view)));

  $('export-yaml').addEventListener('click', () => {
    try { download('敷地.yaml', toYaml(), 'text/yaml;charset=utf-8'); }
    catch (err) { alert('エラー: ' + err.message); }
  });
  $('import-yaml').addEventListener('click', () => $('file-input').click());
  $('file-input').addEventListener('change', ev => {
    const file = ev.target.files[0];
    if (!file) return;
    const ext = (file.name.match(/\.([^.]+)$/) || [, ''])[1].toLowerCase();
    const reader = new FileReader();
    reader.onload = () => {
      try {
        if (ext === 'json') applyImportedSite(SI.parseSiteJson(reader.result));
        else if (ext === 'csv') applyImportedSite(SI.parseSiteCsv(reader.result));
        else { fromYaml(reader.result); $('status').textContent = '設定を読み込みました'; }
      } catch (err) { alert('読み込みに失敗しました: ' + err.message); }
    };
    reader.readAsText(file);
    ev.target.value = '';
  });
  $('export-dxf').addEventListener('click', () => {
    if (!lastResult || !lastResult.area) { alert('先に「計算する」を押してください'); return; }
    try {
      const text = window.MvceDxf.buildSiteDxf(
        lastResult, lastShadowSpec, lastIsochroneHours, lastIsochrones, window.MvceDxf.JWW_UNITS_PER_METER);
      window.MvceDxf.saveDxf(text, '敷地.dxf');
    } catch (err) { alert('DXFの書き出しに失敗しました: ' + err.message); }
  });
  window.addEventListener('resize', () => { drawPlan(); window.JwcadVolumeViewer.draw(); });

  // 平面図はホイールでズーム（カーソル位置を中心に拡大縮小する）
  planCanvas.addEventListener('wheel', ev => {
    ev.preventDefault();
    if (!lastPlanView) return;
    const { baseScale, cx0, cy0, w, h } = lastPlanView;
    const rect = planCanvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const oldScale = baseScale * planZoom;
    const worldX = cx0 + (mx - w / 2) / oldScale;
    const worldY = cy0 - (my - h / 2) / oldScale;

    planZoom = Math.max(0.4, Math.min(20, planZoom * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
    const newScale = baseScale * planZoom;
    planCenter = { x: worldX - (mx - w / 2) / newScale, y: worldY + (my - h / 2) / newScale };
    drawPlan();
  }, { passive: false });

  toggleShapeMode();
  toggleShadow();
  toggleSky();
  rebuildEdgeInputs();
  updateFarNote();
  // サマリーは書式付きで自前に描くので、ビューア側の描画は止める。
  // 方位記号は右上（#statusの計算結果パネルと重なる）を避けて、その下に描く。
  window.JwcadVolumeViewer.init(
    { site: [], final: [], baseline: [], summary: [], radius: 1 },
    { canvasId: 'c3d', summaryId: null, compassTopOffset: 130 });
  switchTab('plan');
  run();
})();
