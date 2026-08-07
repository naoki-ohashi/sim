# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: 単体コマンド版 (jwcad-volume.exe)

設定YAMLを読んで計算し、DXFと3DビューアHTMLを書き出すコマンド。
JWWが無くても使えます。ビルドは build_windows.bat から呼ばれます。
"""
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for package in ("shapely", "ezdxf", "yaml"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# 3Dビューアの描画コードは実行時に読み込むので同梱する
datas += [("../web/viewer.js", "web")]

a = Analysis(
    ["entry_cli.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="jwcad-volume",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
