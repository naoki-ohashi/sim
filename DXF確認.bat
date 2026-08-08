@echo off
chcp 932 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  DXF確認 - JW-CADで読める形式かどうか調べます
echo ============================================================
echo.

if "%~1"=="" (
    echo 調べたいDXFファイルを、このバッチファイルに
    echo ドラッグ＆ドロップしてください。
    echo.
    echo   例: 結果.dxf をマウスでつまんで、
    echo       DXF確認.bat の上で離す
    echo.
    pause
    exit /b 1
)

REM ---- Python を探す --------------------------------------------
set PY=
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C --version >nul 2>&1
        if not errorlevel 1 set PY=%%~C
    )
)

if not defined PY (
    echo [エラー] Python が見つかりませんでした。
    echo MVE実行.bat と同じ手順でPythonを入れてください。
    echo.
    pause
    exit /b 1
)

REM ---- 実行（複数ファイルをまとめて渡せる）----------------------
%PY% tools\check_dxf.py %*

echo.
pause
