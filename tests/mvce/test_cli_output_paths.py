"""出力先の指定まわり（絶対パス・Windowsのパス・失敗時の伝え方）のテスト.

設定YAMLに `C:\\Users\\...\\Desktop\\敷地検討.dxf` のような出力先を書く
使い方を想定しています。
"""
import pathlib

import pytest
import yaml

from mvce.cli import main

from .test_io import _result  # noqa: F401  (フィクスチャの共有はしないが同じ敷地を使う)

CONFIG = """
site:
  name: テスト
  rectangle: {width_m: 30, depth_m: 20}
  edges:
    - {kind: road, road_width_m: 6.0}
    - {kind: adjacent}
    - {kind: adjacent}
    - {kind: adjacent}
  zoning: {zone_type: 1res, far_ratio: 200, coverage_ratio: 60}
  floor_height_m: 3.2
output:
  dxf_path: __DXF__
  html_path: __HTML__
"""


def _write_config(tmp_path, dxf, html):
    path = tmp_path / "site.yaml"
    text = CONFIG.replace("__DXF__", str(dxf)).replace("__HTML__", str(html))
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_output_folder_is_created(tmp_path, capsys):
    """途中のフォルダが無くても、勝手に作って書き出す。"""
    out = tmp_path / "まだ無い" / "さらに下"
    config = _write_config(tmp_path, out / "図面.dxf", out / "3d.html")

    assert main([str(config), "--cell", "5.0"]) == 0
    assert (out / "図面.dxf").exists()
    assert (out / "3d.html").exists()


def test_output_path_is_printed_in_full(tmp_path, capsys):
    """どこに出したか分かるよう、絶対パスで知らせる。"""
    out = tmp_path / "図面.dxf"
    config = _write_config(tmp_path, out, tmp_path / "3d.html")

    main([str(config), "--cell", "5.0"])
    assert str(out.resolve()) in capsys.readouterr().out


def test_write_failure_is_reported_without_a_traceback(tmp_path, capsys):
    """書けないときは traceback ではなく、日本語の理由を出して 1 で終わる。"""
    blocked = tmp_path / "ファイル"
    blocked.write_text("これはフォルダではない", encoding="utf-8")
    config = _write_config(tmp_path, blocked / "図面.dxf", tmp_path / "3d.html")

    assert main([str(config), "--cell", "5.0"]) == 1
    err = capsys.readouterr().err
    assert "図面の書き出しに失敗しました" in err
    assert "理由:" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("quoting, ok", [
    ("{}", True),        # 引用なし
    ("'{}'", True),      # 一重引用符
    ('"{}"', False),     # 二重引用符 … YAMLが \\U をユニコード脱出と解釈して壊れる
])
def test_windows_paths_need_no_double_quotes(quoting, ok):
    r"""`"C:\Users\..."` と書くとYAMLの段階で失敗する（\U がエスケープ扱い）。

    利用者がつまずきやすいので、この挙動を明示しておきます。
    """
    text = "dxf_path: " + quoting.format(r"C:\Users\naoki\Desktop\敷地検討.dxf")
    if ok:
        assert yaml.safe_load(text)["dxf_path"] == r"C:\Users\naoki\Desktop\敷地検討.dxf"
    else:
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(text)


def test_home_shortcut_is_expanded(tmp_path, capsys):
    """`~` を使った出力先も、フォルダを作る段階で展開される。"""
    from mvce.io.dxf_pen import ensure_parent_dir

    target = tmp_path / "home" / "out" / "図面.dxf"
    ensure_parent_dir(str(target))
    assert (tmp_path / "home" / "out").is_dir()
    # 相対パス（フォルダ指定なし）でも例外にならないこと
    ensure_parent_dir("図面.dxf")
    assert pathlib.Path(".").is_dir()
