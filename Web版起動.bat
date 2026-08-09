@echo off
chcp 932 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  MVE - Web版UI 起動
echo ============================================================
echo.

REM ---- 1. Python を探す --------------------------------------------
set PY=
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C --version >nul 2>&1
        if not errorlevel 1 set PY=%%~C
    )
)

if not defined PY (
    echo [エラー] Python が見つかりませんでした。
    echo.
    echo   1. https://www.python.org/downloads/ からダウンロードしてください
    echo   2. インストールの最初の画面で
    echo      「Add python.exe to PATH」に必ずチェックを入れてください
    echo   3. インストール後、このファイルをもう一度ダブルクリックしてください
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PY% --version 2^>^&1') do set PYVER=%%V
echo Python: !PYVER!
echo.

REM ---- 2. Web版UIを1つのHTMLにまとめる ------------------------------
echo Web版UIをビルドしています...
%PY% tools\build_mve_web.py
if errorlevel 1 (
    echo.
    echo [エラー] ビルドに失敗しました。上のメッセージを確認してください。
    echo.
    pause
    exit /b 1
)

echo.

REM ---- 3. できあがったHTMLをブラウザで開く --------------------------
set OUTHTML=dist\MVE敷地入力.html
if not exist "!OUTHTML!" (
    echo [エラー] !OUTHTML! が見つかりませんでした。
    echo.
    pause
    exit /b 1
)

echo ブラウザで開きます: !OUTHTML!
start "" "!OUTHTML!"

echo.
echo ============================================================
echo  起動しました。ブラウザのタブを確認してください。
echo  （このウィンドウは閉じてもかまいません）
echo ============================================================
echo.
pause
