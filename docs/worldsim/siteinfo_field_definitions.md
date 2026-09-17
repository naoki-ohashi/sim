# SiteInfo 項目定義書 v0.2（草案）

> WorldSim の出発点となる **敷地情報（SiteInfo）** の入力項目を定義します。
> 前提は [`vision.md`](vision.md)（考え方）と
> [`siteinfo_requirements.md`](siteinfo_requirements.md)（入力要件）です。
> DB 設計は [`siteinfo_db_design.md`](siteinfo_db_design.md)、DDL は
> [`../../db/siteinfo/schema.sql`](../../db/siteinfo/schema.sql) を参照。
>
> 出典: SiteInfo v0.1（`siteinfo/index.html`、`sample_site.geojson`）の項目、
> 条文アーカイブ README の「SITEINFO とは（2026-08-30）」、
> 宅建業法 35 条 重要事項説明書の「法令に基づく制限」区分。

## 0. 定義書の読み方

### 0.1 SiteInfo の責務

SiteInfo は **敷地情報を入力するデータベースのカード** です。判定ロジックは
持ちません（用途の可否判定や割増容積の算定は HBU-ANALYZER、BVCE、MVE の
仕事）。SiteInfo が正しく埋まっていれば、下流エンジンは同じ敷地条件で動きます。

### 0.2 列の意味

| 列 | 意味 |
|---|---|
| キー | DB・GeoJSON・画面で共通に使う識別子（snake_case） |
| 項目名 | 画面に表示する日本語名 |
| 型 | `text` / `int` / `num`（小数） / `bool` / `enum` / `date` / `geom` / `json` |
| 単位 | m、㎡、% など |
| 必須 | ◎ 必須（未入力では SiteInfo を確定できない）／○ 推奨／△ 任意 |
| 自動 | 自動入力の候補があるか。◎ 取得元が確立／○ 取得元はあるが自治体差あり／× 手入力のみ |
| 取得元候補 | 自動入力に使えるデータソース |
| 根拠 | 関連する法令・様式 |

### 0.3 全項目に共通する付随情報（メタ属性）

**すべての項目**が、値に加えて次のメタ属性を持ちます（要件ノート 3 節）。
自動入力は補助であり、**必須項目は入力ユーザーの最終確認を経るまで未確定**です。

| メタ属性 | 内容 |
|---|---|
| `source_kind` | `auto`（GIS 等から自動）／`manual`（手入力）／`derived`（他項目から計算） |
| `source_name` | 取得元の名称（例: 国土交通省 不動産情報ライブラリ） |
| `source_dataset` | データセット名・レイヤ名・API 名 |
| `source_fetched_at` | 取得日時 |
| `confirm_status` | `unconfirmed`（未確認）／`confirmed`（確認済み）／`rejected`（自動値を却下し手入力で置換） |
| `confirmed_by` / `confirmed_at` | 最終確認したユーザーと日時 |
| `note` | 自治体の提示方法の違い、判断理由などのメモ |

### 0.4 自動入力の取得元（候補）

| 略称 | 取得元 | 用途 |
|---|---|---|
| GSI 住所検索 | 国土地理院 住所検索 API（`msearch.gsi.go.jp`） | 住所 → 座標 |
| GSI 逆ジオコーダ | 国土地理院 逆ジオコーダ（`mreversegeocoder.gsi.go.jp`） | 座標 → 住所・市区町村コード |
| reinfolib | 国土交通省 不動産情報ライブラリ API | 用途地域、容積率、建蔽率、防火地域、高度地区、地区計画、地価、駅 |
| 都市計画 GIS | 各自治体の都市計画情報 GIS（形式は自治体ごとに異なる） | 用途地域、日影規制、高度地区、地区計画、都市計画道路 |
| ハザード | 国土交通省 ハザードマップポータル（重ねるハザードマップ） | 洪水、土砂災害、津波、高潮 |
| PLATEAU | 3D 都市モデル（`api.plateauview.mlit.go.jp`） | 周辺建物、地形、3D 表示 |
| 登記 | 登記情報（登記事項証明書、公図、地積測量図） | 地番、地積、所有者（手入力） |

