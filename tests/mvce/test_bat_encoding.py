"""バッチファイルの文字コードを固定する（再発防止）。

日本語版 Windows の cmd.exe は、バッチファイルを OEM コードページ（CP932）
として読みます。UTF-8 で保存されたバッチは日本語が文字化けし、`echo` の
メッセージが読めなくなるほか、日本語を含むパスやラベルを使っている行では
実行そのものが失敗します。

改行も CRLF でなければなりません。LF だけの行は、行末に余分な文字が付いた
ものとして解釈されることがあります。

`test_jww_dxf_compat.py` が DXF の書式を固定しているのと同じ趣旨で、
配布するバッチの書式をここで固定します。
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BAT_FILES = sorted(REPO_ROOT.glob("**/*.bat"))


def test_repository_has_bat_files():
    """glob が壊れて0件になったまま緑になるのを防ぐ。"""
    assert BAT_FILES, "リポジトリに .bat が見つかりません"


@pytest.mark.parametrize("path", BAT_FILES, ids=lambda p: p.name)
def test_bat_is_cp932(path):
    raw = path.read_bytes()
    try:
        raw.decode("cp932")
    except UnicodeDecodeError as exc:
        raise AssertionError(
            f"{path.name} が CP932 で読めません（UTF-8 で保存されている可能性）。"
            f" 日本語版 Windows の cmd.exe は CP932 として読むため文字化けします: {exc}"
        ) from None


@pytest.mark.parametrize("path", BAT_FILES, ids=lambda p: p.name)
def test_bat_is_not_utf8_when_it_has_japanese(path):
    """日本語を含むバッチが UTF-8 のまま入るのを防ぐ。

    CP932 と UTF-8 の両方で読めてしまうのは ASCII だけのファイルで、
    その場合は文字化けしないので対象外にする。
    """
    raw = path.read_bytes()
    if raw.decode("cp932").isascii():
        return
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")


@pytest.mark.parametrize("path", BAT_FILES, ids=lambda p: p.name)
def test_bat_uses_crlf(path):
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name} に BOM が付いています"
    lone_lf = raw.count(b"\n") - raw.count(b"\r\n")
    assert lone_lf == 0, f"{path.name} に LF だけの改行が {lone_lf} 行あります"
