"""MVE Web版UIのブラウザ実行テスト。

実際にChromiumで開いて、入力→計算→平面図/3D描画→書き出しまでを確認します。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist" / "MVE敷地入力.html"
CHROMIUM = "/opt/pw-browsers/chromium"

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None, reason="Playwright が無い環境ではスキップ")


@pytest.fixture(scope="module")
def built():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_mve_web.py")],
                   check=True, capture_output=True)
    assert DIST.exists()
    return DIST


@pytest.fixture(scope="module")
def page(built):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        launch = {"executable_path": CHROMIUM} if Path(CHROMIUM).exists() else {}
        browser = p.chromium.launch(**launch)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
        pg.goto(built.as_uri())
        _wait(pg)
        yield pg
        browser.close()


def _wait(pg, timeout=180000):
    pg.wait_for_function(
        "document.getElementById('status').textContent.indexOf('計算中') === -1", timeout=timeout)


def _pixels(pg, canvas_id):
    return pg.evaluate("""(id) => {
      const c = document.getElementById(id);
      if (!c.width || !c.height) return 0;
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) n++;
      return n;
    }""", canvas_id)


def test_single_file_has_no_external_references(built):
    html = built.read_text(encoding="utf-8")
    assert "<script src=" not in html
    assert "http://" not in html and "https://" not in html


def test_computes_and_draws_plan_on_load(page):
    assert not page.errors, page.errors
    assert "延床" in page.inner_text("#status")
    assert _pixels(page, "cplan") > 1000


def test_summary_is_japanese_and_complete(page):
    text = page.inner_text("#summary-body")
    for expected in ("敷地面積", "建築面積", "延床面積", "達成容積率", "上限に達した規制"):
        assert expected in text, expected


def test_edge_inputs_match_vertex_count(page):
    assert page.eval_on_selector_all("#edges .edge", "e => e.length") == 4
    page.select_option("#shape-mode", "poly")
    page.fill("#poly-points", "0,0\n40,0\n40,15\n20,25\n0,15")
    page.dispatch_event("#poly-points", "change")
    assert page.eval_on_selector_all("#edges .edge", "e => e.length") == 5
    page.select_option("#shape-mode", "rect")


def test_three_d_tab_renders(page):
    page.click(".tab[data-view=v3d]")
    page.wait_for_timeout(400)
    assert _pixels(page, "c3d") > 1000
    page.click(".tab[data-view=plan]")


def test_road_width_change_updates_far_note(page):
    """法52条2項で容積率が下がる場合、その場で注意書きが出る。"""
    note = page.inner_text("#far-note")
    assert "法52条2項" in note
    assert "6.0m" in note


def test_measurement_plane_choices_are_statutory(page):
    values = page.eval_on_selector_all("#mh option", "e => e.map(o => o.value)")
    assert values == ["1.5", "4", "6.5"]


def test_stricter_shadow_limits_reduce_floor_area(page):
    def floor_area():
        import re
        text = page.inner_text("#summary-body")
        return float(re.search(r"延床面積\(概算\): ([\d.]+)", text).group(1))

    page.fill("#h5", "5"); page.fill("#h10", "3")
    page.click("#run"); _wait(page)
    lenient = floor_area()

    page.fill("#h5", "2"); page.fill("#h10", "1")
    page.click("#run"); _wait(page)
    strict = floor_area()

    assert strict < lenient
    assert not page.errors, page.errors

    page.fill("#h5", "5"); page.fill("#h10", "3")
    page.click("#run"); _wait(page)


def test_shadow_can_be_switched_off(page):
    page.uncheck("#shadow-on")
    page.click("#run"); _wait(page)
    assert "測定線" not in page.inner_text("#summary-body")
    page.check("#shadow-on")
    page.click("#run"); _wait(page)
    assert "測定線" in page.inner_text("#summary-body")


def test_export_yaml_is_loadable_by_python(page, tmp_path):
    with page.expect_download() as dl:
        page.click("#export-yaml")
    path = tmp_path / "site.yaml"
    dl.value.save_as(str(path))

    sys.path.insert(0, str(ROOT))
    from mve.config import load_project

    project = load_project(str(path))
    assert project.site.area_m2 > 0
    assert project.shadow is not None
    assert project.site.edges[0].kind.value == "road"


def test_sky_ratio_can_be_enabled(page):
    """天空率チェックボックスON状態で3Dタブに切り替えてもJSエラーが出ないこと。"""
    page.check("#sky-on")
    page.click("#run"); _wait(page)
    assert not page.errors, page.errors
    text = page.inner_text("#summary-body")
    assert "天空率" in text

    page.click(".tab[data-view=v3d]")
    page.wait_for_timeout(400)
    assert _pixels(page, "c3d") > 1000
    assert not page.errors, page.errors
    page.click(".tab[data-view=plan]")

    with page.expect_download() as dl:
        page.click("#export-yaml")
    path = None
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/site_sky.yaml"
        dl.value.save_as(path)

        sys.path.insert(0, str(ROOT))
        from mve.config import load_project

        project = load_project(path)
        assert project.options.use_sky_ratio is True

    page.uncheck("#sky-on")
    page.click("#run"); _wait(page)
