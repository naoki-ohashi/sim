"""`.FCStd` から床面積表を作るコマンド。

    freecad-floor-area 建物.FCStd
    freecad-floor-area 建物.FCStd -o 床面積集計表.xlsx

FreeCADの起動は不要です（保存済みの面積の値を読みます）。
FreeCADの中から実行したい場合は `freecad/床面積集計.FCMacro` を使って
ください。
"""
from __future__ import annotations

import argparse
import os
import sys

from .export import ExportError, openpyxl_available, write_area_table
from .fcstd import FcstdError, any_object_with_area, read_rooms
from .table import build_table

DEFAULT_SUFFIX = "_床面積"


def default_output_path(source: str, *, prefer_xlsx: bool = True) -> str:
    """入力と同じ場所に `◯◯_床面積.xlsx`（openpyxlが無ければ .csv）。"""
    stem, _ = os.path.splitext(source)
    ext = ".xlsx" if (prefer_xlsx and openpyxl_available()) else ".csv"
    return f"{stem}{DEFAULT_SUFFIX}{ext}"


def format_table(headers, body) -> str:
    """標準出力用に、桁を揃えた文字列にする。"""
    def cell(value) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    rows = [[cell(v) for v in headers]] + [[cell(v) for v in row] for row in body]

    def width(text: str) -> int:
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)

    widths = [max(width(row[i]) for row in rows) for i in range(len(headers))]
    lines = []
    for row in rows:
        parts = [text + " " * (widths[i] - width(text)) for i, text in enumerate(row)]
        lines.append("  ".join(parts).rstrip())
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freecad-floor-area",
        description="FreeCADの.FCStdから部屋（Arch Space）の床面積表を書き出します。",
    )
    parser.add_argument("fcstd", help="読み込む .FCStd ファイル")
    parser.add_argument(
        "-o", "--output",
        help="出力先（.xlsx または .csv）。省略すると入力と同じ場所に作ります。",
    )
    parser.add_argument(
        "--all-areas", action="store_true",
        help="Space以外でも面積(Area)を持つオブジェクトをすべて集計する",
    )
    parser.add_argument(
        "--sheet", default="床面積表", help="Excelのシート名（既定: 床面積表）",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="集計結果を表示しない")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        rooms = read_rooms(
            args.fcstd, predicate=any_object_with_area if args.all_areas else None
        )
    except FcstdError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    if not rooms:
        print(
            "部屋（Arch Space）が見つかりませんでした。\n"
            "  * BIM/Archワークベンチの「スペース」で部屋を作っているか確認してください。\n"
            "  * 面積を持つ他のオブジェクトも集計するなら --all-areas を付けてください。\n"
            "  * 形状はあるが面積プロパティが無い場合は、FreeCADの中で"
            "freecad/床面積集計.FCMacro を実行してください。",
            file=sys.stderr,
        )
        return 2

    output = args.output or default_output_path(args.fcstd)
    try:
        write_area_table(rooms, output, sheet_title=args.sheet)
    except ExportError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    unknown = [r.name for r in rooms if r.floor_area_m2 is None]
    if not args.quiet:
        headers, body = build_table(rooms)
        print(format_table(headers, body))
        print()
    if unknown:
        print(
            "面積が取れなかった部屋（空欄・合計に含めていません）: "
            + "、".join(unknown),
            file=sys.stderr,
        )
    print(f"書き出しました: {output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
