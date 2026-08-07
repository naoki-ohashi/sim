import ezdxf
import pytest

from jwcad_volume.envelope import compute_max_envelope
from jwcad_volume.output.dxf_writer import write_envelope_dxf
from jwcad_volume.site import Boundary, Site
from jwcad_volume.zoning import ZoningParams

SQUARE = [(0, 0), (30, 0), (30, 30), (0, 30)]


def _site():
    zoning = ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6)
    edges = [
        Boundary((0, 0), (30, 0), kind="road", road_width_m=6.0),
        Boundary((30, 0), (30, 30), kind="adjacent"),
        Boundary((30, 30), (0, 30), kind="none"),
        Boundary((0, 30), (0, 0), kind="none"),
    ]
    return Site(points=SQUARE, edges=edges, zoning=zoning)


def test_write_envelope_dxf_roundtrip(tmp_path):
    site = _site()
    result = compute_max_envelope(
        site, n_layers=8, interval_m=10.0, n_azimuth=40, search_iterations=8, use_sky_ratio=False
    )
    out_path = tmp_path / "envelope.dxf"
    write_envelope_dxf(result, str(out_path))
    assert out_path.exists()

    doc = ezdxf.readfile(str(out_path))
    msp = doc.modelspace()
    plan_polylines = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "ENVELOPE-PLAN"]
    assert len(plan_polylines) == len(result.blocks)
    site_polylines = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "SITE"]
    assert len(site_polylines) == 1
    section_polylines = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "ENVELOPE-SECTION"]
    assert len(section_polylines) >= 1
    summary_texts = [e for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "SUMMARY"]
    assert len(summary_texts) > 0


def test_dxf_contains_isometric_on_its_own_layers(tmp_path):
    site = _site()
    result = compute_max_envelope(
        site, n_layers=6, interval_m=10.0, n_azimuth=30, search_iterations=6, use_sky_ratio=False
    )
    out_path = tmp_path / "envelope.dxf"
    write_envelope_dxf(result, str(out_path))

    msp = ezdxf.readfile(str(out_path)).modelspace()
    iso_layers = {e.dxf.layer for e in msp if e.dxftype() == "LINE" and e.dxf.layer.startswith("ISO-")}
    assert {"ISO-SITE", "ISO-OUTLINE", "ISO-VERTICAL"} <= iso_layers


def test_isometric_does_not_overlap_the_plan(tmp_path):
    site = _site()
    result = compute_max_envelope(
        site, n_layers=6, interval_m=10.0, n_azimuth=30, search_iterations=6, use_sky_ratio=False
    )
    out_path = tmp_path / "envelope.dxf"
    write_envelope_dxf(result, str(out_path))

    msp = ezdxf.readfile(str(out_path)).modelspace()
    plan_max_y = max(
        max(v[1] for v in e.get_points("xy"))
        for e in msp
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer in ("SITE", "ENVELOPE-PLAN")
    )
    iso_min_y = min(
        min(e.dxf.start.y, e.dxf.end.y)
        for e in msp
        if e.dxftype() == "LINE" and e.dxf.layer.startswith("ISO-")
    )
    assert iso_min_y > plan_max_y


def test_write_envelope_dxf_rejects_bad_axis(tmp_path):
    site = _site()
    result = compute_max_envelope(
        site, n_layers=4, interval_m=10.0, n_azimuth=30, search_iterations=4, use_sky_ratio=False
    )
    with pytest.raises(ValueError):
        write_envelope_dxf(result, str(tmp_path / "out.dxf"), section_axis="z")
