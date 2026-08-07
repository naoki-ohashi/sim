REM #jww
REM #cd
REM #e
REM ===================================================================
REM  jwcad-volume : 書式確認用の診断バッチ（図面は一切変更しません）
REM
REM  JWWが外部変形に渡してくるデータの実物を採取して、本ツールが正しく
REM  読めているかを確認するためのものです。
REM
REM  使い方:
REM    1. 敷地の外形線を範囲選択する
REM    2. [その他]-[外部変形] からこのバッチを選ぶ
REM    3. このフォルダに次の2つが作られます
REM         JWC_SAMPLE.TXT … JWWが渡してきた生データ
REM         診断結果.txt    … 本ツールがそれをどう読んだかの報告
REM    4. 「解釈できなかった行」に線分が入っていたら、書式の想定が
REM       実機と違っています。2つのファイルを添えて報告してください。
REM ===================================================================
copy /Y "%1" "%~dp0JWC_SAMPLE.TXT" >nul 2>&1
if not exist "%~dp0JWC_SAMPLE.TXT" copy /Y JWC_TEMP.TXT "%~dp0JWC_SAMPLE.TXT" >nul 2>&1
"%~dp0jwcad_volume_gaihen.exe" "%~dp0JWC_SAMPLE.TXT" --diagnose > "%~dp0診断結果.txt" 2>&1

REM 図面に何も追加しないよう、返すデータはコメント1行だけにする
echo # jwcad-volume diagnostic (no drawing output) > "%1"
