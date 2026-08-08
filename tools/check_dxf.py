"""DXFがJW-CAD（JWW）で読める形式かどうかを調べる.

    python3 tools/check_dxf.py 図面.dxf [別の図面.dxf ...]

JWWのDXF読込は古い仕様しか受け付けません。条件を外していると、読み込みは
成功したように見えるのに図面に何も表示されません。何が原因かを切り分ける
ために、ファイルの中身を実際に読んで報告します。

判定の根拠は `mve/io/dxf_pen.py` にまとめてあります。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

try:
    import ezdxf
except ImportError:
    print("ezdxf が見つかりません。リポジトリのフォルダで pip install -e . を実行してください。")
    raise SystemExit(1)

#: JWWが読めるDXFのバージョン
GOOD_VERSIONS = {"AC1009"}

#: JWWが確実に描ける要素
GOOD_TYPES = {"LINE", "TEXT", "CIRCLE", "ARC", "SOLID", "POINT"}

OK = "OK  "
NG = "NG  "


def _check(path: Path) -> bool:
    print("=" * 62)
    print(path)
    print("=" * 62)

    try:
        doc = ezdxf.readfile(str(path))
    except IOError:
        print(f"{NG}ファイルを開けません。パスが正しいか確認してください。")
        return False
    except ezdxf.DXFStructureError as exc:
        print(f"{NG}DXFとして壊れています: {exc}")
        return False

    ok = True
    msp = doc.modelspace()
    counts = Counter(e.dxftype() for e in msp)

    # 1. バージョン
    if doc.dxfversion in GOOD_VERSIONS:
        print(f"{OK}バージョン: {doc.acad_release} ({doc.dxfversion})")
    else:
        ok = False
        print(f"{NG}バージョン: {doc.acad_release} ({doc.dxfversion})")
        print("      → JWWは R12 (AC1009) を想定しています。R2000以降は読めないことがあります。")

    # 2. 要素の種類
    bad = {t: n for t, n in counts.items() if t not in GOOD_TYPES}
    print(f"    要素: {dict(counts) if counts else '（空）'}")
    if not counts:
        ok = False
        print(f"{NG}図形が1つもありません。")
    elif bad:
        ok = False
        print(f"{NG}JWWが読み飛ばす要素があります: {bad}")
        if "LWPOLYLINE" in bad:
            print("      → LWPOLYLINE はR14以降の要素です。線分(LINE)に分解する必要があります。")
    else:
        print(f"{OK}要素の種類はJWWが読めるものだけです。")

    # 3. 大きさ（mmで書かれているか）
    xs: list[float] = []
    ys: list[float] = []
    for e in msp:
        if e.dxftype() == "LINE":
            xs += [e.dxf.start.x, e.dxf.end.x]
            ys += [e.dxf.start.y, e.dxf.end.y]
    if xs:
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        print(f"    図面の大きさ: 幅 {w:.0f} × 高さ {h:.0f} （図面単位）")
        if max(w, h) < 1000:
            ok = False
            print(f"{NG}小さすぎます。mで書かれている可能性があります。")
            print("      → JWWはmmで作図します。1m=1000単位で書き出してください。")
        else:
            print(f"{OK}mmで書かれているとみて問題ない大きさです"
                  f"（実寸 約{max(w, h) / 1000:.0f}m）。")

    # 4. 日本語の文字コード
    raw = path.read_bytes()
    has_text = counts.get("TEXT", 0) > 0
    if has_text:
        if b"\\U+" in raw:
            ok = False
            print(f"{NG}日本語が \\U+XXXX にエスケープされています（JWWで文字化けします）。")
            print("      → $DWGCODEPAGE=ANSI_932 でShift-JISとして書き出してください。")
        elif b"ANSI_932" in raw:
            print(f"{OK}文字コード: Shift-JIS (ANSI_932)")
        elif any(ord(c) > 0x7F for e in msp if e.dxftype() == "TEXT"
                 for c in e.dxf.text):
            ok = False
            print(f"{NG}日本語の文字があるのに Shift-JIS ではありません。")
            print("      → $DWGCODEPAGE=ANSI_932 で書き出してください。")
        else:
            print(f"{OK}文字は半角のみなので、文字コードの問題はありません。")

    print()
    print("判定: " + ("JWWで読めるはずです。" if ok
                      else "このままではJWWで表示されません。上の NG を直してください。"))
    print()
    return ok


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    results = [_check(Path(a)) for a in argv]
    if len(results) > 1:
        print(f"まとめ: {sum(results)} / {len(results)} 件がJWWで読める形式です。")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
