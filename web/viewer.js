/* jwcad-volume 3Dビューア（描画部）
 *
 * このファイルは2か所から使われます。
 *   1. Python版の出力 (jwcad_volume/output/html3d.py) が中身をそのまま埋め込む
 *   2. Web版アプリ (web/index.html) が <script src> で読み込む
 * 同じ描画コードを共有することで、両者の見え方が食い違わないようにしています。
 *
 * three.js等の外部ライブラリは使わず、Canvas 2Dの画家のアルゴリズム
 * （面を奥から順に塗る）＋裏面カリングで描いています。箱の積み重ね形状
 * ではこれで十分な見た目になり、CDNもオフライン制約も気にせずに済みます。
 *
 * 使い方: グローバルに DATA（site/final/baseline/summary/radius）を用意して
 * から JwcadVolumeViewer.init() を呼びます。データを差し替える場合は
 * JwcadVolumeViewer.setData(newData) を呼ぶと再描画されます。
 */
(function (global) {
  'use strict';

  let DATA = { site: [], final: [], baseline: [], summary: [], radius: 1, roads: [], isochrones: {} };


  let canvas, ctx;
  let summaryId = 'summary-body';

  const HOME = { az: 225, el: 30, zoom: 1, panX: 0, panY: 0 };
  let view = Object.assign({}, HOME);

  const show = { final: true, base: true, site: true, roads: true, shadow: true, isochrones: true };
  const ISOCHRONE_COLORS = ['#e05252', '#e0c34a', '#4ac96e', '#4ac9c9', '#4a7ee0', '#c94ae0'];

  // --- 投影 -----------------------------------------------------------
  // Python側 mesh.Axonometric と同じ式。方位角は真北から時計回り。
  function makeProjector(az, el) {
    const a = az * Math.PI / 180, e = el * Math.PI / 180;
    const ca = Math.cos(a), sa = Math.sin(a), ce = Math.cos(e), se = Math.sin(e);
    return {
      // 画面座標(x=右, y=上) と 奥行き(大きいほど遠い)
      project(p) {
        const x = p[0] * ca - p[1] * sa;
        const y = p[0] * sa + p[1] * ca;
        return [x, y * se + p[2] * ce, y * ce - p[2] * se];
      },
      // 視線方向（面の裏表判定に使う）
      viewDir() { return [sa * ce, ca * ce, -se]; }
    };
  }

  function faceNormal(v) {
    let nx = 0, ny = 0, nz = 0;
    for (let i = 0; i < v.length; i++) {
      const a = v[i], b = v[(i + 1) % v.length];
      nx += (a[1] - b[1]) * (a[2] + b[2]);
      ny += (a[2] - b[2]) * (a[0] + b[0]);
      nz += (a[0] - b[0]) * (a[1] + b[1]);
    }
    const len = Math.hypot(nx, ny, nz) || 1;
    return [nx / len, ny / len, nz / len];
  }

  const LIGHT = (() => { const v = [-0.4, -0.6, 0.7]; const n = Math.hypot(...v); return v.map(c => c / n); })();

  function shade(normal, base) {
    const d = Math.max(0, normal[0] * LIGHT[0] + normal[1] * LIGHT[1] + normal[2] * LIGHT[2]);
    const k = 0.45 + 0.55 * d;
    return `rgb(${Math.round(base[0] * k)},${Math.round(base[1] * k)},${Math.round(base[2] * k)})`;
  }

  // --- 描画 -----------------------------------------------------------
  let dpr = 1, cw = 0, ch = 0, scale = 1, cx = 0, cy = 0;

  function resize() {
    dpr = window.devicePixelRatio || 1;
    cw = canvas.clientWidth; ch = canvas.clientHeight;
    canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function toScreen(sp) {
    return [cx + sp[0] * scale + view.panX, cy - sp[1] * scale + view.panY];
  }

  function collectFaces(faces, proj) {
    const out = [];
    const vd = proj.viewDir();
    for (const f of faces) {
      const n = faceNormal(f.v);
      // 裏を向いている面は描かない（法線が視線と同じ向き）
      if (n[0] * vd[0] + n[1] * vd[1] + n[2] * vd[2] > 0) continue;
      const pts = f.v.map(p => proj.project(p));
      let depth = 0;
      for (const p of pts) depth += p[2];
      out.push({ pts, depth: depth / pts.length, normal: n, kind: f.k });
    }
    out.sort((a, b) => b.depth - a.depth); // 奥から順に
    return out;
  }

  function paint(list, color, alpha, stroke) {
    ctx.globalAlpha = alpha;
    for (const f of list) {
      ctx.beginPath();
      const p0 = toScreen(f.pts[0]);
      ctx.moveTo(p0[0], p0[1]);
      for (let i = 1; i < f.pts.length; i++) {
        const p = toScreen(f.pts[i]);
        ctx.lineTo(p[0], p[1]);
      }
      ctx.closePath();
      ctx.fillStyle = shade(f.normal, f.kind === 'top' ? color.top : color.wall);
      ctx.fill();
      if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
    }
    ctx.globalAlpha = 1;
  }

  // 汎用ポリライン描画（z=0平面）。道路の反対側境界線・日影測定線などで使う。
  function drawPolyline(proj, points, style) {
    if (!points || !points.length) return;
    const opts = Object.assign({ stroke: '#7a8492', width: 2, dash: [], close: false }, style || {});
    ctx.beginPath();
    points.forEach((p, i) => {
      const s = toScreen(proj.project([p[0], p[1], 0]));
      i ? ctx.lineTo(s[0], s[1]) : ctx.moveTo(s[0], s[1]);
    });
    if (opts.close) ctx.closePath();
    ctx.strokeStyle = opts.stroke;
    ctx.lineWidth = opts.width;
    ctx.setLineDash(opts.dash);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawSite(proj) {
    drawPolyline(proj, DATA.site, { stroke: '#7a8492', width: 2, dash: [7, 4], close: true });
  }

  // 前面道路の「反対側」とみなす基準線（令130条の12・令134条を反映）。
  function drawRoads(proj) {
    for (const road of DATA.roads || []) {
      drawPolyline(proj, road.opposite, { stroke: '#e0a23f', width: 1.5, dash: [3, 3] });
    }
  }

  // 日影規制の5m/10m測定線。
  function drawShadowLines(proj) {
    const lines = DATA.shadowLines;
    if (!lines) return;
    drawPolyline(proj, lines.m5, { stroke: '#3fa9f5', width: 1.3, dash: [2, 3], close: true });
    drawPolyline(proj, lines.m10, { stroke: '#f5734a', width: 1.3, dash: [2, 3], close: true });
  }

  // 等時間日影図（等時間日影線）。座標はPython側で計算済み（マーチングスクエア法はJS未実装）。
  function drawIsochrones(proj) {
    const iso = DATA.isochrones;
    if (!iso) return;
    Object.keys(iso).forEach((level, idx) => {
      const color = ISOCHRONE_COLORS[idx % ISOCHRONE_COLORS.length];
      for (const line of iso[level]) {
        drawPolyline(proj, line.points, { stroke: color, width: 1.3, dash: [1, 2], close: line.closed });
      }
    });
  }

  function drawCompass(proj) {
    // 真北が画面上どちらを向くかを示す（方位が分からないと斜線制限を読めない）
    const o = proj.project([0, 0, 0]), n = proj.project([0, 1, 0]);
    let dx = n[0] - o[0], dy = -(n[1] - o[1]);
    const len = Math.hypot(dx, dy) || 1;
    dx /= len; dy /= len;
    const ox = cw - 52, oy = 62, r = 22;
    ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--border');
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(ox, oy, r, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = '#e05252'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(ox + dx * r, oy + dy * r); ctx.stroke();
    ctx.fillStyle = '#e05252';
    ctx.font = '11px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('N', ox + dx * (r + 9), oy + dy * (r + 9));
  }

  function draw() {
    ctx.clearRect(0, 0, cw, ch);
    const proj = makeProjector(view.az, view.el);
    scale = (Math.min(cw, ch) * 0.36 / (DATA.radius || 1)) * view.zoom;
    cx = cw / 2; cy = ch / 2;

    if (show.site) drawSite(proj);
    if (show.roads) drawRoads(proj);
    if (show.shadow) drawShadowLines(proj);
    if (show.isochrones) drawIsochrones(proj);
    if (show.final) paint(collectFaces(DATA.final, proj), { wall: [201, 139, 75], top: [224, 170, 110] }, 1, 'rgba(0,0,0,.25)');
    // エンベロープは最後に半透明で重ね、ガラスケースのように見せる
    if (show.base) paint(collectFaces(DATA.baseline, proj), { wall: [110, 168, 254], top: [150, 195, 255] }, 0.22, 'rgba(110,168,254,.55)');
    drawCompass(proj);
  }

  // --- 操作 -----------------------------------------------------------
  function bindEvents() {
    let drag = null;
    canvas.addEventListener('pointerdown', e => {
      drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
      canvas.setPointerCapture(e.pointerId);
      canvas.classList.add('dragging');
    });
    canvas.addEventListener('pointermove', e => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.pan) { view.panX += dx; view.panY += dy; }
      else {
        view.az = (view.az - dx * 0.5) % 360;
        view.el = Math.max(-89, Math.min(89, view.el + dy * 0.4));
      }
      draw();
    });
    const endDrag = () => { drag = null; canvas.classList.remove('dragging'); };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      view.zoom = Math.max(0.2, Math.min(8, view.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      draw();
    }, { passive: false });

    document.querySelectorAll('.views button[data-az]').forEach(b => {
      b.addEventListener('click', () => {
        view.az = +b.dataset.az; view.el = +b.dataset.el; draw();
      });
    });
    const reset = document.getElementById('reset');
    if (reset) reset.addEventListener('click', resetView);
    for (const [id, key] of [['t-final', 'final'], ['t-base', 'base'], ['t-site', 'site'],
                              ['t-roads', 'roads'], ['t-shadow', 'shadow'],
                              ['t-isochrones', 'isochrones']]) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', e => { show[key] = e.target.checked; draw(); });
    }
  }

  function renderSummary() {
    if (summaryId === null) return;   // 呼び出し側が自前で描く場合
    const body = document.getElementById(summaryId);
    if (!body) return;
    body.innerHTML = DATA.summary
      .map(s => '<div>' + s.replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</div>').join('');
  }

  function resetView() {
    view = Object.assign({}, HOME);
    draw();
  }

  // 計算し直した結果を差し替える（Web版が再計算のたびに呼ぶ）
  function setData(next) {
    DATA = next;
    renderSummary();
    if (ctx) resize();
  }

  /* options（すべて省略可）:
   *   canvasId  … 描画先のcanvas要素のid（既定 'c'）
   *   summaryId … サマリーを書き込む要素のid。null を渡すと書き込まない
   *               （呼び出し側で書式を付けて描きたい場合に使う）
   * 既存の呼び出し（Python版の出力・旧Web版）は引数なしなので、既定値で
   * これまで通り動く。
   */
  function init(initialData, options) {
    if (initialData) DATA = initialData;
    const opts = options || {};
    if ('summaryId' in opts) summaryId = opts.summaryId;
    canvas = document.getElementById(opts.canvasId || 'c');
    if (!canvas) throw new Error('canvas が見つかりません: ' + (opts.canvasId || 'c'));
    ctx = canvas.getContext('2d');
    bindEvents();
    renderSummary();
    window.addEventListener('resize', resize);
    resize();
  }

  // resize は、タブなどで隠れた状態から表示に切り替えたときに必要。
  // 隠れている間は clientWidth が 0 なので、表示後に呼び直す。
  global.JwcadVolumeViewer = { init, setData, draw, resetView, resize };
})(typeof window !== 'undefined' ? window : globalThis);