---

## 1. 識別・所在（A）

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `site_id` | 敷地 ID | text | | ◎ | — | システム採番（UUID） | |
| `site_name` | 敷地名 | text | | ○ | × | | 検討案件名など任意の呼び名 |
| `address` | 所在（住居表示） | text | | ◎ | ◎ | GSI 逆ジオコーダ | 重要事項説明書「所在」 |
| `lot_numbers` | 地番（複数可） | json | | ◎ | × | 登記 | 筆ごとの地番・地目・地積の配列 |
| `municipality_code` | 市区町村コード | text | | ◎ | ◎ | GSI 逆ジオコーダ | JIS X 0402。GIS 取得元の切替キー |
| `prefecture` / `city` | 都道府県・市区町村 | text | | ◎ | ◎ | 同上 | |
| `owner_summary` | 所有者・権利関係の概要 | text | | △ | × | 登記 | 個人情報を含むため保存範囲は別途規定 |
| `status` | 確定状態 | enum | | ◎ | — | | `draft` / `confirmed` / `archived` |

## 2. 位置・形状（B）

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `geom` | 敷地ポリゴン | geom | 経緯度 | ◎ | ○ | 地図上作図／GeoJSON 取込／公図 | JGD2011（EPSG:6668）。MultiPolygon 可 |
| `shape_source` | 形状の由来 | enum | | ◎ | — | | `survey_triangles`（三斜）／`polygon`（地図作図）／`coordinates`（座標）／`geojson`／`dxf`／`cadastral`（公図） |
| `plane_srid` | 平面直角座標系 | int | | ◎ | ◎ | 位置から自動判定 | EPSG:6669〜6687（系 I〜XIX）。MVE・面積計算に使用 |
| `centroid` | 代表点 | geom | 経緯度 | ◎ | ◎ | `geom` から算出 | 派生値 |
| `elevation_m` | 標高 | num | m | △ | ◎ | GSI 標高 API | |
| `north_angle_deg` | 真北方位角 | num | 度 | ◎ | ◎ | 座標から算出（真北）／磁北は非採用 | MVE `north_angle_deg`。図面上方向から反時計回り |
| `survey_drawing_ref` | 測量図・公図の参照 | text | | ○ | × | 添付ファイル | 三斜求積表・座標一覧の原本 |

## 3. 面積（C）

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `area_registered_m2` | 公簿面積 | num | ㎡ | ○ | × | 登記 | 地積の合計 |
| `area_measured_m2` | 実測面積 | num | ㎡ | ○ | × | 測量図 | |
| `area_geom_m2` | 図形面積 | num | ㎡ | ◎ | ◎ | `geom` から算出 | 派生値。平面直角座標で計算 |
| `area_effective_m2` | 採用面積 | num | ㎡ | ◎ | ○ | 上記のいずれかを選択 | 下流エンジンが使う面積。SiteInfo v0.1 `area_m2` |
| `area_basis` | 採用面積の根拠 | enum | | ◎ | — | | `registered` / `measured` / `geom` / `manual` |
| `area_tsubo` | 採用面積（坪） | num | 坪 | — | ◎ | 換算 | 派生値（÷3.30579） |
| `setback_area_m2` | セットバック等で除外する面積 | num | ㎡ | ○ | ○ | 道路種別から算出 | 法 42 条 2 項道路のみなし境界、都市計画道路 |

## 4. 境界・道路（D）

