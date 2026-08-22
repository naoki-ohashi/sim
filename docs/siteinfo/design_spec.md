# SiteInfo 設計仕様書

**敷地情報取得エンジン（SiteInfo）**／`prototype v0.1`（2026-08時点）

正本は [`siteinfo/index.html`](../../siteinfo/index.html)（単一HTML・ビルド不要）。
HBU-ANALYZER v0.4の「STEP1」から分離して作成した独立エンジン。

| | |
|---|---|
| 対象 | `siteinfo/index.html`（HTML/CSS/vanilla JS） |
| 実行環境 | ブラウザ単体で動作。行政GISのみElectron想定（`window.envAPI` / `window.gisAPI`） |
| 出力 | 敷地情報**GeoJSON**（WGS84 / EPSG:4326） |
| 位置づけ | SIMワールドの**入口**。全エンジンの共通入力を作る |

---

## 1. 目的と分離の理由

### 解く問題

> ある土地について、**どこにあり・どんな形で・法的にどう規定されているか**を、
> 地図・行政GIS・手入力から集め、**1つのGeoJSONにまとめる。**

SIMワールドの各エンジン（HBU-ANALYZER・BVCE・MVE）はいずれも敷地情報を必要とするが、
その取得方法は共通である。ならば取得は1か所に集約し、以降のエンジンは
「もう分かっている敷地」を受け取って各々の分析に専念すればよい。

### HBU-ANALYZERから分離した理由

v0.4までこの機能はHBU-ANALYZERのSTEP1だった。切り出したのは次の3点による。

1. **下流が3つに増えた** — HBUだけでなくBVCE・MVEも同じ敷地情報を必要とする。
   HBUの中に取得機能があると、BVCEを使うためだけにHBUを開くことになる。
2. **依存の性質が違う** — 取得は地図タイル・行政API・3D配信という外部通信と
   ライブラリ（Leaflet・CesiumJS）に依存する。判定・算定は純粋な計算である。
   同居させると、計算部分まで外部要因で動かなくなる。
3. **更新の頻度が違う** — 行政APIの仕様変更やPLATEAUの配信変更は取得側の都合であり、
   収支モデルの見直しとは無関係に起きる。

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

- **事業性の判断** — 収支・利回りは扱わない（HBU-ANALYZERの領域）
- **建築ボリュームの検討** — 斜線・日影の計算はしない（MVEの領域）
- **都市計画情報の正式な証明** — 行政GISの値は参考値（8.1節）
- **測量に代わる面積の確定** — 面積は地図上のポリゴンからの概算（8.2節）

---

## 2. システム構成

```
<head>
  cdnjs (Leaflet CSS/JS)  … 地図
<body>
  #app（2カラム：左=入力、右=地図とサマリー）
    左: STEP1(位置と形状) / STEP2(敷地条件・行政情報) / STEP3(書き出し)
    右: 地図 / 取得した敷地情報
    PLATEAUモーダル（CesiumJSは初回クリック時に遅延ロード）
  <script>
    1. マスタデータ    ZONES, SHINJUKU_AREAS, SHADOW_OPTIONS, LAYERS
    2. 幾何            polygonAreaM2, ringContains, geometryContains, tileXY
    3-4. ヘルパと状態
    5. 地図            Leaflet + 切り替え可能な背景地図（BASEMAPS）
    6. STEP1           住所検索・描画・GeoJSON読み込み
    7. STEP2           行政GIS連携（reinfolib）
    8. STEP3           敷地情報GeoJSONの組み立てと書き出し
    9. PLATEAU         CesiumJS + 3D Tiles
```

### Electronホスト前提のAPI

行政GIS（不動産情報ライブラリ）はCORS制限のためブラウザから直接取得できない。
Electronのメインプロセス経由で取得する前提の関数に依存する。
**未定義でも例外は握りつぶし、機能を無効化した状態で動き続ける。**

| API | 役割 | 無い場合 |
|---|---|---|
| `window.envAPI.get(name)` | reinfolib APIキーを環境変数から読む | 例外を無視。キーは手入力欄から取る |
| `window.gisAPI.fetch(url, key)` | reinfolib APIをメインプロセス経由で取得 | 行政GIS機能が使えない。画面にその旨を明示表示 |

