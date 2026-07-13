"""EXPERIMENTAL, UNVERIFIED adapter for JW-CAD/JWW's native 外部変形 data
exchange text format.

JWW's [その他]-[外部変形] menu launches a registered external program and
passes it the path of a temporary text file containing the current
selection (or whole drawing), in JWW's own line-based text encoding; the
external program is expected to overwrite that file with replacement/new
entity data in the same encoding, which JWW then re-reads back into the
drawing. This module writes lines in that general shape (one line per
geometry element, layer/pen/entity-type-coded fields, coordinates in the
drawing's own units) based on the format as documented in JWW's own help
text, but this project has had no way to test it against an actual JW-CAD
installation.

**Do not trust this module's output to be byte-correct.** Treat it as a
starting point to adjust once you can test against your own JWW version --
compare against a file JWW itself writes when invoking a trivial existing
外部変形 program, and adjust `_format_line` accordingly. For guaranteed
results, use output.dxf_writer and JWW's DXF import instead; see
docs/jww_integration.md.
"""
from __future__ import annotations

from ..envelope import EnvelopeResult

# Layer group/number is a guess: JWW files commonly separate a 2-digit layer
# group (0-9) and 2-digit layer (00-15); using group 0 for the site outline
# and successive layers for each envelope step is a reasonable placeholder.
SITE_LAYER = "0,0"
PLAN_LAYER_BASE = 1  # envelope layer i uses group 0, layer (PLAN_LAYER_BASE + i) mod 16


def _format_line_entity(layer: str, pen: int, points: list[tuple[float, float]]) -> str:
    coords = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
    return f"L,{layer},{pen} {coords}"


def write_envelope_gaihen_text(result: EnvelopeResult, path: str) -> None:
    lines: list[str] = []
    site_ring = list(result.site.points) + [result.site.points[0]]
    lines.append(_format_line_entity(SITE_LAYER, 1, site_ring))

    for i, block in enumerate(result.blocks):
        layer = f"0,{(PLAN_LAYER_BASE + i) % 16}"
        ring = list(block.footprint.exterior.coords)
        lines.append(_format_line_entity(layer, 2, ring))

    with open(path, "w", encoding="shift_jis", errors="replace") as f:
        f.write("\n".join(lines) + "\n")
