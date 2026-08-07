"""MVE のコマンドライン.

    mve 設定.yaml [--dxf-out 図面.dxf] [--html-out 3d.html]

設定YAMLの書き方は examples/mve_sample.yaml を参照してください。
"""
from __future__ import annotations

import argparse
import sys

from .config import load_project
from .io.drawing import write_dxf
from .io.viewer3d import write_html
from .optimizer import optimize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mve",
        description="MVE — 日影規制・斜線制限をふまえた最大容積の計算",
    )
    parser.add_argument("config", help="設定YAML（examples/mve_sample.yaml 参照）")
    parser.add_argument("--dxf-out", help="図面の出力先（設定の output.dxf_path を上書き）")
    parser.add_argument("--html-out", help="3Dビューアの出力先（output.html_path を上書き）")
    parser.add_argument("--no-shadow", action="store_true", help="日影規制のチェックを省略する")
    parser.add_argument("--cell", type=float, help="メッシュのXY幅(m)をまとめて指定する")
    args = parser.parse_args(argv)

    try:
        project = load_project(args.config)
    except (OSError, ValueError, KeyError) as exc:
        print(f"設定の読み込みに失敗しました: {exc}", file=sys.stderr)
        return 1

    if args.cell:
        project.options.cell_size_x_m = args.cell
        project.options.cell_size_y_m = args.cell

    for note in project.notes:
        print(f"[敷地] {note}")

    result = optimize(
        project.site,
        None if args.no_shadow else project.shadow,
        project.options,
    )
    for line in result.summary_lines_ja():
        print(line)

    dxf_path = args.dxf_out or project.output.dxf_path
    if dxf_path:
        write_dxf(result, dxf_path,
                  draw_mesh=project.output.draw_mesh,
                  draw_floor_labels=project.output.draw_floor_labels)
        print(f"図面を書き出しました: {dxf_path}")

    html_path = args.html_out or project.output.html_path
    if html_path:
        write_html(result, html_path)
        print(f"3Dビューアを書き出しました: {html_path}（ブラウザで開けます）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
