"""JW-CADで「どこまでなら読めるか」を切り分けるためのテストDXFを作る.

    python3 tools/make_jww_test_dxf.py [出力先フォルダ]

DXFを読み込んでも図面に何も表示されないとき、原因は複数考えられます。
単純なファイルから順に複雑にしたものを並べて作るので、**どれが表示されて
どれが表示されないか**を見れば、原因が1つに絞れます。

| ファイル | 足したもの | 表示されなければ |
|---|---|---|
| `01_線だけ.dxf` | 10m四方の線4本のみ（レイヤ0） | 読込操作そのものを見直す |
| `02_文字あり.dxf` | 半角と日本語の文字 | 文字（文字スタイル・文字コード）が原因 |
| `03_レイヤ4枚.dxf` | 名前付きレイヤ4枚 | レイヤ名が原因 |
| `04_レイヤ19枚.dxf` | レイヤ19枚（本番と同じ数） | JW-CADのレイヤ上限（16枚）が原因 |
| `05_ezdxf版.dxf` | 01と同じ図形をezdxfで出力 | ezdxfが付ける要素（ハンドル等）が原因 |

すべて 10m四方＝10000mm四方の正方形で、同じ大きさです。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mve.io.dxf_pen import JwwDrawing          # noqa: E402
from mve.io.dxf_r12 import R12Drawing          # noqa: E402

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _cross(pen, layer="0", color=7):
    """正方形＋対角線。少ない線数で「向き」と「大きさ」が分かる形。"""
    pen.polyline(SQUARE, layer, color)
    pen.line(SQUARE[0], SQUARE[2], layer, color)
    pen.line(SQUARE[1], SQUARE[3], layer, color)


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    # 01 線だけ
    pen = R12Drawing()
    _cross(pen)
    made.append(out_dir / "01_線だけ.dxf")
    pen.save(str(made[-1]))

    # 02 文字あり
    pen = R12Drawing()
    _cross(pen)
    pen.text("ABC 123", (0.5, 8.5), 0.8, "0", 7)
    pen.text("日本語テスト", (0.5, 6.5), 0.8, "0", 7)
    made.append(out_dir / "02_文字あり.dxf")
    pen.save(str(made[-1]))

    # 03 レイヤ4枚
    pen = R12Drawing()
    for i, (layer, color) in enumerate(
            [("MVE-SITE", 7), ("MVE-ROAD", 8), ("MVE-MESH", 3), ("MVE-OUTLINE", 5)]):
        y = i * 2.0
        pen.line((0.0, y), (10.0, y), layer, color)
    _cross(pen)
    made.append(out_dir / "03_レイヤ4枚.dxf")
    pen.save(str(made[-1]))

    # 04 レイヤ19枚（本番と同じ数）
    pen = R12Drawing()
    _cross(pen)
    for i in range(19):
        y = i * 0.5
        pen.line((0.0, y), (10.0, y), f"MVE-TEST-{i:02d}", (i % 7) + 1)
    made.append(out_dir / "04_レイヤ19枚.dxf")
    pen.save(str(made[-1]))

    # 05 ezdxf版（01と同じ図形）
    pen = JwwDrawing()
    pen.add_layer("0", 7)
    _cross(pen)
    made.append(out_dir / "05_ezdxf版.dxf")
    pen.save(str(made[-1]))

    return made


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else Path("JWW切り分けテスト")
    made = build(out_dir)
    print(f"{len(made)}個のテストファイルを作りました: {out_dir.resolve()}")
    for path in made:
        print(f"  {path.name}  ({path.stat().st_size:,} バイト)")
    print()
    print("番号の順にJW-CADで開いて、どれが表示されるか確認してください。")
    print("すべて10m四方の正方形＋対角線です（表示されれば四角にバツ印が見えます）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
