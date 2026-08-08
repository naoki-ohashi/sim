"""MVE のコマンドライン.

    mve 設定.yaml [--dxf-out 図面.dxf] [--html-out 3d.html]

設定YAMLの書き方は examples/mve_sample.yaml を参照してください。
"""
from __future__ import annotations

import argparse
import os
import sys

from .config import load_project
from .io.drawing import BACKENDS, write_dxf
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
    parser.add_argument(
        "--dxf-units", type=float, metavar="単位",
        help="DXFで1mを何単位として書くか（既定1000＝mm。JW-CADはmmなので通常そのまま）",
    )
    parser.add_argument(
        "--dxf-backend", choices=sorted(BACKENDS),
        help="DXFの書き出し方（既定r12＝JW-CAD向けの最小構成 / ezdxf＝他CAD互換重視）",
    )
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
        units = args.dxf_units or project.output.dxf_units_per_meter
        backend = args.dxf_backend or project.output.dxf_backend
        try:
            write_dxf(result, dxf_path,
                      draw_mesh=project.output.draw_mesh,
                      draw_floor_labels=project.output.draw_floor_labels,
                      units_per_meter=units, backend=backend)
        except OSError as exc:
            return _write_failed("図面", dxf_path, exc)
        print(f"図面を書き出しました: {os.path.abspath(dxf_path)}"
              f"（DXF R12・1m={units:g}単位・{backend}）")

    html_path = args.html_out or project.output.html_path
    if html_path:
        try:
            write_html(result, html_path)
        except OSError as exc:
            return _write_failed("3Dビューア", html_path, exc)
        print(f"3Dビューアを書き出しました: {os.path.abspath(html_path)}"
              "（ブラウザで開けます）")

    return 0


def _write_failed(what: str, path: str, exc: OSError) -> int:
    """書き出しに失敗した理由を、traceback ではなく日本語で伝える。"""
    print(f"{what}の書き出しに失敗しました: {path}", file=sys.stderr)
    print(f"  理由: {exc.strerror or exc}", file=sys.stderr)
    print("  出力先のドライブ名・フォルダ名が正しいか、書き込み権限があるか、"
          "同じファイルを他のソフト（JW-CADなど）で開いたままになっていないか"
          "確認してください。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