最小限のホスト実装を [`siteinfo/electron/`](../../siteinfo/electron) に置いてある。

**影響範囲**：地図タイル・住所検索・PLATEAUは素の `fetch` のため、Electron外の
ブラウザでも動作する。行政GISだけがElectron専用。取得できない場合もSTEP2を
手入力すればGeoJSONは作れる。Leaflet自体が読めない環境（オフライン等）でも、
地図以外（GeoJSON入出力・手入力・書き出し）は動き続ける。

---

## 3. STEP1：位置と形状

### 敷地の指定方法（4通り、併用可）

1. **住所・地番検索** — 国土地理院ジオコーディングAPI。ヒットを選ぶと地図が移動し、
   新宿区内なら該当エリアのベンチマークを反映する
2. **地図上に描画** — 「✏ 敷地を描く」で地図クリックにより頂点追加。3点以上で確定できる
3. **🔍 地点情報モード** — 任意の点をクリックすると、その地点の都市計画情報を
   ポップアップ表示する。描画モードとは排他
4. **GeoJSON読み込み** — 測量図由来のポリゴン等を取り込む。
   `Polygon` / `Feature` / `FeatureCollection` に対応

### 敷地面積の算定

```js
function polygonAreaM2(latlngs){
  // 平均緯度を基準にした局所平面近似 + 靴ひも公式(shoelace)
  R = 6378137;  lat0 = 頂点群の平均緯度;
  xy = 各点を [R・lng(rad)・cos(lat0), R・lat(rad)] に変換
  return |Σ(xy[i].x・xy[i+1].y − xy[i+1].x・xy[i].y)| / 2;
}
```

測地線に基づく厳密な面積ではなく、敷地スケールでは十分な精度の平面近似。
HBU-ANALYZER・BVCEにも**同一の式**があり、同じGeoJSONを別エンジンに読ませても
面積が食い違わない。「手入力で上書き」欄に値があればそちらが優先され、
その旨が `area_is_manual` としてGeoJSONにも記録される。

### ローカルベンチマーク `SHINJUKU_AREAS`

新宿区内8エリア（西新宿・新宿三丁目歌舞伎町周辺・高田馬場・大久保百人町・四谷・
神楽坂・市谷・落合中井）の**用途地域・道路幅員・地価**の参考値。住所文字列に
「新宿区」と各エリアの地名が含まれる場合にSTEP2へ反映し、一致したエリア名を
`area_name` としてGeoJSONに載せる。

賃料・ADRは市場条件でありSiteInfoの責務ではないため、HBU-ANALYZER側
（`AREA_RENT_BENCHMARKS`）に置く。両者は `area_name` という文字列1つで結ばれる。

---

## 4. STEP2：行政情報の取得

敷地の代表点を含むズームレベル14のタイル座標を求め、不動産情報ライブラリ
（reinfolib）の各レイヤーを取得する。

| レイヤーID | 内容 | 反映先 |
|---|---|---|
| `XKT002` | 用途地域（建ぺい率・容積率を含む） | 用途地域 / far / bcr |
| `XKT023` | 地区計画 | 地区計画 |
| `XKT014` | 防火・準防火地域 | 防火・準防火地域 |
| `XKT024` | 高度地区 | 高度地区 |
| `XPT002` | 地価公示（年次別） | 想定地価（坪単価換算） |

各レイヤーのGeoJSONから、対象地点を包含するフィーチャーを**点内多角形判定**
（レイキャスティング法。穴あきポリゴンは `Polygon` / `MultiPolygon` 双方に対応）で
1件特定する。地価公示は2025年から2022年へ遡って取得を試み、タイル内の全ポイントから
緯度経度の2乗距離が最小の点を採用する（円/m² → 万円/坪に換算）。

プロパティ名はAPIの表記ゆれに備え、候補キー→部分一致の順で探す（`pick()`）。

