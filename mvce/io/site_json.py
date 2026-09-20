"""JSONから敷地図を読み込む.

HBU-ANALYZER等の外部ツールが出力するポリゴンデータを想定しています。
YAML設定の `site.points`/`site.edges` とほぼ同じ形をJSONで表したものです。

    {
      "points": [[0, 0], [30, 0], [30, 20], [0, 20]],
      "edges": [
        {"kind": "road", "road_width_m": 6.0, "wall_setback_m": 1.5},
        {"kind": "adjacent"},
        {"kind": "adjacent", "relaxation": {"kind": "water", "width_m": 4.0}},
        {"kind": "adjacent"}
      ],
      "units_per_meter": 1.0
    }

`edges` は省略できます。省略した場合はすべての辺が「対象外」になるので、
YAML側の `site.edges` で指定してください（DXF読み込みのレイヤ名推測が
無い場合と同じ扱いです）。
"""
from __future__ import annotations

import json

from ..geometry import Point
from .dxf_site import ImportedEdge, ImportedSitePlan, SiteImportError

_VALID_KINDS = ("road", "adjacent", "none")


def read_site_plan_json(path: str, units_per_meter: float = 1.0) -> ImportedSitePlan:
    """JSONから敷地の外形を読み取る。

    JSON内に `units_per_meter` があればそちらを優先します（無ければ引数の値）。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        raise SiteImportError(f"JSONを読み込めませんでした: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SiteImportError(
            f"JSONの形式が正しくありません（{path}、{exc.lineno}行目付近）: {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise SiteImportError(
            "JSONのトップレベルはオブジェクト（{ \"points\": [...] } の形）である必要があります"
        )

    scale = 1.0 / float(data.get("units_per_meter", units_per_meter))

    raw_points = data.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 3:
        got = len(raw_points) if isinstance(raw_points, list) else "points キー自体が無い"
        raise SiteImportError(f"points には3点以上の座標配列が必要です（現在: {got}）")

    points: list[Point] = []
    for i, p in enumerate(raw_points):
        if not (isinstance(p, (list, tuple)) and len(p) == 2
                and all(isinstance(v, (int, float)) for v in p)):
            raise SiteImportError(f"points[{i}] は [x, y] の形式である必要があります: {p!r}")
        points.append((float(p[0]) * scale, float(p[1]) * scale))

    n = len(points)
    notes: list[str] = []
    raw_edges = data.get("edges")

    if raw_edges is None:
        edges = [ImportedEdge(p1=points[i], p2=points[(i + 1) % n]) for i in range(n)]
        notes.append(
            "JSONにedgesが無いため、辺の種別はすべて「対象外」としました。"
            "YAML側の site.edges で指定してください。"
        )
        return ImportedSitePlan(points=points, edges=edges, notes=notes)

    if not isinstance(raw_edges, list) or len(raw_edges) != n:
        got = len(raw_edges) if isinstance(raw_edges, list) else "配列ではない"
        raise SiteImportError(f"edges の数({got})が points の数({n})と一致しません")

    edges = []
    for i, e in enumerate(raw_edges):
        if not isinstance(e, dict):
            raise SiteImportError(f"edges[{i}] はオブジェクトである必要があります: {e!r}")
        kind = e.get("kind", "none")
        if kind not in _VALID_KINDS:
            raise SiteImportError(
                f"edges[{i}].kind は road/adjacent/none のいずれかにしてください: {kind!r}"
            )
        road_width_m = e.get("road_width_m")
        if kind == "road" and (road_width_m is None or float(road_width_m) <= 0):
            raise SiteImportError(
                f"edges[{i}] は道路境界線（kind: road）ですが、"
                "road_width_m が指定されていないか0以下です"
            )
        relaxation = e.get("relaxation")
        if relaxation is not None and not isinstance(relaxation, dict):
            raise SiteImportError(f"edges[{i}].relaxation はオブジェクトである必要があります: {relaxation!r}")
        edges.append(ImportedEdge(
            p1=points[i], p2=points[(i + 1) % n],
            kind_hint=kind,
            road_width_m=float(road_width_m) if road_width_m is not None else None,
            wall_setback_m=(
                float(e["wall_setback_m"]) if e.get("wall_setback_m") is not None else None
            ),
            relaxation=relaxation,
            ground_level_diff_m=(
                float(e["ground_level_diff_m"])
                if e.get("ground_level_diff_m") is not None else None
            ),
            label=str(e.get("label", "")),
        ))

    return ImportedSitePlan(points=points, edges=edges, notes=notes)
