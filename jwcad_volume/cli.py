"""jwcad-volume CLI: compute the max legal building volume from a YAML
project config and write a DXF (and optionally an experimental native JWW
外部変形 text file) for import into JW-CAD/JWW.

This is a standalone entry point today (phase 1: manual site-parameter
input, per docs/methodology.md). Wiring it up as a JWW 外部変形 registered
program is a separate integration step -- see docs/jww_integration.md.
"""
from __future__ import annotations

import argparse
import sys

from .config import load_project
from .envelope import compute_max_envelope
from .output.dxf_writer import write_envelope_dxf
from .output.gaihen_text import write_envelope_gaihen_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jwcad-volume", description=__doc__)
    parser.add_argument("config", help="path to a YAML project config (see examples/sample_site.yaml)")
    parser.add_argument("--dxf-out", help="override output.dxf_path from the config")
    parser.add_argument("--gaihen-text-out", help="override output.gaihen_text_path (experimental, see docs)")
    parser.add_argument("--no-sky-ratio", action="store_true", help="disable the 天空率 tower search")
    args = parser.parse_args(argv)

    project = load_project(args.config)
    env = project.envelope
    result = compute_max_envelope(
        project.site,
        n_layers=env.n_layers,
        interval_m=env.interval_m,
        n_azimuth=env.n_azimuth,
        measurement_height=env.measurement_height,
        split_fractions=env.split_fractions,
        search_iterations=env.search_iterations,
        use_sky_ratio=(env.use_sky_ratio and not args.no_sky_ratio),
        shadow_params=project.shadow,
    )

    for line in result.summary_lines():
        print(line)

    dxf_path = args.dxf_out or project.output.dxf_path
    if dxf_path:
        write_envelope_dxf(
            result, dxf_path,
            section_axis=project.output.section_axis,
            section_position=project.output.section_position,
        )
        print(f"wrote {dxf_path}")

    gaihen_path = args.gaihen_text_out or project.output.gaihen_text_path
    if gaihen_path:
        write_envelope_gaihen_text(result, gaihen_path)
        print(f"wrote {gaihen_path} (EXPERIMENTAL format, see docs/jww_integration.md)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
