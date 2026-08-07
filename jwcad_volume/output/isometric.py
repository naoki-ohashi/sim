"""アイソメ図（軸測投影）を2Dの線分として生成する.

JWWは2D CADなので本物の3D表示はできませんが、3D形状を平行投影して
2Dの線分に落とせば、図面の中に立体的な見え方を描き込めます。回転は
できない代わりに、新しいソフトを一切必要とせず、そのまま印刷・
図面化できるのが利点です。

生成した線分は `output/dxf_writer.py`（DXF）と `gaihen.py`（JWW外部変形）
の両方から使えます。

なお、隠線消去は行っていません（ワイヤーフレーム）。ボリューム検討の
段階では各段の輪郭が見えている方がむしろ形状を読み取りやすいためです。
"""
from __future__ import annotations

from ..envelope import EnvelopeResult
from ..mesh import Axonometric, Point2, blocks_to_edges, site_edges

# 線種の区別（JWWの線色/DXFのレイヤ割り当てに使う）
KIND_SITE = "site"          # 敷地境界（地盤面）
KIND_OUTLINE = "outline"    # 各段の輪郭
KIND_VERTICAL = "vertical"  # 垂直稜線

Segment = tuple[Point2, Point2, str]


def isometric_segments(
    result: EnvelopeResult,
    azimuth_deg: float = 225.0,
    elevation_deg: float = 30.0,
    origin: Point2 | None = None,
    include_baseline: bool = False,
) -> list[Segment]:
    """計算結果をアイソメ投影し、2D線分のリストで返す。

    `origin` を与えると、図の左下がその座標に来るように平行移動します
    （平面図と重ならない位置に置くため）。`include_baseline` を真に
    すると、斜線制限のみのエンベロープも重ねて描きます。
    """
    axo = Axonometric(azimuth_deg=azimuth_deg, elevation_deg=elevation_deg)

    edges = list(site_edges(list(result.site.points)))
    edges += blocks_to_edges(result.blocks)
    if include_baseline:
        edges += blocks_to_edges(result.baseline_blocks)

    segments: list[Segment] = [
        (axo.project(e.p1), axo.project(e.p2), e.kind) for e in edges
    ]
    if not segments:
        return []

    if origin is not None:
        xs = [c for s in segments for c in (s[0][0], s[1][0])]
        ys = [c for s in segments for c in (s[0][1], s[1][1])]
        dx = origin[0] - min(xs)
        dy = origin[1] - min(ys)
        segments = [
            ((p1[0] + dx, p1[1] + dy), (p2[0] + dx, p2[1] + dy), kind) for p1, p2, kind in segments
        ]
    return segments


def default_origin(result: EnvelopeResult, gap_ratio: float = 0.25) -> Point2:
    """平面図の右隣にアイソメ図を置くための基準点。"""
    xs = [p[0] for p in result.site.points]
    ys = [p[1] for p in result.site.points]
    width = max(xs) - min(xs)
    return (max(xs) + max(width * gap_ratio, 3.0), min(ys))
