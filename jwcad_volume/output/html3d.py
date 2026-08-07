"""ブラウザで見る3Dビューア（単一HTMLファイル）の出力.

出来上がるHTMLは**完全に自己完結**していて、外部ライブラリもCDNも
使いません。ダブルクリックで開くだけで、マウスで回して確認できます。
オフラインでも動き、メール添付やチャットでそのまま渡せます。

three.js等を使わずCanvas 2Dの画家のアルゴリズム（面を奥から順に塗る）で
描いています。今回のような箱の積み重ね形状ではこれで十分な見た目になり、
かつライブラリを埋め込まずに済むためファイルが軽量になります。

描画部そのものは `web/viewer.js` に置いてあり、ここではその中身を読んで
HTMLに埋め込みます。Web版アプリ(web/index.html)も同じファイルを読み込む
ので、Python版の出力とWeb版で見え方が食い違うことがありません。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..envelope import EnvelopeResult
from ..mesh import Face, blocks_to_faces


def _viewer_js_path() -> Path:
    """描画コードの場所。exe化(PyInstaller)されている場合は展開先を見る。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:  # PyInstallerのonefileは実行時に一時ディレクトリへ展開する
        return Path(base) / "web" / "viewer.js"
    return Path(__file__).resolve().parents[2] / "web" / "viewer.js"


VIEWER_JS_PATH = _viewer_js_path()

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
__VIEWER_JS__
JwcadVolumeViewer.init(__DATA__);
</script>
</body>
</html>
"""


def _viewer_js() -> str:
    """共通の描画コードを読み込む。

    exe化(PyInstaller)された場合はソースツリーが無いので、
    packaging の spec で web/viewer.js を同梱している。
    """
    path = _viewer_js_path()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # 同梱漏れに気づけるよう、原因を明示して失敗させる
        raise RuntimeError(
            f"3Dビューアの描画コードが見つかりません: {path}\n"
            "（exe化した場合は packaging/*.spec の datas に web/viewer.js が"
            "入っているか確認してください）"
        ) from exc


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
        .replace("__VIEWER_JS__", _viewer_js())
        .replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    )


def write_viewer_html(result: EnvelopeResult, path: str, title: str = "最大ボリューム 3Dビュー") -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_viewer_html(result, title))