敷地の各辺を 1 レコードとして持ちます（MVE の `edges` と同じ構造）。

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `edge_seq` | 辺番号 | int | | ◎ | ◎ | `geom` の頂点順 | 反時計回り |
| `edge_kind` | 境界種別 | enum | | ◎ | ○ | 道路 GIS・道路台帳 | `road` / `adjacent` / `none` |
| `road_width_m` | 前面道路幅員 | num | m | ◎（道路辺） | ○ | reinfolib、道路台帳 | 法 52 条 2 項（容積率の道路幅員制限）、道路斜線 |
| `road_type` | 道路種別 | enum | | ◎（道路辺） | ○ | 指定道路図（自治体） | 法 42 条 1 項 1〜5 号、2 項、3 項、法 43 条ただし書 |
| `road_setback_m` | セットバック距離 | num | m | ○ | ○ | 道路種別から算出 | 2 項道路の中心線後退 |
| `is_private_road` | 私道か | bool | | ◎（道路辺） | × | | 重要事項説明書「私道に関する負担」 |
| `private_road_burden` | 私道負担の内容 | text | | ○ | × | | 面積・持分 |
| `wall_setback_m` | 壁面後退距離 | num | m | ○ | ○ | 地区計画・条例 | MVE `wall_setback_m` |
| `relaxation_kind` | 緩和対象（辺の外側） | enum | | ○ | ○ | 都市計画 GIS | `none` / `park` / `water` / `railway`（令 134 条、135 条の 3、135 条の 4、135 条の 12） |
| `relaxation_width_m` | 緩和対象の幅 | num | m | ○ | ○ | 同上 | |
| `frontage_m` | 接道長さ | num | m | ◎ | ◎ | `geom` から算出 | 法 43 条（2m 以上） |
| `corner_lot` | 角地 | bool | | ○ | ◎ | 道路辺が 2 辺以上 | 建蔽率の角地緩和（自治体の指定基準による） |

## 5. 都市計画法（E）

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `area_division` | 区域区分 | enum | | ◎ | ○ | 都市計画 GIS | `urbanization_promotion`（市街化区域）／`urbanization_control`（市街化調整区域）／`undivided`（非線引き）／`outside`（都市計画区域外）／`quasi_city_planning`（準都市計画区域） |
| `zone_type` | 用途地域 | enum | | ◎ | ◎ | reinfolib、都市計画 GIS | 法 48 条・別表第二。MVE `zone_type`（`1res` 〜 `industrial_exclusive` の 13 区分＋無指定） |
| `zone_type_secondary` | 用途地域（2 以上にわたる場合） | json | | ○ | ○ | 同上 | 面積按分のための区分と面積 |
| `far_percent` | 指定容積率 | int | % | ◎ | ◎ | reinfolib | 法 52 条 1 項 |
| `bcr_percent` | 指定建蔽率 | int | % | ◎ | ◎ | reinfolib | 法 53 条 1 項 |
| `bcr_bonus_corner` | 角地加算の適用 | bool | | ○ | × | 自治体の指定基準 | 法 53 条 3 項 2 号 |
| `bcr_bonus_fireproof` | 防火地域内耐火建築物等の加算 | bool | | ○ | ○ | 防火地域から判断 | 法 53 条 3 項 1 号 |
| `fire_zone` | 防火・準防火地域 | enum | | ◎ | ◎ | reinfolib | `fire` / `quasi_fire` / `none`／法 22 条区域は `article22` |
| `height_district` | 高度地区 | text | | ◎ | ◎ | reinfolib、都市計画 GIS | 種別名（例: 第 2 種高度地区）と最高限度・最低限度 |
| `height_district_max_m` | 高度地区の最高限度 | num | m | ○ | ○ | 同上 | 斜線型は別途パラメータ |
| `special_use_district` | 特別用途地区 | text | | ○ | ○ | 都市計画 GIS | |
| `high_use_district` | 高度利用地区 | bool | | ○ | ○ | 都市計画 GIS | |
| `district_plan` | 地区計画 | text | | ◎ | ◎ | reinfolib | 名称。`none` なら「指定なし」 |
| `district_plan_rules` | 地区計画の制限内容 | json | | ○ | × | 自治体の地区整備計画 | 壁面位置、高さ、用途、最低敷地面積など |
| `scenic_district` | 風致地区・景観地区 | text | | ○ | ○ | 都市計画 GIS | |
| `planned_road` | 都市計画道路（計画線） | json | | ◎ | ○ | 都市計画 GIS | 名称・幅員・事業決定の有無・敷地への掛かり |
| `redevelopment_project` | 市街地再開発事業・区画整理事業 | text | | ○ | ○ | 都市計画 GIS | |
| `development_permit_required` | 開発許可の要否 | enum | | ○ | × | | `required` / `not_required` / `unknown`（法 29 条） |
| `min_lot_area_m2` | 敷地面積の最低限度 | num | ㎡ | ○ | ○ | 都市計画 GIS | 法 53 条の 2 |

