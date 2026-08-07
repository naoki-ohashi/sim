"""Web版アプリのブラウザ実行テスト。

実際にChromiumで開いて、入力→計算→3D描画→書き出しまでが通ることを
確認します。Playwrightが無い環境ではスキップします。
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "jwcad-volume-web.html"

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None, reason="Playwright が無い環境ではスキップ"
)

CHROMIUM = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="module")
def built_app():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py")], check=True,
                   capture_output=True)
    assert DIST.exists()
    return DIST


@pytest.fixture(scope="module")
def page(built_app):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        launch = {"executable_path": CHROMIUM} if Path(CHROMIUM).exists() else {}
        browser = p.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": 1280, "height": 860}, accept_downloads=True)
        pg = context.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
        pg.goto(built_app.as_uri())
        _wait_done(pg)
        yield pg
        browser.close()


def _wait_done(pg, timeout=120000):
    pg.wait_for_function(
        "document.getElementById('status').textContent.indexOf('計算中') === -1", timeout=timeout)


def _drawn_pixels(pg):
    return pg.evaluate("""() => {
      const c = document.getElementById('c');
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) n++;
      return n;
    }""")


def test_single_file_build_has_no_external_references(built_app):
    html = built_app.read_text(encoding="utf-8")
    assert "<script src=" not in html
    assert "http://" not in html and "https://" not in html


def test_app_computes_and_draws_on_load(page):
    assert not page.errors, page.errors
    assert "体積" in page.inner_text("#status")
    assert _drawn_pixels(page) > 1000
    assert page.eval_on_selector_all("#summary-body div", "e => e.length") > 5


def test_summary_is_japanese(page):
    text = page.inner_text("#summary-body")
    assert "敷地面積" in text
    assert "最高高さ" in text


def test_recompute_reflects_changed_inputs(page):
    before = page.inner_text("#status")
    page.fill("#width", "45")
    page.click("#run")
    _wait_done(page)
    assert page.inner_text("#status") != before
    assert not page.errors, page.errors
    page.fill("#width", "30")
    page.click("#run")
    _wait_done(page)


def test_edge_kind_selectors_match_vertex_count(page):
    page.select_option("#shape-mode", "poly")
    page.fill("#poly-points", "0,0\n40,0\n40,15\n20,25\n0,15")
    page.dispatch_event("#poly-points", "change")
    assert page.eval_on_selector_all("#edge-kinds select", "e => e.length") == 5
    page.select_option("#shape-mode", "rect")


def test_export_yaml_is_loadable_by_python(page, tmp_path):
    with page.expect_download() as dl:
        page.click("#export-yaml")
    path = tmp_path / "site.yaml"
    dl.value.save_as(str(path))

    sys.path.insert(0, str(ROOT))
    from jwcad_volume.config import load_project

    project = load_project(str(path))
    assert project.site.area_m2 > 0
    assert project.envelope.max_stages >= 1


def test_export_3d_html_is_self_contained(page, tmp_path):
    with page.expect_download() as dl:
        page.click("#export-html")
    path = tmp_path / "envelope_3d.html"
    dl.value.save_as(str(path))

    html = path.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "http://" not in html and "https://" not in html
    match = re.search(r"JwcadVolumeViewer\.init\((\{.*\})\);", html)
    assert match, "3Dデータが埋め込まれていない"
    data = json.loads(match.group(1))
    assert data["site"] and data["baseline"]


def test_shadow_toggle_changes_result(page):
    page.check("#shadow-on")
    page.fill("#l1h", "1")
    page.fill("#l2h", "1")
    page.click("#run")
    _wait_done(page)
    strict = page.inner_text("#summary-body")
    assert "日影規制" in strict

    page.uncheck("#shadow-on")
    page.click("#run")
    _wait_done(page)
    assert "日影規制" not in page.inner_text("#summary-body")
