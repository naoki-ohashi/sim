@echo off
chcp 932 >nul 2>&1
REM ===================================================================
REM  jwcad-volume : Windows用exeビルドスクリプト
REM
REM  Windows上で、Pythonがインストールされた状態で実行してください。
REM  出来上がったexeはPython無しのPCでも動きます。
REM
REM    実行方法: このファイルをダブルクリック、または
REM              コマンドプロンプトで  build_windows.bat
REM
REM  出来上がるもの (dist\jww\ フォルダ):
REM    jwcad_volume_gaihen.exe … JWW外部変形の本体
REM    jwcad-volume.exe         … 単体で使うコマンド版
REM    最大ボリューム計算.bat    … JWWの外部変形メニューに登録するバッチ
REM    診断_データ確認.bat       … 書式確認用（図面は変更しません）
REM    gaihen_params.yaml       … 用途地域や容積率などの設定ファイル
REM
REM  ※ このスクリプトはLinux環境で開発したため、Windows実機での
REM     ビルド検証はできていません。エラーが出た場合はメッセージを
REM     添えて報告してください。
REM ===================================================================
setlocal

echo [1/4] 依存パッケージとPyInstallerを導入します...
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pyinstaller
if errorlevel 1 goto :failed

echo.
echo [2/4] 外部変形本体をビルドします...
python -m PyInstaller --noconfirm ^
    --distpath dist\jww --workpath build\gaihen ^
    packaging\jwcad_volume_gaihen.spec
if errorlevel 1 goto :failed

echo.
echo [3/4] コマンド版をビルドします...
python -m PyInstaller --noconfirm ^
    --distpath dist\jww --workpath build\cli ^
    packaging\jwcad_volume_cli.spec
if errorlevel 1 goto :failed

echo.
echo [4/4] バッチと設定ファイルを配置します...
copy /Y "jww\最大ボリューム計算.bat" "dist\jww\" >nul
copy /Y "jww\診断_データ確認.bat" "dist\jww\" >nul
copy /Y "jww\gaihen_params.yaml" "dist\jww\" >nul
if errorlevel 1 goto :failed

echo.
echo ===================================================================
echo  ビルド完了: dist\jww\ フォルダをまるごと好きな場所に置いてください。
echo.
echo  次の手順:
echo    1. dist\jww\gaihen_params.yaml を敷地の条件に合わせて編集
echo    2. JWWで敷地の外形線を線色で描き分けて範囲選択
echo    3. [その他]-[外部変形] から 最大ボリューム計算.bat を選ぶ
echo.
echo  うまく動かない場合は、先に 診断_データ確認.bat を実行して
echo  診断結果.txt を確認してください。
echo ===================================================================
goto :end

:failed
echo.
echo *** ビルドに失敗しました。上のエラーメッセージを確認してください。 ***
exit /b 1

:end
endlocal