## 6. 建築基準法の形態規制（F）

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `absolute_height_limit_m` | 絶対高さ制限 | num | m | ○ | ○ | 用途地域から | 法 55 条（10m／12m） |
| `road_slant_applies` | 道路斜線の適用 | bool | | ◎ | ◎ | 用途地域から | 法 56 条 1 項 1 号 |
| `adjacent_slant_applies` | 隣地斜線の適用 | bool | | ◎ | ◎ | 同上 | 法 56 条 1 項 2 号 |
| `north_slant_applies` | 北側斜線の適用 | bool | | ◎ | ◎ | 同上 | 法 56 条 1 項 3 号 |
| `sky_ratio_allowed` | 天空率の適用可否 | bool | | ○ | ◎ | | 法 56 条 7 項 |
| `exterior_wall_setback_m` | 外壁後退距離 | num | m | ○ | ○ | 都市計画 GIS | 法 54 条 |
| `wall_line` | 壁面線の指定 | text | | ○ | ○ | 自治体 | 法 46 条 |
| `building_agreement` | 建築協定 | text | | ○ | × | 自治体 | 法 69 条 |
| `local_ordinances` | 条例による制限 | json | | ○ | × | 自治体 | 緑化、駐車場附置義務、ワンルーム条例、中高層条例など |

## 7. 日影規制（G）

要件ノート 2 節。自治体条例で指定される組み合わせを **そのまま入力** します。

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `shadow_applies` | 日影規制の有無 | enum | | ◎ | ○ | 都市計画 GIS | `regulated` / `none` / `unknown`（要確認）。商業・工業・工専は対象外 |
| `shadow_measurement_height_m` | 測定面の高さ | enum | m | ◎（規制あり） | ○ | 同上 | `1.5` / `4.0` / `6.5`（別表第四） |
| `shadow_hours_5m` | 5m 超 10m 以内の規制時間 | num | 時間 | ◎（規制あり） | ○ | 同上 | 例 3 / 4 / 5。自由入力可 |
| `shadow_hours_10m` | 10m 超の規制時間 | num | 時間 | ◎（規制あり） | ○ | 同上 | 例 2 / 2.5 / 3。自由入力可 |
| `shadow_preset` | 組み合わせプリセット | enum | | — | — | | `3h_2h` / `4h_2.5h` / `5h_3h` / `custom`。選ぶと上 2 項目を埋める |
| `shadow_target_criteria` | 対象建築物の基準 | enum | | ◎（規制あり） | ◎ | 用途地域から | `eaves7m_or_3f`（軒高 7m 超または 3 階以上）／`height10m`（高さ 10m 超） |
| `shadow_hokkaido` | 北海道区分 | bool | | ◎ | ◎ | 都道府県から | 真太陽時 9〜15 時 |
| `shadow_ordinance_ref` | 条例の根拠 | text | | ○ | × | | 条例名・条項 |

MVE の `shadow` 設定へは `measurement_height_m` ← `shadow_measurement_height_m`、
`line_5m_max_hours` ← `shadow_hours_5m`、`line_10m_max_hours` ← `shadow_hours_10m`、
`hokkaido` ← `shadow_hokkaido` としてそのまま渡します。

## 8. その他の法令上の制限（H）— 重要事項説明書の区分

