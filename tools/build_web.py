"""Web版アプリを単一HTMLファイルにまとめる。

web/ 以下は保守しやすいようファイルを分けてありますが、配布や
「ダブルクリックで開く」用途にはまとめた1ファイルの方が扱いやすいので、
このスクリプトで結合します。

    python3 tools/build_web.py

出来上がるもの:
    dist/jwcad-volume-web.html   … これ1つで動くWeb版

まとめた版では、3D HTMLの書き出し機能（envelope_3d.html と同じ形式で
保存する機能）も使えるようになります。分割版では viewer.js の中身を
JavaScript側から読めないため、その機能だけ無効になります。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = ROOT / "dist" / "jwcad-volume-web.html"

SCRIPTS = ["engine.js", "envelope.js", "viewer.js", "app.js"]


def build() -> str:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    viewer_js = (WEB / "viewer.js").read_text(encoding="utf-8")

    # Python版の出力と同じHTML雛形を使えるようにしておく（書き出し機能用）
    sys.path.insert(0, str(ROOT))
    from jwcad_volume.output.html3d import _TEMPLATE  # noqa: E402

    def js_string(text: str) -> str:
        """JS文字列リテラルにする。`</script>` を含むとHTMLパーサが
        そこでスクリプトを閉じてしまうため、`</` を `<\\/` に逃がす。"""
        return json.dumps(text).replace("</", "<\\/")

    inlined = [
        "<script>",
        f"window.__VIEWER_JS_SOURCE__ = {js_string(viewer_js)};",
        f"window.__VIEWER_HTML_TEMPLATE__ = {js_string(_TEMPLATE)};",
        "</script>",
    ]
    for name in SCRIPTS:
        source = (WEB / name).read_text(encoding="utf-8")
        inlined.append("<script>\n" + source + "\n</script>")

    block = "\n".join(inlined)
    for name in SCRIPTS:
        tag = f'<script src="{name}"></script>'
        if tag not in html:
            raise SystemExit(f"index.html に {tag} が見つかりません")
        # 最初のscriptタグの位置にまとめて差し込み、残りは削除する
        html = html.replace(tag, block if name == SCRIPTS[0] else "")
    return html


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = build()
    OUT.write_text(html, encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.relative_to(ROOT)} ({size_kb:.0f} KB)")
    print("ブラウザでダブルクリックして開けます（通信は一切しません）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
