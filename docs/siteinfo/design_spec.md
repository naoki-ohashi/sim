# SiteInfo 設計仕様書

**敷地情報取得エンジン（SiteInfo）**／`prototype v0.1`

正本は [`siteinfo/index.html`](../../siteinfo/index.html)（単一HTML・ビルド不要）。
HBU-ANALYZER v0.4の「STEP1」から分離した独立エンジンで、`SIM_engines/siteinfo` で
運用していた実装をこのリポジトリに取り込んだもの。

| | |
|---|---|
| 対象 | `siteinfo/index.html`（HTML/CSS/vanilla JS・約1,100行） |
| 実行環境 | ブラウザで動作。行政GISのみElectron必須（`window.gisAPI`） |
| 出力 | 敷地情報**GeoJSON**（WGS84 / EPSG:4326） |
| 位置づけ | SIMワールドの**入口**。全エンジンの共通入力を作る |

---

## 1. 目的と分離の理由

### 解く問題

> ある土地について、**どこにあり・どんな形で・法的にどう規定されているか**を、
> 地図・行政GIS・手入力から集め、**1つのGeoJSONにまとめる。**

### HBU-ANALYZERから分離した理由

1. **下流が3つに増えた** — HBUだけでなくBVCE・MVEも同じ敷地情報を必要とする
2. **依存の性質が違う** — 取得は地図タイル・行政API・3D配信という外部通信と
   ライブラリ（Leaflet・CesiumJS）に依存する。判定・算定は純粋な計算である
3. **更新の頻度が違う** — 行政APIやPLATEAU配信の変更は取得側の都合であり、
   収支モデルの見直しとは無関係に起きる

### エンジン構成

| エンジン | 責務 | 問い |
|---|---|---|
| SiteInfo（本書） | 敷地の位置・形状・行政情報の取得 | この土地は何か |
| HBU-ANALYZER | 用途別の収支比較と有効利用の判定 | この土地をどう使うか |
| BVCE-V01(TOKYO) | 都市開発諸制度による割増容積の算定 | 容積をどこまで積めるか |
| MVE | 斜線・日影・天空率をふまえた最大ボリューム | 実際に何が建つか |

```
SiteInfo ──[敷地情報GeoJSON]──┬──▶ HBU-ANALYZER    用途と事業性の判定
                              ├──▶ BVCE-V01(TOKYO) 割増容積の算定
                              └──▶ MVE             建築ボリュームの検証
```

### 非目標

- **事業性の判断**（HBU-ANALYZERの領域）／**建築ボリュームの検討**（MVEの領域）
- **都市計画情報の正式な証明** — 行政GISの値は参考値（8章）
- **測量に代わる面積の確定** — 面積は地図上のポリゴンからの概算（8章）

---

## 2. システム構成

Electronのメインプロセス経由で外部APIを取得するための関数に依存する。
**未定義でも例外は握りつぶし、機能を無効化した状態で動き続ける。**

| API | 役割 | 無い場合 |
|---|---|---|
| `window.envAPI.get()` / `get("REINFOLIB_API_KEY")` | reinfolib APIキーを環境変数から読む | 無視。キーは手入力欄から取る |
| `window.gisAPI.fetch(url, key)` | reinfolib APIを取得（要APIキー） | **行政GISは使えない。**「window.gisAPI が未定義」と明示表示して中断する |
| `window.netAPI.fetch(url)` | 地理院ジオコーダ・PLATEAUデータカタログのJSONを取得 | 素の `fetch` にフォールバック（CORSや`file://`のOrigin: nullで失敗しうる） |

`envAPI.get()` はホストによって `{reinfolibApiKey}` を返す実装と、
引数名を取って文字列を返す実装があるため、両方に対応している。
`gisAPI.fetch()` の戻り値も、文字列／`{ok,status,body}`／GeoJSONそのものの
いずれでも解釈する（`parseGisResponse`）。

最小限のホスト実装を [`siteinfo/electron/`](../../siteinfo/electron) に置いてある。

