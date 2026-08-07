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

  let DATA = { site: [], final: [], baseline: [], summary: [], radius: 1 };


  let canvas, ctx;

  const HOME = { az: 225, el: 30, zoom: 1, panX: 0, panY: 0 };
  let view = Object.assign({}, HOME);

  const show = { final: true, base: true, site: true };

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

  function drawSite(proj) {
    const ring = DATA.site;
    if (!ring.length) return;
    ctx.beginPath();
    ring.forEach((p, i) => {
      const s = toScreen(proj.project([p[0], p[1], 0]));
      i ? ctx.lineTo(s[0], s[1]) : ctx.moveTo(s[0], s[1]);
    });
    ctx.closePath();
    ctx.strokeStyle = '#7a8492';
    ctx.lineWidth = 2;
    ctx.setLineDash([7, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
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
    for (const [id, key] of [['t-final', 'final'], ['t-base', 'base'], ['t-site', 'site']]) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', e => { show[key] = e.target.checked; draw(); });
    }
  }

  function renderSummary() {
    const body = document.getElementById('summary-body');
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

  function init(initialData) {
    if (initialData) DATA = initialData;
    canvas = document.getElementById('c');
    ctx = canvas.getContext('2d');
    bindEvents();
    renderSummary();
    window.addEventListener('resize', resize);
    resize();
  }

  global.JwcadVolumeViewer = { init, setData, draw, resetView };
})(typeof window !== 'undefined' ? window : globalThis);