**エラーの扱い**：4レイヤー**すべて**が取得エラーだった場合（APIキー不正・
Electron外実行など）は、「データなし」と誤認させないよう明示的にエラーメッセージへ
切り替える。一部レイヤーだけ失敗した場合、そのレイヤーの欄は「指定なし」で
埋めずに空のまま残し、失敗した旨をステータスに出す。建ぺい率・容積率が行政データ側で
未提供の場合は、用途地域の目安値にフォールバックしたうえでその旨を表示する。

### 手入力に委ねる項目

**道路幅員と日影規制は全国統一のAPIが存在しない**（自治体条例に依存するため）。
この2項目は常に手入力とし、GISビューアへの参照リンクと当該地点の緯度経度を表示して
確認を促す。

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

- **座標はWGS84（EPSG:4326）、順序は `[経度, 緯度]`** — GeoJSON規約どおり。
  範囲外なら読み込み時に明示して中断する
- **属性は素のスカラー値** — 単位を名前に含める（`area_m2` / `road_width_m` /
  `land_price_man_per_tsubo`）ことで、受け取り側が単位を推測せずに済む
- **日影規制は値とラベルの両方** — `shadow_regulation`（機械可読）と
  `shadow_regulation_label`（人間可読）を併記する
- **出所を明記** — `source` / `gis_source` / `generated_at` により由来を辿れる
- **QGIS等でそのまま開ける** — 属性表として読める素直な構造
- 敷地形状が未確定でも、代表点があれば `Point` ジオメトリで書き出す

### 用途地域IDの対応

`zone_id` はSiteInfo（＝HBU・BVCE）側の表記。MVE（`mve/`・`web/mve/`）は別のIDを
使っているため、MVEへ渡す実装を書く際は次の対応で読み替える。

| `zone_id`（SiteInfo） | MVEの `zone` | 用途地域 |
|---|---|---|
| `dai1_teiso` | `1low` | 第一種低層住居専用地域 |
| `dai2_teiso` | `2low` | 第二種低層住居専用地域 |
| `denen` | `denen` | 田園住居地域 |
| `dai1_chuko` | `1mid` | 第一種中高層住居専用地域 |
| `dai2_chuko` | `2mid` | 第二種中高層住居専用地域 |
| `dai1_jukyo` | `1res` | 第一種住居地域 |
| `dai2_jukyo` | `2res` | 第二種住居地域 |
| `jun_jukyo` | `quasi_res` | 準住居地域 |
| `kinrin_shogyo` | `neighbor_commercial` | 近隣商業地域 |
| `shogyo` | `commercial` | 商業地域 |
| `jun_kogyo` | `quasi_industrial` | 準工業地域 |
| `kogyo` | `industrial` | 工業地域 |
| `kogyo_senyo` | `industrial_exclusive` | 工業専用地域 |
| `shitei_nashi` | `unspecified` | 指定なし |

### 書き出し前の内容確認

右カラムの「取得した敷地情報」に、**実際に書き出される内容**を表形式で常時表示する。
入力を変更するたびに再描画されるため、渡す前に何が下流へ流れるかを確認できる。

**受け取り側の寛容さ**：下流エンジンは属性が欠けていても動くよう作る。
HBU-ANALYZERは値が入っている属性だけを反映し（`setIfPresent`）、Polygonが無くても
`area_m2` があれば動く。SiteInfo自身も、書き出したGeoJSONを読み戻すときは
同じ方針で属性を反映する。

---

## 6. PLATEAU 3D表示

国土交通省 Project PLATEAU の3D Tiles配信サービスをCesiumJSでアプリ内に埋め込んで
表示する。Cesium ionのトークンを使わない構成のため、**APIキー・利用登録は不要**。

1. **CesiumJSの遅延ロード** — 初回の「PLATEAUで3D表示」クリック時にCDNから
   動的ロードする（起動時には読み込まない）
2. **市区町村コードの解決** — 敷地の緯度経度を国土地理院のリバースジオコーダ
   （`mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress`）に投げ、
   5桁の市区町村コードを得る
3. **tileset.json の特定** — データカタログAPIのJSONを**再帰的に走査**して
   tileset.jsonのURLを集め、市区町村コードを含む建築物モデル(bldg)を選ぶ。
   LOD2があればLOD2、なければLOD1
