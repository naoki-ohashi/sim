# SiteInfo — 敷地情報取得エンジン

敷地の**位置・形状・行政情報**を集め、SIMワールド共通の**敷地情報GeoJSON**
（WGS84 / EPSG:4326）を書き出すツールです。HBU-ANALYZER v0.4の「STEP1」を
切り出した独立エンジンで、下流のエンジンはこのGeoJSONだけを受け取ります。

```
SiteInfo ──[敷地情報GeoJSON]──┬──▶ HBU-ANALYZER    用途と事業性の判定
                              ├──▶ BVCE-V01(TOKYO) 割増容積の算定
                              └──▶ MVE             建築ボリュームの検証
```

設計の全体像は [`docs/siteinfo/design_spec.md`](../docs/siteinfo/design_spec.md) を参照してください。

## 使い方

### ブラウザで開く（地図・描画・GeoJSON入出力・PLATEAU）

`index.html` をダブルクリックするだけです。ビルドは不要で、
HTML/CSS/vanilla JSの単一ファイルです。

この場合、**行政GIS（用途地域・地区計画・防火地域・高度地区・地価公示）だけが
使えません**。不動産情報ライブラリ（reinfolib）はCORS制限のためブラウザから
直接取得できないためです。用途地域などをSTEP2に手入力すればGeoJSONは作れます。

### Electronで開く（行政GISも使う）

```bash
cd siteinfo/electron
npm install
REINFOLIB_API_KEY=xxxxxxxx npm start     # Windowsは set REINFOLIB_API_KEY=...
```

`electron/` は最小限のホストです。画面が期待するAPIを3つ提供します。

| API | 役割 |
|---|---|
| `window.envAPI.get(name)` | reinfolib APIキーを環境変数から読む |
| `window.gisAPI.fetch(url, key)` | reinfolib APIをメインプロセス経由で取得する（要APIキー） |
| `window.netAPI.fetch(url)` | 地理院ジオコーダ・PLATEAUデータカタログのJSONを代行取得する（CORS回避） |

別の場所にある `index.html` を開くこともできます（旧版の検証などに）。

```bash
SITEINFO_HTML="D:\GD\[Claude]\siteinfo\index.html" npm start
npm start -- "D:\GD\[Claude]\siteinfo\index.html"
```

APIキーは[不動産情報ライブラリ](https://www.reinfolib.mlit.go.jp/)で取得します。
キーはSTEP2の入力欄に直接入れることもできます（保存はしません）。

## 操作の流れ

1. **STEP1 位置と形状** — 住所検索／地図に描画／地点情報モード／GeoJSON読み込みの
   4通り（併用可）で敷地を決めます。3点以上で「確定」すると面積が出ます。
   確定測量図の値は「手入力で上書き」に入れてください（`area_is_manual`に記録されます）。
2. **STEP2 敷地条件・行政情報** — 「行政GISから取得」で用途地域・容積率・建ぺい率・
   地区計画・防火地域・高度地区・地価公示を取得します。
   **道路幅員と日影規制は全国統一のAPIが無いため常に手入力**です。
3. **STEP3 書き出し** — 右カラムの「取得した敷地情報」が、そのまま書き出される内容です。

「PLATEAUで3D表示」は、国土交通省 Project PLATEAUの3D Tilesを表示します
（CesiumJSは初回クリック時に遅延ロード。APIキー・利用登録は不要）。

## 注意

- 都市計画情報は**参考値**です。正式な確認は自治体窓口で行ってください。
- 面積は地図上のポリゴンからの**概算**であり、測量に代わるものではありません。
- ローカルベンチマーク（`SHINJUKU_AREAS`）は新宿区内8エリアのみです。

## うまく動かないとき

### `Cannot read properties of undefined (reading 'fetch')`（用途地域・地区計画・防火・高度地区）

`window.gisAPI` が無い状態で行政GISを呼んでいます。**Electronホスト経由で
起動していない**（ブラウザで直接開いた、preloadが読まれていない、
`contextIsolation` の設定が食い違っている）のが原因です。

- このリポジトリ版は `window.gisAPI` の有無を先に確認し、
  「行政GISは利用できません（window.gisAPI が未定義）」と表示して止まります。
  上のエラーがそのまま出る場合は**別のビルドを起動しています**。
- 対処: `cd siteinfo/electron && REINFOLIB_API_KEY=… npm start` で起動する。
  旧版のHTMLを使いたい場合は `SITEINFO_HTML=…` で指定すれば、このホストの
  `window.gisAPI` がそのまま使えます。

### PLATEAU 3D表示が出ない

モーダル上部のステータス欄に、どの段階で失敗したかが出ます。

| 表示 | 原因と対処 |
|---|---|
| `CesiumJSを読み込めませんでした（…）` | CDNに到達できない。社内プロキシ・オフライン環境を確認する（cesium.com → unpkg → jsDelivr の順に試します） |
| `リバースジオコーダに接続できません（…）` | 地理院APIに届いていない。ブラウザで開いている場合はCORSの可能性があるためElectronで起動する |
| `データカタログAPIに接続できません（…）` | PLATEAU配信サービスに届いていない。同上 |
| `3D都市モデル未整備（市区町村コード …）` | その自治体のデータが無い。tileset.jsonのURLが分かればモーダル上部の欄に直接入力できる |