宅建業法 35 条 1 項 2 号の「法令に基づく制限」を、**法令ごとに 1 レコード**で
持ちます。各レコードは共通の 4 列を持ちます。

| キー | 項目名 | 型 | 必須 | 備考 |
|---|---|---|---|---|
| `law_code` | 法令コード | enum | ◎ | 下表のコード |
| `applies` | 該当の有無 | enum | ◎ | `yes` / `no` / `unknown`。**`unknown` のままでは確定不可** |
| `detail` | 制限の内容 | text | ○（該当時） | 区域名、指定内容、制限の概要 |
| `reference` | 根拠資料 | text | ○ | 図面名・告示番号・窓口名など |

### 8.1 法令コード一覧（初期セット）

| `law_code` | 法令 | 主な区域・制限 | 自動 | 取得元候補 |
|---|---|---|---|---|
| `national_land_use` | 国土利用計画法 | 届出の要否（規制区域・監視区域） | ○ | 自治体 |
| `agricultural_land` | 農地法 | 農地転用許可 | ○ | 農地台帳 |
| `landslide_fill` | 宅地造成及び特定盛土等規制法 | 宅地造成等工事規制区域、特定盛土等規制区域、造成宅地防災区域 | ○ | 自治体 GIS |
| `sediment_disaster` | 土砂災害防止法 | 警戒区域（イエロー）、特別警戒区域（レッド） | ◎ | ハザード |
| `steep_slope` | 急傾斜地法 | 急傾斜地崩壊危険区域 | ○ | 都道府県 GIS |
| `tsunami` | 津波防災地域づくり法 | 津波災害警戒区域・特別警戒区域 | ◎ | ハザード |
| `flood_hazard` | 水防法（水害ハザードマップ） | 浸水想定区域と想定浸水深 | ◎ | ハザード |
| `river` | 河川法 | 河川区域、河川保全区域 | ○ | 都道府県 GIS |
| `port_coast` | 港湾法・海岸法 | 臨港地区、海岸保全区域 | ○ | 自治体 |
| `landscape` | 景観法 | 景観計画区域、届出の要否 | ○ | 自治体 |
| `cultural_property` | 文化財保護法 | 周知の埋蔵文化財包蔵地 | ○ | 自治体 GIS |
| `natural_park` | 自然公園法 | 特別地域・普通地域 | ○ | 環境省 GIS |
| `urban_green` | 都市緑地法 | 特別緑地保全地区、緑化地域 | ○ | 都市計画 GIS |
| `productive_green` | 生産緑地法 | 生産緑地地区 | ○ | 都市計画 GIS |
| `soil_contamination` | 土壌汚染対策法 | 要措置区域、形質変更時要届出区域 | ○ | 都道府県 |
| `large_retail` | 大規模小売店舗立地法 | 届出の要否 | × | |
| `parking_ordinance` | 駐車場法・附置義務条例 | 附置義務の有無 | × | |
| `airport_height` | 航空法 | 高さ制限（制限表面） | ○ | 空港周辺 GIS |
| `radio_propagation` | 電波法 | 伝搬障害防止区域 | ○ | 総務省 |
| `other` | その他 | 自由記述 | × | |

コード一覧は DB の `legal_restriction_catalog` テーブルで管理し、追加は
データで行います（コード変更のたびにスキーマを変えない）。

## 9. 供給施設・その他（I）

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 根拠・備考 |
|---|---|---|---|---|---|---|---|
| `water_supply` | 上水道 | enum | | ◎ | × | 水道局 | `front_road` / `on_site` / `none`。管径・私設管 |
| `sewerage` | 下水道 | enum | | ◎ | × | 下水道台帳 | `public` / `septic` / `none`。処理区域内外 |
| `gas` | ガス | enum | | ◎ | × | ガス会社 | `city_gas` / `lp` / `none` |
| `electricity` | 電気 | text | | ○ | × | 電力会社 | 引込の状況 |
| `utility_notes` | 供給施設の備考 | text | | △ | × | | 引込負担金など |
| `asbestos_survey` | 石綿使用調査の記録 | enum | | ○ | × | | 既存建物がある場合 |
| `seismic_diagnosis` | 耐震診断の記録 | enum | | ○ | × | | 既存建物がある場合 |
| `existing_building` | 既存建物の概要 | json | | ○ | × | 登記 | 構造・階数・延床・築年 |

