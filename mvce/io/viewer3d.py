"""3Dビューア（単一HTML）の書き出し.

描画コードは `web/viewer.js` を共有します（Web版・旧jwcad_volume版と同じ）。
外部ライブラリもCDNも使わないので、ダブルクリックで開けてオフラインでも
動きます。

MVEでは「最大ボリューム（計算結果）」に加えて、比較用に
「斜線制限のエンベロープ（適合建築物）」を半透明で重ねて表示します。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..index.isochrone import site_isochrones
from ..massing import Block
from ..solvers.optimizer import OptimizeResult
from ..regulations import road_slant
from ..regulations.shadow import measurement_points
from ..regulations.sky_ratio import slant_envelope
from .dxf_pen import ensure_parent_dir


def _viewer_js_path() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "web" / "viewer.js"
    return Path(__file__).resolve().parents[2] / "web" / "viewer.js"


_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#f2f4f7; --panel:#fff; --text:#1b1f24; --muted:#5c6673; --border:#d6dbe3; --accent:#2f6fd0; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14171c; --panel:#1d2127; --text:#e8ebef; --muted:#9aa4b2; --border:#2f3540; --accent:#6ea8fe; }
  }
  * { box-sizing: border-box; }
  html, body { margin:0; height:100%; }
  body { background:var(--bg); color:var(--text); overflow:hidden;
         font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,system-ui,sans-serif; }
  #stage { position:fixed; inset:0; }
  canvas { display:block; width:100%; height:100%; cursor:grab; }
  canvas.dragging { cursor:grabbing; }
  .panel { position:fixed; background:var(--panel); border:1px solid var(--border);
           border-radius:10px; padding:12px 14px; font-size:13px; line-height:1.7;
           box-shadow:0 4px 16px rgba(0,0,0,.12); }
  #controls { top:14px; left:14px; max-width:260px; }
  #summary { bottom:14px; left:14px; max-width:340px; max-height:55vh; overflow:auto; font-size:12px; }
  #summary summary { cursor:pointer; font-weight:600; }
  #summary div { color:var(--muted); }
  #hint { bottom:14px; right:14px; color:var(--muted); font-size:12px; }
  h2 { margin:0 0 8px; font-size:13px; letter-spacing:.04em; }
  label { display:flex; align-items:center; gap:8px; cursor:pointer; }
  .swatch { width:13px; height:13px; border-radius:3px; border:1px solid rgba(0,0,0,.25); flex:none; }
  .views { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
  button { font:inherit; font-size:12px; padding:5px 10px; cursor:pointer; color:var(--text);
           background:transparent; border:1px solid var(--border); border-radius:6px; }
  button:hover { border-color:var(--accent); color:var(--accent); }
  @media (max-width:700px){ #summary,#hint{ display:none; } }
</style>
</head>
<body>
<div id="stage"><canvas id="c"></canvas></div>
<div class="panel" id="controls">
  <h2>MVE 表示</h2>
  <label><input type="checkbox" id="t-final" checked>
    <span class="swatch" style="background:#c98b4b"></span>最大ボリューム</label>
  <label><input type="checkbox" id="t-base" checked>
    <span class="swatch" style="background:#6ea8fe"></span>斜線制限エンベロープ</label>
  <label><input type="checkbox" id="t-site" checked>
    <span class="swatch" style="background:#888"></span>敷地</label>
  <label><input type="checkbox" id="t-roads" checked>
    <span class="swatch" style="background:#e0a23f"></span>道路の反対側境界線</label>
  <label><input type="checkbox" id="t-shadow" checked>
    <span class="swatch" style="background:#3fa9f5"></span>日影5m/10m測定線</label>
  <label><input type="checkbox" id="t-isochrones" checked>
    <span class="swatch" style="background:#e0c34a"></span>等時間日影図</label>
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
__VIEWER_JS__
JwcadVolumeViewer.init(__DATA__);
</script>
</body>
</html>
"""


