# SiteInfo データベース（PostgreSQL / PostGIS）

| ファイル | 内容 |
|---|---|
| `schema.sql` | テーブル・型・制約・ビュー・関数の定義 |
| `seed_catalog.sql` | 用途地域、法令コード、GIS 取得元、必須項目定義の初期データ |
| `smoke_test.sql` | 動作確認（サンプル敷地を投入し、制約・確定判定・GeoJSON 出力・平面座標変換を検証。最後にロールバック） |

設計の説明は [`docs/worldsim/siteinfo_db_design.md`](../../docs/worldsim/siteinfo_db_design.md)、
項目の定義は [`docs/worldsim/siteinfo_field_definitions.md`](../../docs/worldsim/siteinfo_field_definitions.md)。

## 使い方

PostgreSQL 16 と PostGIS 3.4 で確認しています。

```bash
createdb siteinfo
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/schema.sql
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/seed_catalog.sql
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/smoke_test.sql   # 任意
```

## 座標系

- 保存: JGD2011 経緯度（EPSG:6668）。GeoJSON を取り込むときは
  `ST_SetSRID(ST_GeomFromGeoJSON(...), 6668)` とする。
- 計算: `site.plane_srid` の平面直角座標系（EPSG:6669〜6687）。
  `site_points_plane(site_id)` が MVE 向けの平面座標（m、反時計回り、
  閉じる終点なし）を返す。
