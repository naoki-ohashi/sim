"""ブラウザで見る3Dビューア（単一HTMLファイル）の出力.

出来上がるHTMLは**完全に自己完結**していて、外部ライブラリもCDNも
使いません。ダブルクリックで開くだけで、マウスで回して確認できます。
オフラインでも動き、メール添付やチャットでそのまま渡せます。

three.js等を使わずCanvas 2Dの画家のアルゴリズム（面を奥から順に塗る）で
描いています。今回のような箱の積み重ね形状ではこれで十分な見た目になり、
かつライブラリを埋め込まずに済むためファイルが軽量になります。
"""
from __future__ import annotations

import json

from ..envelope import EnvelopeResult
from ..mesh import Face, blocks_to_faces

_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #f2f4f7; --panel: #ffffff; --text: #1b1f24; --muted: #5c6673;
    --border: #d6dbe3; --accent: #2f6fd0;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14171c; --panel: #1d2127; --text: #e8ebef; --muted: #9aa4b2;
      --border: #2f3540; --accent: #6ea8fe;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    background: var(--bg); color: var(--text); overflow: hidden;
    font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, system-ui, sans-serif;
  }
  #stage { position: fixed; inset: 0; }
  canvas { display: block; width: 100%; height: 100%; cursor: grab; }
  canvas.dragging { cursor: grabbing; }
  .panel {
    position: fixed; background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; font-size: 13px; line-height: 1.7;
    box-shadow: 0 4px 16px rgba(0,0,0,.12);
  }
  #controls { top: 14px; left: 14px; max-width: 260px; }
  #summary { bottom: 14px; left: 14px; max-width: 340px; max-height: 55vh; overflow: auto; }
  #summary summary { cursor: pointer; font-weight: 600; font-size: 13px; letter-spacing: .04em; }
  #summary[open] summary { margin-bottom: 6px; }
  #hint { bottom: 14px; right: 14px; color: var(--muted); font-size: 12px; }
  h2 { margin: 0 0 8px; font-size: 13px; letter-spacing: .04em; }
  label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .swatch { width: 13px; height: 13px; border-radius: 3px; border: 1px solid rgba(0,0,0,.25); flex: none; }
  .views { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  button {
    font: inherit; font-size: 12px; padding: 5px 10px; cursor: pointer;
    color: var(--text); background: transparent;
    border: 1px solid var(--border); border-radius: 6px;
  }
  button:hover { border-color: var(--accent); color: var(--accent); }
  #summary div { color: var(--muted); }
  #summary div.head { color: var(--text); font-weight: 600; margin-bottom: 4px; }
  @media (max-width: 700px) {
    #summary { display: none; }
    #hint { display: none; }
  }
</style>
</head>
<body>
<div id="stage"><canvas id="c"></canvas></div>

<div class="panel" id="controls">
  <h2>表示</h2>
  <label><input type="checkbox" id="t-final" checked>
    <span class="swatch" style="background:#c98b4b"></span>最大ボリューム</label>
  <label><input type="checkbox" id="t-base" checked>
    <span class="swatch" style="background:#6ea8fe"></span>斜線制限エンベロープ</label>
  <label><input type="checkbox" id="t-site" checked>
    <span class="swatch" style="background:#888"></span>敷地・地盤</label>
  <div class="views">
    <button data-az="225" data-el="30">南西</button>
    <button data-az="135" data-el="30">南東</button>
    <button data-az="180" data-el="10">南から</button>
    <button data-az="180" data-el="90">真上</button>
    <button id="reset">リセット</button>
  </div>
</div>

<details class="panel" id="summary" open><summary>計算結果</summary><div id="summary-body"></div></details>
<div class="panel" id="hint">ドラッグ=回転 / ホイール=拡大縮小 / 右ドラッグ=移動</div>

<script>
const DATA = __DATA__;

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');

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
const endDrag = e => { drag = null; canvas.classList.remove('dragging'); };
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
document.getElementById('reset').addEventListener('click', () => {
  view = Object.assign({}, HOME); draw();
});
for (const [id, key] of [['t-final', 'final'], ['t-base', 'base'], ['t-site', 'site']]) {
  document.getElementById(id).addEventListener('change', e => { show[key] = e.target.checked; draw(); });
}

document.getElementById('summary-body').innerHTML =
  DATA.summary.map(s => '<div>' + s.replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</div>').join('');

window.addEventListener('resize', resize);
resize();
</script>
</body>
</html>
"""


def _faces_payload(faces: list[Face], ndigits: int = 3) -> list[dict]:
    return [
        {"v": [[round(c, ndigits) for c in vertex] for vertex in face.vertices], "k": face.kind}
        for face in faces
    ]


def build_viewer_html(result: EnvelopeResult, title: str = "最大ボリューム 3Dビュー") -> str:
    """計算結果から自己完結HTMLの文字列を組み立てる。"""
    final_faces = blocks_to_faces(result.blocks)
    baseline_faces = blocks_to_faces(result.baseline_blocks)

    site = [[round(x, 3), round(y, 3)] for x, y in result.site.points]
    xs = [p[0] for p in site]
    ys = [p[1] for p in site]
    cx = (min(xs) + max(xs)) / 2 if site else 0.0
    cy = (min(ys) + max(ys)) / 2 if site else 0.0
    top = max((b.z_top for b in result.baseline_blocks), default=10.0)
    span = max(max(xs) - min(xs), max(ys) - min(ys), top) if site else 10.0

    def recentre(payload: list[dict]) -> list[dict]:
        for face in payload:
            for vertex in face["v"]:
                vertex[0] = round(vertex[0] - cx, 3)
                vertex[1] = round(vertex[1] - cy, 3)
        return payload

    data = {
        "site": [[round(x - cx, 3), round(y - cy, 3)] for x, y in site],
        "final": recentre(_faces_payload(final_faces)),
        "baseline": recentre(_faces_payload(baseline_faces)),
        "summary": result.summary_lines_ja(),
        "radius": round(span * 0.75, 3) or 1.0,
    }
    return (
        _TEMPLATE
        .replace("__TITLE__", title)
        .replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    )


def write_viewer_html(result: EnvelopeResult, path: str, title: str = "最大ボリューム 3Dビュー") -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_viewer_html(result, title))