def _faces(blocks: list[Block], cx: float, cy: float, north_angle_deg: float) -> list[dict]:
    """ブロックを面データに変換する。

    ビューアは +Y を北として描くので、真北がずれている図面は、その分だけ
    座標を回してから渡します（ビューアのコンパスと実際の方位が合うように）。
    """
    import math

    a = math.radians(north_angle_deg)
    ca, sa = math.cos(a), math.sin(a)

    def to_view(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - cx, y - cy
        return (round(dx * ca + dy * sa, 3), round(-dx * sa + dy * ca, 3))

    faces: list[dict] = []
    for block in blocks:
        ring = [(float(x), float(y)) for x, y, *_ in block.footprint.exterior.coords[:-1]]
        if len(ring) < 3:
            continue
        zb, zt = round(block.z_bottom, 3), round(block.z_top, 3)
        for i in range(len(ring)):
            x1, y1 = to_view(*ring[i])
            x2, y2 = to_view(*ring[(i + 1) % len(ring)])
            faces.append({"k": "wall", "v": [[x1, y1, zb], [x2, y2, zb], [x2, y2, zt], [x1, y1, zt]]})
        faces.append({"k": "top", "v": [[*to_view(*p), zt] for p in ring]})
        faces.append({"k": "bottom", "v": [[*to_view(*p), zb] for p in reversed(ring)]})
    return faces


def _isochrones_view(result: OptimizeResult, isochrones, to_view) -> dict:
    """等時間日影図を、ビューア座標系の {レベル文字列: [{points, closed}, ...]} に変換する。"""
    spec = result.shadow_spec
    if spec is None or not spec.isochrone_hours or result.area is None:
        return {}
    data = isochrones if isochrones is not None else site_isochrones(
        result.site, result.area, result.floors, spec, spec.isochrone_hours,
        interval_m=spec.isochrone_grid_interval_m, margin_m=spec.isochrone_margin_m,
    )
    return {
        f"{level:g}": [
            {"points": [to_view(*p) for p in points], "closed": closed}
            for points, closed in data.get(level, [])
        ]
        for level in spec.isochrone_hours
    }


def build_html(
    result: OptimizeResult, title: str = "MVE 最大ボリューム",
    isochrones: dict[float, list[tuple[list[tuple[float, float]], bool]]] | None = None,
) -> str:
    """`isochrones` は等時間日影図を計算済みなら渡す（`isochrone.site_isochrones`
    の戻り値と同じ形）。省略すると必要な場合に内部で計算する。DXFと両方
    書き出す場合は1回だけ計算して両方に渡すと計算時間を節約できる。
    """
    site = result.site
    xs = [p[0] for p in site.points]
    ys = [p[1] for p in site.points]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    angle = site.north.north_angle_deg

    import math
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    site_view = [
        [round((x - cx) * ca + (y - cy) * sa, 3), round(-(x - cx) * sa + (y - cy) * ca, 3)]
        for x, y in site.points
    ]

    # 斜線制限すべてを合成した包絡形（見せるためのもの）。
    # 天空率の適合建築物とは別物（令135条の6・7・8 は規制ごとに別の形）。
    envelope = slant_envelope(site, n_layers=16)
    top = max((b.z_top for b in envelope), default=10.0)
    span = max(max(xs) - min(xs), max(ys) - min(ys), top)

    def to_view(x: float, y: float) -> list[float]:
        dx, dy = x - cx, y - cy
        return [round(dx * ca + dy * sa, 3), round(-dx * sa + dy * ca, 3)]

    data = {
        "site": site_view,
        "final": _faces(result.blocks, cx, cy, angle),
        "baseline": _faces(envelope, cx, cy, angle),
        "summary": result.summary_lines_ja(),
        "radius": round(span * 0.75, 3) or 1.0,
        "roads": [
            {"widthM": round(edge.road_width_m, 3),
             "opposite": [to_view(*p) for p in road_slant.opposite_boundary_line(site, i)]}
            for i, edge in enumerate(site.edges) if edge.is_road
        ],
        "shadowLines": (
            {
                "m5": [to_view(*p) for p in measurement_points(site, result.shadow_spec, 5.0)],
                "m10": [to_view(*p) for p in measurement_points(site, result.shadow_spec, 10.0)],
            }
            if result.shadow_spec is not None else None
        ),
        "isochrones": _isochrones_view(result, isochrones, to_view),
    }
    try:
        viewer_js = _viewer_js_path().read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"3Dビューアの描画コードが見つかりません: {_viewer_js_path()}") from exc

    return (_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__VIEWER_JS__", viewer_js)
            .replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":"))))


def write_html(
    result: OptimizeResult, path: str, title: str = "MVE 最大ボリューム",
    isochrones: dict[float, list[tuple[list[tuple[float, float]], bool]]] | None = None,
) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_html(result, title, isochrones=isochrones))
