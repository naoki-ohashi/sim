"""MVE のWeb版UIを単一HTMLファイルにまとめる。

    python3 tools/build_mvce_web.py

出来上がるもの:
    dist/MVCE.html   … これ1つで動く（ダブルクリックで開く）

web/mvce/ は保守しやすいようファイルを分けてありますが、配布用には
1ファイルの方が扱いやすいので結合します。通信は一切しないので、
USBメモリで持ち歩いてもメール添付でもそのまま動きます。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MVCE = WEB / "mvce"
OUT = ROOT / "dist" / "MVCE.html"

# index.html の <script src=...> と同じ順番で結合する
SCRIPTS = [MVCE / "engine.js", MVCE / "optimizer.js", MVCE / "isochrone.js",
           MVCE / "site_import.js", MVCE / "cp932_table.js", MVCE / "dxf.js",
           WEB / "viewer.js", MVCE / "app.js"]
SRC_TAGS = ['<script src="engine.js"></script>',
            '<script src="optimizer.js"></script>',
            '<script src="isochrone.js"></script>',
            '<script src="site_import.js"></script>',
            '<script src="cp932_table.js"></script>',
            '<script src="dxf.js"></script>',
            '<script src="../viewer.js"></script>',
            '<script src="app.js"></script>']


def build() -> str:
    html = (MVCE / "index.html").read_text(encoding="utf-8")
    for tag in SRC_TAGS:
        if tag not in html:
            raise SystemExit(f"index.html に {tag} が見つかりません")

    blocks = []
    for path in SCRIPTS:
        source = path.read_text(encoding="utf-8")
        # 埋め込む中に </script> があるとHTMLパーサがそこで閉じてしまう
        source = source.replace("</script>", "<\\/script>")
        blocks.append(f"<script>\n{source}\n</script>")

    html = html.replace(SRC_TAGS[0], "\n".join(blocks))
    for tag in SRC_TAGS[1:]:
        html = html.replace(tag, "")
    return html


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    print("ブラウザでダブルクリックして開けます（通信は一切しません）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
