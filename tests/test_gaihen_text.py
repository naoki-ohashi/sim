from jwcad_volume.envelope import compute_max_envelope
from jwcad_volume.output.gaihen_text import write_envelope_gaihen_text
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (30, 0), (30, 30), (0, 30)]


def _site():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    edges = [Boundary(SQUARE[i], SQUARE[(i + 1) % 4], kind="none") for i in range(4)]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_write_envelope_gaihen_text_smoke(tmp_path):
    # This only checks the file gets written in the intended shape (one "L,"
    # line per polygon) -- it is NOT a check that JW-CAD can actually read
    # it; see the module docstring for why that's still unverified.
    site = _site()
    result = compute_max_envelope(
        site, n_layers=5, interval_m=10.0, n_azimuth=20, search_iterations=4, use_sky_ratio=False
    )
    out_path = tmp_path / "envelope.txt"
    write_envelope_gaihen_text(result, str(out_path))
    assert out_path.exists()
    lines = out_path.read_text(encoding="shift_jis").splitlines()
    assert len(lines) == 1 + len(result.blocks)
    assert all(line.startswith("L,") for line in lines)
