"""プロファイルの読み込み（YAML / 組み込み）."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..sources import SourceRef
from .schema import ComplianceProfile

BUILTIN_DIR = Path(__file__).parent / "builtin"

_FIELDS = {
    "railway_is_adjacent_relaxation",
    "park_is_deemed_boundary",
    "apply_article_134_2",
    "ground_average_method",
    "sky_region_split_method",
    "sky_reference_layers",
    "sky_azimuth_count",
    "sky_measurement_interval_m",
}


def builtin_names() -> list[str]:
    return sorted(p.stem for p in BUILTIN_DIR.glob("*.yaml"))


def profile_from_dict(data: dict[str, Any]) -> ComplianceProfile:
    """プロファイルの辞書表現から作る。未知のキーは黙って捨てません。"""
    if not isinstance(data, dict):
        raise ValueError("プロファイルはマップで書いてください")
    unknown = set(data) - _FIELDS - {"name", "source", "notes"}
    if unknown:
        raise ValueError(
            f"プロファイルに未知のキーがあります: {sorted(unknown)}"
            f"（有効: {sorted(_FIELDS | {'name', 'source', 'notes'})}）"
        )
    if "name" not in data:
        raise ValueError("プロファイルには name が必要です")

    source = SourceRef.from_dict(data["source"]) if data.get("source") else None
    kwargs = {k: data[k] for k in _FIELDS if k in data}
    notes = tuple(data.get("notes", ()) or ())
    return ComplianceProfile(name=str(data["name"]), source=source, notes=notes, **kwargs)


def load_profile(name_or_path: str) -> ComplianceProfile:
    """組み込みの名前、または YAML ファイルのパスから読み込む。

    組み込みは `builtin/` の `*.yaml`。いまは条文だけの `statutory` のみです。
    """
    builtin = BUILTIN_DIR / f"{name_or_path}.yaml"
    path = builtin if builtin.exists() else Path(name_or_path)
    if not path.exists():
        raise FileNotFoundError(
            f"プロファイルが見つかりません: {name_or_path!r}"
            f"（組み込み: {builtin_names()}）"
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return profile_from_dict(data)
