"""JWW外部変形のエントリポイント.

JWWから起動され、次の流れで動きます。

1. JWWが選択図形を書き出した `JWC_TEMP.TXT` を読む
2. 線分群から敷地の閉じた外形を組み立てる
3. **線色**から各辺の境界種別（道路/隣地/北側）を判定する
4. 用途地域・容積率など図面から読み取れない条件は設定YAMLで補う
5. 最大ボリュームを計算し、結果を `JWC_TEMP.TXT` に上書きしてJWWへ返す

線色で境界種別を指定するのは、CAD上で自然に描き分けられるためです。
既定では 線色1=道路境界線 / 線色2=隣地境界線 / 線色3=北側境界線 とし、
設定YAMLの `boundary_colors` で変更できます。割り当てのない線色は
規制なし("none")として扱います。
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from dataclasses import dataclass, field

import yaml

from .config import EnvelopeSettings, build_envelope_settings, build_shadow_params
from .envelope import compute_max_envelope
from .jwc import UNITS_PER_METER, JwcWriter, read_jwc_file
from .output.isometric import default_origin, isometric_segments
from .regulations.shadow import ShadowRegulationParams
from .ring_builder import RingBuildError, build_ring
from .site import Boundary, Site
from .zoning import ZoningParams

DEFAULT_TEMP_NAME = "JWC_TEMP.TXT"
DEFAULT_BOUNDARY_COLORS = {"road": 1, "adjacent": 2, "north": 3}

# 書き戻す図形の線色（JWWの標準的な線色番号）
RESULT_COLOR_SITE = 1
RESULT_COLOR_ENVELOPE = 2
RESULT_COLOR_TEXT = 4
ISO_COLOR_BY_KIND = {"site": 1, "outline": 2, "vertical": 3}


@dataclass
class GaihenParams:
    """外部変形の実行条件（図面から読み取れない部分）。"""

    zoning: ZoningParams
    boundary_colors: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_BOUNDARY_COLORS))
    road_width_m: float = 6.0
    road_width_by_color: dict[int, float] = field(default_factory=dict)
    setback_m: float = 0.0
    floor_height_m: float = 3.2
    units_per_meter: float = UNITS_PER_METER
    envelope: EnvelopeSettings = field(default_factory=EnvelopeSettings)
    shadow: ShadowRegulationParams | None = None
    result_layer: int = 8
    draw_isometric: bool = True
    isometric_azimuth_deg: float = 225.0
    isometric_elevation_deg: float = 30.0


def load_gaihen_params(path: str) -> GaihenParams:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    z = data["zoning"]
    zoning = ZoningParams(
        zone_type=z["zone_type"],
        far_ratio=z["far_ratio"],
        coverage_ratio=z["coverage_ratio"],
        absolute_height_limit_m=z.get("absolute_height_limit_m"),
    )
    colors = dict(DEFAULT_BOUNDARY_COLORS)
    colors.update(data.get("boundary_colors") or {})

    return GaihenParams(
        zoning=zoning,
        boundary_colors=colors,
        road_width_m=data.get("road_width_m", 6.0),
        road_width_by_color={int(k): float(v) for k, v in (data.get("road_width_by_color") or {}).items()},
        setback_m=data.get("setback_m", 0.0),
        floor_height_m=data.get("floor_height_m", 3.2),
        units_per_meter=data.get("units_per_meter", UNITS_PER_METER),
        envelope=build_envelope_settings(data.get("envelope")),
        shadow=build_shadow_params(data.get("shadow")),
        result_layer=data.get("result_layer", 8),
        draw_isometric=data.get("draw_isometric", True),
        isometric_azimuth_deg=data.get("isometric_azimuth_deg", 225.0),
        isometric_elevation_deg=data.get("isometric_elevation_deg", 30.0),
    )


def site_from_jwc(path: str, params: GaihenParams) -> Site:
    """JWC_TEMP.TXTを読んで、線色から境界種別を判定した Site を組み立てる。"""
    doc = read_jwc_file(path, units_per_meter=params.units_per_meter)
    if not doc.lines:
        raise RingBuildError(
            "選択された図形の中に線分が見つかりませんでした。"
            "敷地の外形線（直線）を選択してから外部変形を実行してください。"
            f"（読み飛ばした行: {len(doc.unknown)}行）"
        )

    ring = build_ring(doc.lines)
    color_to_kind = {color: kind for kind, color in params.boundary_colors.items()}

    edges: list[Boundary] = []
    n = len(ring.points)
    for i in range(n):
        p1, p2 = ring.points[i], ring.points[(i + 1) % n]
        seg = ring.segments[i]
        kind = color_to_kind.get(seg.color, "none")
        road_width = 0.0
        if kind == "road":
            road_width = params.road_width_by_color.get(seg.color, params.road_width_m)
        edges.append(
            Boundary(
                p1=p1,
                p2=p2,
                kind=kind,
                road_width_m=road_width,
                setback_m=params.setback_m,
            )
        )

    return Site(
        points=ring.points,
        edges=edges,
        zoning=params.zoning,
        floor_height_m=params.floor_height_m,
    )


def write_result_jwc(result, path: str, params: GaihenParams) -> None:
    """計算結果（敷地・各段の平面輪郭・サマリー文字）をJWC形式で書き出す。"""
    w = JwcWriter(units_per_meter=params.units_per_meter)
    w.add_comment("jwcad-volume 最大ボリューム計算結果")

    w.set_attributes(layer=params.result_layer, color=RESULT_COLOR_SITE, line_type=1)
    w.add_polyline(list(result.site.points), close=True)

    w.set_attributes(color=RESULT_COLOR_ENVELOPE)
    for block in result.blocks:
        w.add_polyline([(x, y) for x, y, *_ in block.footprint.exterior.coords], close=True)

    if params.draw_isometric:
        # 平面図の右隣にアイソメ図（2Dの線分として作図）
        for p1, p2, kind in isometric_segments(
            result,
            azimuth_deg=params.isometric_azimuth_deg,
            elevation_deg=params.isometric_elevation_deg,
            origin=default_origin(result),
        ):
            w.set_attributes(color=ISO_COLOR_BY_KIND.get(kind, RESULT_COLOR_ENVELOPE))
            w.add_line(p1, p2)

    # サマリーは敷地の下側に並べる
    xs = [p[0] for p in result.site.points]
    ys = [p[1] for p in result.site.points]
    text_x = min(xs)
    text_y = min(ys) - 2.0
    w.set_attributes(color=RESULT_COLOR_TEXT)
    for i, line in enumerate(result.summary_lines()):
        w.add_text((text_x, text_y - i * 1.2), line, height_m=0.8)

    w.save(path)


def run(temp_path: str, params_path: str) -> str:
    """外部変形の本処理。JWWに表示させたい要約文字列を返す。"""
    params = load_gaihen_params(params_path)
    site = site_from_jwc(temp_path, params)

    env = params.envelope
    result = compute_max_envelope(
        site,
        n_layers=env.n_layers,
        interval_m=env.interval_m,
        n_azimuth=env.n_azimuth,
        measurement_height=env.measurement_height,
        split_fractions=env.split_fractions,
        search_iterations=env.search_iterations,
        use_sky_ratio=env.use_sky_ratio,
        shadow_params=params.shadow,
    )
    write_result_jwc(result, temp_path, params)
    return (
        f"敷地{site.area_m2:.1f}m2 / 最高高さ{result.max_height_m:.2f}m / "
        f"体積{result.volume_m3:.1f}m3 / 延床(概算){result.total_floor_area_m2:.1f}m2"
    )


def diagnose(temp_path: str, units_per_meter: float = UNITS_PER_METER) -> str:
    """JWWが実際に渡してきたデータの中身を人が読める形で報告する。

    本パッケージのJWC書式の理解は実機JWWで検証できていないため、まずこれで
    「何が来ているか」を確認するのが最初の一歩になります。手順は
    docs/jww_integration.md を参照してください。
    """
    doc = read_jwc_file(temp_path, units_per_meter=units_per_meter)
    out: list[str] = [
        f"ファイル: {temp_path}",
        f"ヘッダ行(#で始まる行): {len(doc.header)}",
    ]
    out.extend(f"    {h}" for h in doc.header[:10])
    out.append(f"線分として読めた行: {len(doc.lines)}")

    if doc.lines:
        by_color = doc.lines_by_color()
        out.append(f"  線色の内訳: " + ", ".join(f"線色{c}={len(v)}本" for c, v in sorted(by_color.items())))
        xs = [v for s in doc.lines for v in (s.x1, s.x2)]
        ys = [v for s in doc.lines for v in (s.y1, s.y2)]
        out.append(
            f"  座標範囲(m換算): X {min(xs):.2f}〜{max(xs):.2f} / Y {min(ys):.2f}〜{max(ys):.2f}"
        )
        out.append(
            f"  → 敷地の実寸と合っていなければ units_per_meter の設定が違います"
            f"（現在: {units_per_meter}）"
        )
        try:
            ring = build_ring(doc.lines)
            out.append(f"  閉じた敷地形状として認識: {len(ring.points)}辺")
            out.append(f"    各辺の線色(順番に): {ring.colors}")
        except RingBuildError as exc:
            out.append(f"  閉じた敷地形状にできませんでした: {exc}")

    out.append(f"解釈できなかった行: {len(doc.unknown)}")
    out.extend(f"    {u}" for u in doc.unknown[:20])
    if len(doc.unknown) > 20:
        out.append(f"    ...他{len(doc.unknown) - 20}行")
    if doc.unknown:
        out.append(
            "  → 線分がここに入っている場合、本パッケージの書式の想定と実機が"
            "食い違っています。この出力を添えて報告してください。"
        )
    return "\n".join(out)


def _write_error_to_jwc(temp_path: str, message: str) -> None:
    """エラー時はJWWへ「何も作図しない」ファイルを返し、原因をメッセージで伝える。

    JWCの `h#` はJWW側にエラー表示させる指示（本実装の理解）。実機で効か
    ない場合でも、コメント行として原因が残るようにしています。
    """
    try:
        with open(temp_path, "w", encoding="shift_jis", errors="replace", newline="") as f:
            f.write(f"h#{message}\r\n")
            f.write(f"# jwcad-volume error: {message}\r\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jwcad-volume-gaihen",
        description="JWW外部変形として敷地図から最大ボリュームを計算します",
    )
    parser.add_argument("temp_file", nargs="?", default=DEFAULT_TEMP_NAME,
                        help="JWWが渡すデータファイル（既定: カレントのJWC_TEMP.TXT）")
    parser.add_argument("--params", help="設定YAML（既定: exeと同じ場所の gaihen_params.yaml）")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="計算せず、渡されたデータの中身を報告する（書式確認用）",
    )
    args = parser.parse_args(argv)

    temp_path = args.temp_file
    params_path = args.params or _default_params_path()

    if args.diagnose:
        units = UNITS_PER_METER
        if os.path.exists(params_path):
            try:
                units = load_gaihen_params(params_path).units_per_meter
            except (ValueError, KeyError, OSError):
                pass  # 設定が読めなくても診断自体は続ける
        try:
            print(diagnose(temp_path, units))
        except OSError as exc:
            print(f"エラー: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        summary = run(temp_path, params_path)
    except (RingBuildError, ValueError, KeyError, OSError) as exc:
        message = str(exc).replace("\n", " ")
        _write_error_to_jwc(temp_path, message)
        print(f"エラー: {message}", file=sys.stderr)
        return 1
    except Exception:  # 想定外の失敗でもJWWに壊れたデータを返さない
        detail = traceback.format_exc(limit=3).replace("\n", " ")
        _write_error_to_jwc(temp_path, "予期しないエラーが発生しました。詳細はコンソールを確認してください。")
        print(detail, file=sys.stderr)
        return 1

    print(summary)
    return 0


def _default_params_path() -> str:
    """exe化された場合はexeと同じフォルダ、通常実行ならカレントを見る。"""
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    return os.path.join(base, "gaihen_params.yaml")


if __name__ == "__main__":
    sys.exit(main())
