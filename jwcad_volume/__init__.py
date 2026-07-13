"""jwcad_volume: legal max building volume calculator for JW-CAD gaihen-henkei.

Computes the maximum legally buildable building volume on a site under
Japan's Building Standards Act (建築基準法), combining:

- 道路斜線制限 (road slant-line restriction) + 天空率 (sky-ratio) alternative
- 隣地斜線制限 (adjacent-site slant-line restriction) + 天空率 alternative
- 北側斜線制限 (north-side slant-line restriction) + 天空率 alternative
- 日影規制 (sunlight/shadow regulation)

and produces plan/section drawing data for JW-CAD (DXF and gaihen-henkei
text exchange format).

This tool is a design-stage estimation aid. It is NOT a substitute for
review and certification by a licensed architect (建築士) or for the
certified software required for actual 天空率 building-permit submissions.
See docs/legal_basis.md and docs/disclaimer.md.
"""

__version__ = "0.1.0"