4. **表示** — 背景はPLATEAU配信のオルソ画像タイル。敷地ポリゴンを朱色の輪郭で重ね、
   俯角32度で敷地上空へカメラを寄せる

**カタログAPIのスキーマに依存しない設計**：配信サービスは実験的提供でレスポンス構造が
変わりうるため、特定のキー名を前提にせず「`http` で始まり `tileset.json` を含む文字列」を
再帰的に拾う方式にしている。該当データが無い市区町村では「3D都市モデル未整備」と
表示して静かに終わる。

---

## 7. 外部通信先の一覧

| 用途 | 接続先 | 認証 | Electron外 |
|---|---|---|---|
| 地図タイル | 国土地理院 XYZタイル（標準地図／淡色地図／航空写真） | 不要 | ✅ |
| 地図タイル（任意） | OpenStreetMap ／ OpenTopoMap | 不要 | ✅ |
| ジオコーディング | 国土地理院 住所検索API | 不要 | ✅ |
| リバースジオコーディング | 国土地理院 LonLatToAddress | 不要 | ✅ |
| 行政GIS（4層＋地価） | 不動産情報ライブラリ（reinfolib） | APIキー | ❌ |
| 3D都市モデル | Project PLATEAU 配信サービス | 不要 | ✅ |
| 地図・3Dライブラリ | cdnjs（Leaflet）／ Cesium公式CDN | 不要 | ✅ |

**Googleは使用しない**：地図・3D・口コミのいずれについてもGoogleのサービスは
使わない方針（SIMワールド共通）。地図の既定は国土地理院、3DはPLATEAUで揃えている。

**背景地図の切り替え**：地図右上のセレクタで背景地図を選べる。選択肢は
`index.html` の `BASEMAPS` 配列で定義しており、XYZタイル配信であれば1行足すだけで
増やせる。GeoJSON Player など他のビューアと同じ絵を並べて確認したい場合のために、
国土地理院タイルに加えてOSM系のタイルも既定で入れてある。選択内容は
`localStorage`（キー `siteinfo.basemap`）に保存され、次回起動時に復元される。

---

## 8. 制約と既知の限界

| | |
|---|---|
| 8.1 行政GISの値は参考値 | 不動産情報ライブラリの提供データに基づく。都市計画情報の正式な確認は自治体窓口で行う必要がある |
| 8.2 面積は測量ではない | 地図上のポリゴンからの概算。実務では確定測量図の値を手入力で上書きすること（`area_is_manual`に記録される） |
| 8.3 道路幅員・日影規制は手入力 | 全国統一APIが存在しない。道路台帳・自治体条例での確認が必要 |
| 8.4 ベンチマークは新宿区のみ | `SHINJUKU_AREAS`は新宿区内8エリアのみ。他エリアでは行政GISまたは手入力に頼る |
| 8.5 行政GISはElectron必須 | CORS制限のため`window.gisAPI`が要る。ブラウザ単体では地図・描画・GeoJSON入出力・PLATEAUのみ動く |
| 8.6 自動テストが存在しない | 回帰確認は手動のブラウザ操作に依存している |
| 8.7 MVEへの直結は未実装 | MVEの取り込み口は `{ points, edges }`（メートル座標）であり、敷地情報GeoJSONをそのままは読めない。現状は手作業での受け渡しになる |

## 9. 今後の課題

1. **ベンチマークの拡張** — 品川区をはじめ新宿区以外のエリアへ順次拡大する
2. **複数敷地の管理** — 現状は1敷地ずつ。案件単位で複数敷地を保持・比較できるようにする
3. **MVEとの接続** — 敷地情報GeoJSONを平面直角座標へ投影し、MVEの `{ points, edges }` へ
   変換する橋渡しを用意する（8.7）
4. **道路幅員の半自動取得** — 自治体の道路台帳GISが公開されている地域では、
   リンクだけでなく取得も試みる
5. **PLATEAU属性の活用** — 3D表示だけでなく、周辺建物の高さ・用途をシグナルとして取り出す
6. **自動テストの整備** — GeoJSON入出力と行政GISのパース処理に対する回帰テスト