---

## 3. STEP1：位置と形状

### 敷地の指定方法（4通り、併用可）

1. **住所検索** — 国土地理院ジオコーディングAPI。新宿区内ならローカル
   ベンチマークをSTEP2へ反映する
2. **地図上に描画** — クリックで頂点追加。3点以上で確定
3. **地点情報モード** — 任意の点をクリックすると、その地点の都市計画情報を
   ポップアップ表示する
4. **GeoJSON読み込み** — Polygonの外周リングを取り込む（**形状のみ**。属性は
   STEP2へ反映されない → 9章）

### 敷地面積の算定

```js
function polygonAreaM2(latlngs){
  // 平均緯度を基準にした局所平面近似 + 靴ひも公式(shoelace)
  R = 6378137;  lat0 = 頂点群の平均緯度;
  xy = 各点を [R・lng(rad)・cos(lat0), R・lat(rad)] に変換
  return |Σ(xy[i].x・xy[i+1].y − xy[i+1].x・xy[i].y)| / 2;
}
```

測地線に基づく厳密な面積ではないが、敷地スケールでは十分な精度の平面近似。
HBU-ANALYZER・BVCEにも同一の式があり、同じGeoJSONで面積が食い違わない。
「面積の手入力」欄（`areaOverride`）に正の値があればそちらが優先され、
その旨が `area_is_manual` としてGeoJSONに記録される。

### ローカルベンチマーク `SHINJUKU_AREAS`

新宿区内8エリア（西新宿／新宿三丁目・歌舞伎町周辺／高田馬場／大久保・百人町／
四谷／神楽坂／市谷／落合・中井）の**用途地域・道路幅員・地価**の参考値。
住所文字列に「新宿区」と各エリアの地名が含まれる場合にSTEP2へ反映し、
一致したエリア名を `area_name` としてGeoJSONに載せる。
賃料・ADRは市場条件でありSiteInfoの責務ではないため、HBU-ANALYZER側が
`area_name` で引く。

---

## 4. STEP2：行政情報の取得

敷地の代表点を含むズームレベル14のタイル座標を求め、不動産情報ライブラリ
（reinfolib）の各レイヤーを取得する。

| レイヤーID | 内容 | 読むプロパティ |
|---|---|---|
| `XKT002` | 用途地域 | `use_area_ja` / `u_building_coverage_ratio_ja` / `u_floor_area_ratio_ja` |
| `XKT023` | 地区計画 | `plan_name` → `plan_type_ja` |
| `XKT014` | 防火・準防火地域 | `plan_type_ja` |
| `XKT024` | 高度地区 | `plan_name` → `plan_type_ja` |
| `XPT002` | 地価公示（年次別） | `u_current_years_price_ja`（円/m² → 万円/坪に換算） |

対象地点を包含するフィーチャーを**点内多角形判定**（レイキャスティング法。
穴あきポリゴンは `Polygon` / `MultiPolygon` 双方に対応）で1件特定する。
地価公示は2025年から2022年へ遡り、タイル内で緯度経度の2乗距離が最小の点を採用する。

### エラーの扱い

- `window.gisAPI` が無い場合は**呼ぶ前に**中断し、Electronで起動する必要がある旨を表示する
- 4レイヤー**すべて**が失敗した場合は「データなし」と誤認させないよう中断し、
  各レイヤーの失敗理由を並べて表示する
- 一部レイヤーだけ失敗した場合、そのレイヤーの欄は「指定なし」で**埋めず**、
  失敗した旨をステータスに出す（未取得と指定なしは別物）
- 建ぺい率・容積率が未提供の場合は用途地域の目安値にフォールバックし、その旨を表示する

### 手入力に委ねる項目

**道路幅員と日影規制は全国統一のAPIが存在しない**（自治体条例に依存するため）。
この2項目は常に手入力とし、GISビューアへの参照リンクと緯度経度を表示して確認を促す。

---

## 5. STEP3：敷地情報GeoJSON

