# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: JWW外部変形の本体 (jwcad_volume_gaihen.exe)

ビルドは build_windows.bat から呼ばれます。単体で実行する場合:
    pyinstaller packaging\\jwcad_volume_gaihen.spec

shapely は GEOS のネイティブDLLを同梱する必要があり、PyInstallerの
自動検出だけでは取りこぼすことがあるため collect_all で明示しています。
"""
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for package in ("shapely", "ezdxf", "yaml"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["entry_gaihen.py"],
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
    name="jwcad_volume_gaihen",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # JWWから呼ばれたときにエラーメッセージが見えるようコンソールを残す
    console=True,
    disable_windowed_traceback=False,
)
