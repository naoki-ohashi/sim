@echo off
chcp 932 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  MVCE - 最大ボリューム計算
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
    echo   2. インストーラの最初の画面で
    echo      「Add python.exe to PATH」に必ずチェックを入れてください
    echo   3. インストール後、このファイルをもう一度ダブルクリックしてください
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PY% --version 2^>^&1') do set PYVER=%%V
echo Python: !PYVER!
echo.

REM ---- 2. 必要なパッケージが入っているか確認 ------------------------
REM   "import mvce" だけだと、このフォルダに mvce\ があるせいで依存パッケージが
REM   未導入でも成功してしまう。shapely/numpy まで読む optimizer で確かめる。
%PY% -c "import mvce.optimizer" >nul 2>&1
if errorlevel 1 (
    echo 初回セットアップを行います。数分かかることがあります...
    echo.
    %PY% -m pip install --upgrade pip
    %PY% -m pip install -e .
    if errorlevel 1 (
        echo.
        echo [エラー] セットアップに失敗しました。
        echo 上に出ているメッセージを添えて報告してください。
        echo.
        pause
        exit /b 1
    )
    echo.
    echo セットアップが完了しました。
    echo.
)

REM ---- 3. 設定ファイルを決める --------------------------------------
REM     このバッチに .yaml をドラッグ＆ドロップすると、それを使います。
set CONFIG=%~1
if "%CONFIG%"=="" (
    if exist "自分の敷地.yaml" (
        set CONFIG=自分の敷地.yaml
    ) else (
        echo 「自分の敷地.yaml」が無いので、テンプレートから作ります。
        copy "examples\敷地入力テンプレート.yaml" "自分の敷地.yaml" >nul
        set CONFIG=自分の敷地.yaml
        echo.
        echo   「自分の敷地.yaml」を作りました。
        echo   メモ帳などで開いて、★ の付いた行を敷地の値に書き換えてから
        echo   もう一度このファイルをダブルクリックしてください。
        echo.
        echo   今回はテンプレートのままの値で計算します。
        echo.
    )
)

echo 設定ファイル: !CONFIG!
echo 計算中です。しばらくお待ちください...
echo.

REM ---- 4. 実行 ------------------------------------------------------
REM   コマンド名(mvce)ではなく python -m で呼ぶ。PATH の通り方に
REM   左右されず確実に動くため。
%PY% -m mvce.cli "!CONFIG!" %2 %3 %4 %5
if errorlevel 1 (
    echo.
    echo [エラー] 計算に失敗しました。上のメッセージを確認してください。
    echo 設定ファイルの書き方は examples\敷地入力テンプレート.yaml を参照。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  完了しました。
echo.
echo  結果_3d.html … ダブルクリックすると3Dで見られます
echo  結果.dxf      … JW-CADのDXF読込で開けます
echo ============================================================
echo.
pause