本エンジンの成果物。SIMワールド各エンジンの**共通入力フォーマット**であり、
実質的にエンジン間の契約にあたる。

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "properties": {
      "name": "西新宿 A敷地", "address": "…", "area_name": "西新宿",
      "area_m2": 990, "area_tsubo": 299.5, "area_is_manual": false,
      "zone": "商業地域", "zone_id": "shogyo",
      "far_percent": 600, "bcr_percent": 80,
      "road_width_m": 20, "walk_min": 3,
      "land_price_man_per_tsubo": 480,
      "district_plan": "西新宿地区計画",
      "fire_zone": "防火地域", "height_zone": "指定なし",
      "shadow_regulation": "none", "shadow_regulation_label": "規制なし",
      "source": "SiteInfo", "source_version": "0.1",
      "gis_source": "国土交通省 不動産情報ライブラリ(reinfolib)",
      "generated_at": "2026-08-13T…Z"
    },
    "geometry": { "type": "Polygon", "coordinates": [[[lng,lat], …]] }
  }]
}
```

### 設計上の約束

- **座標はWGS84（EPSG:4326）、順序は `[経度, 緯度]`**、リングは閉じる。
  読み込み時に範囲外なら明示して中断する
- **属性は素のスカラー値**。単位を名前に含める（`area_m2` / `road_width_m` /
  `land_price_man_per_tsubo`）
- **日影規制は値とラベルの両方**（`shadow_regulation` は
  `none` / `t1` / `t2` / `t3` / `check`、`shadow_regulation_label` は表示文言）
- **出所を明記**（`source` / `source_version` / `gis_source` / `generated_at`）
- geometryは**Polygonのみ**。書き出しには3頂点以上が必要

### 用途地域IDの対応

`zone_id` はSiteInfo（＝HBU・BVCE）側の表記。MVE（`mve/`・`web/mve/`）は別のIDを
使うため、MVEへ渡す実装を書く際は次の対応で読み替える。

| `zone_id`（SiteInfo） | MVEの `zone` | 用途地域 |
|---|---|---|
| `ichi_tei` | `1low` | 第一種低層住居専用地域 |
| `ni_tei` | `2low` | 第二種低層住居専用地域 |
| `den_en` | `denen` | 田園住居地域 |
| `ichi_chu` | `1mid` | 第一種中高層住居専用地域 |
| `ni_chu` | `2mid` | 第二種中高層住居専用地域 |
| `ichi_ju` | `1res` | 第一種住居地域 |
| `ni_ju` | `2res` | 第二種住居地域 |
| `jun_ju` | `quasi_res` | 準住居地域 |
| `kinsho` | `neighbor_commercial` | 近隣商業地域 |
| `shogyo` | `commercial` | 商業地域 |
| `junko` | `quasi_industrial` | 準工業地域 |
| `kogyo` | `industrial` | 工業地域 |
| `kosen` | `industrial_exclusive` | 工業専用地域 |

### 書き出し前の内容確認

画面右の「取得した敷地情報」に、**実際に書き出される内容**を表形式で常時表示する。
入力を変更するたびに再描画されるため、渡す前に何が下流へ流れるかを確認できる。

**受け取り側の寛容さ**：下流エンジンは属性が欠けていても動くよう作る。
HBU-ANALYZERは値が入っている属性だけを反映する。

---

## 6. PLATEAU 3D表示

国土交通省 Project PLATEAU の3D Tiles配信サービスをCesiumJSで埋め込んで表示する。
Cesium ionのトークンを使わない構成のため、**APIキー・利用登録は不要**。

1. **CesiumJSの遅延ロード** — 初回クリック時にCDNから動的ロードする。CDNは1つに
   賭けず cesium.com → unpkg → jsDelivr の順に試す
2. **市区町村コードの解決** — 緯度経度を国土地理院のリバースジオコーダ
   （`mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress`）に投げ、5桁コードを得る
3. **tileset.json の特定** — データカタログAPIのJSONを**再帰的に走査**して
   tileset.jsonのURLを集め、市区町村コードを含む建築物モデル(bldg)を選ぶ。
   LOD2があればLOD2、なければLOD1。エンドポイント自体も変わりうるため候補を順に試す
4. **表示** — 背景はPLATEAU配信のオルソ画像タイル。敷地ポリゴンを朱色で重ね、
   俯角32度で敷地上空へカメラを寄せる

**失敗の切り分け**：CesiumJS読み込み／リバースジオコーダ／データカタログ／未整備を
区別してモーダル上部に表示する。カタログに全く接続できない場合は「未整備」ではなく
接続失敗として出す。tileset.jsonのURLが分かっている場合は、モーダル上部の欄に
直接入力して表示できる。

**カタログAPIのスキーマに依存しない設計**：実験的提供でレスポンス構造が変わりうるため、
特定のキー名を前提にせず「`http` で始まり `tileset.json` を含む文字列」を再帰的に拾う。

---

## 7. 外部通信先の一覧

| 用途 | 接続先 | 認証 | Electron外 |
|---|---|---|---|
| 地図タイル | 国土地理院 XYZタイル | 不要 | ✅ |
| ジオコーディング | 国土地理院 住所検索API | 不要 | ✅ |
| リバースジオコーディング | 国土地理院 LonLatToAddress | 不要 | ⚠ CORSで弾かれうる |
| 行政GIS（4層＋地価） | 不動産情報ライブラリ（reinfolib） | APIキー | ❌ |
| 3D都市モデル・オルソ | Project PLATEAU 配信サービス | 不要 | ⚠ 同上 |
| 地図・3Dライブラリ | cdnjs（Leaflet）／ Cesium公式CDN・unpkg・jsDelivr | 不要 | ✅ |
| Webフォント | Google Fonts | 不要 | ✅ |

⚠ の2つは、Electronで起動すれば `window.netAPI` 経由になり回避できる。

**地図・3DにGoogleのサービスは使わない**（SIMワールド共通）。地図は国土地理院、
3DはPLATEAUで揃えている。

---

## 8. 制約と既知の限界

| | |
|---|---|
| 8.1 行政GISの値は参考値 | 正式な確認は自治体窓口で行う必要がある |
| 8.2 面積は測量ではない | 地図上のポリゴンからの概算。実務では確定測量図の値を手入力で上書きする |
| 8.3 道路幅員・日影規制は手入力 | 全国統一APIが存在しない |
| 8.4 ベンチマークは新宿区のみ | `SHINJUKU_AREAS`は新宿区内8エリアのみ |
| 8.5 行政GISはElectron必須 | CORS制限のため`window.gisAPI`が要る |
| 8.6 地図はLeafletのCDNに依存 | cdnjsに到達できない環境では地図機能が動かない |
| 8.7 GeoJSONの読み込みは形状のみ | 属性はSTEP2へ反映されない |
| 8.8 `gis_source` は固定文字列 | 行政GISを使っていなくても同じ値が入る |
| 8.9 自動テストが存在しない | 回帰確認は手動のブラウザ操作に依存している |
| 8.10 MVEへの直結は未実装 | MVEの取り込み口は `{ points, edges }`（メートル座標）であり、敷地情報GeoJSONをそのままは読めない |

## 9. 今後の課題

1. **ベンチマークの拡張** — 品川区をはじめ新宿区以外のエリアへ順次拡大する
2. **複数敷地の管理** — 案件単位で複数敷地を保持・比較できるようにする
3. **敷地情報の再読み込み** — 書き出したGeoJSONの属性をSTEP2へ復元する（8.7）
4. **MVEとの接続** — GeoJSONを平面直角座標へ投影し `{ points, edges }` へ変換する（8.10）
5. **道路幅員の半自動取得** — 自治体の道路台帳GISが公開されている地域では取得も試みる
6. **PLATEAU属性の活用** — 周辺建物の高さ・用途をシグナルとして取り出す
7. **自動テストの整備** — GeoJSON入出力と行政GISのパース処理に対する回帰テスト