## 10. 市場・立地（J）

SiteInfo v0.1 が保持していた項目。判定には使わず、下流の HBU・収支に渡します。

| キー | 項目名 | 型 | 単位 | 必須 | 自動 | 取得元候補 | 備考 |
|---|---|---|---|---|---|---|---|
| `nearest_station` | 最寄駅 | text | | ○ | ◎ | reinfolib、駅データ | |
| `walk_min` | 最寄駅からの徒歩 | int | 分 | ○ | ◎ | 経路計算（80m/分） | SiteInfo v0.1 `walk_min` |
| `land_price_man_per_tsubo` | 想定地価 | num | 万円/坪 | ○ | ○ | 地価公示・取引価格（reinfolib） | SiteInfo v0.1 |
| `official_land_price` | 公示地価・基準地価 | json | 円/㎡ | ○ | ◎ | reinfolib | 地点・年・価格 |
| `route_price` | 路線価 | num | 千円/㎡ | ○ | ○ | 国税庁 | |

## 11. 添付・出典（K）

| キー | 項目名 | 型 | 必須 | 備考 |
|---|---|---|---|---|
| `attachments` | 添付資料 | json | ○ | 測量図、公図、登記事項証明書、都市計画図の写し、GeoJSON、DXF |
| `gis_sources_used` | 使用した GIS 取得元 | json | ◎（自動入力時） | 取得元名・データセット・取得日時・ライセンス |
| `geojson_export` | GeoJSON 書き出し | — | — | SiteInfo v0.1 互換の `properties` を含めて書き出す（下記） |

### 11.1 SiteInfo v0.1 GeoJSON との互換

v0.1 の `properties` は v0.2 の項目に次のように対応します。書き出し時は
両方のキーを含め、既存の HBU-ANALYZER・BVCE・MVE を壊さないようにします。

| v0.1 キー | v0.2 キー |
|---|---|
| `name` | `site_name` |
| `address` | `address` |
| `area_m2` / `area_tsubo` / `area_is_manual` | `area_effective_m2` / `area_tsubo` / `area_basis = manual` |
| `zone` / `zone_id` | `zone_type`（表示名は辞書から） |
| `far_percent` / `bcr_percent` | 同名 |
| `road_width_m` | 道路辺の `road_width_m`（最大幅員） |
| `walk_min` / `land_price_man_per_tsubo` | 同名 |
| `district_plan` / `fire_zone` / `height_zone` | `district_plan` / `fire_zone` / `height_district` |
| `shadow_regulation` / `shadow_regulation_label` | `shadow_applies` + `shadow_preset` |
| `gis_source` / `generated_at` | `gis_sources_used` |

## 12. 確定（confirmed）の条件

SiteInfo を `confirmed` にできるのは、次をすべて満たしたときです。

1. 必須（◎）項目がすべて入力されている。
2. 必須項目のメタ属性 `confirm_status` がすべて `confirmed` である
   （自動入力された値も、ユーザーが確認して初めて確定する）。
3. 第 8 節の法令制限に `applies = unknown` の行が残っていない。
4. 日影規制が `regulated` の場合、測定面高さと 2 つの規制時間が入っている。
5. 道路辺が 1 辺以上あり、各道路辺に幅員と道路種別が入っている。

## 13. 未決事項

- 用途地域が 2 以上にわたる場合の按分ルールをどこで解くか（SiteInfo は面積を
  持つだけにする方針）。
- 所有者情報の保存範囲と閲覧権限。
- 自治体ごとの GIS 取得元の登録方法（`gis_source` テーブルで管理する案）。
- 別表第一・第二（用途制限）の参照表をどのエンジンが使うか。
