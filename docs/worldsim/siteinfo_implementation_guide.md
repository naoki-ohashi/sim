---
summary: Codex／Claude Code／Gemini 向けの実装指示。API、GeoJSON 入出力、取得元ごとの自動入力アダプタ、マイルストーン M1〜M6。
status: draft
owner: 大橋
updated: 2026-09-18
---

# SiteInfo 実装指示書 v0.2（Codex／Claude Code 共通）

> この文書は、コーディングエージェント（OpenAI Codex、Claude Code）に SiteInfo を
> 実装させるための指示書です。**どちらのエージェントに渡しても同じものが
> できる**ように、判断はすべてここに書き、エージェントに任せる裁量を小さく
> しています。渡し方は [`siteinfo_agent_prompts.md`](siteinfo_agent_prompts.md)。
>
> 前提文書（必ず先に読む）:
> [`urban_sim_concept_design.md`](urban_sim_concept_design.md) → [`siteinfo_requirements.md`](siteinfo_requirements.md) →
> [`siteinfo_field_definitions.md`](siteinfo_field_definitions.md) →
> [`siteinfo_db_design.md`](siteinfo_db_design.md) → `db/siteinfo/schema.sql`。
> 画面は [`siteinfo_ui_design.md`](siteinfo_ui_design.md)。

## 0. 守ること（原則）

1. **自動入力は補助。確定はユーザー。** 自動取得した値は必ず
   `site_field_provenance` に `source_kind='auto'`、`confirm_status='unconfirmed'`
   で記録し、確認済みの値を上書きしない。
2. **法令・数値は一次情報で確認する。** 条文番号や規制値をコードに埋めるときは
   `docs/mve/legal_basis.md` と同じ流儀で出典を書く。推測で埋めない。
3. **DB のスキーマが正。** `db/siteinfo/schema.sql` を変えるときは、この文書と
   `siteinfo_db_design.md` と `smoke_test.sql` を同じコミットで更新する。
4. **既存の下流を壊さない。** SiteInfo v0.1 GeoJSON の `properties` キーは
   出力し続ける（`v_site_geojson` が保証する）。MVE の入力形式も変えない。
5. **ネットワークに出られない環境で動くこと。** 取得元ごとのアダプタは
   録画したレスポンス（fixture）でテストする。実 API はオプトインの統合テスト。
6. **秘密情報はコードに書かない。** reinfolib の API キーは環境変数
   `REINFOLIB_API_KEY`。`.env.example` に名前だけ置く。
7. **1 マイルストーン 1 PR。** 各 PR は「受け入れ条件」がすべて通ってから開く。

## 1. 技術スタックと配置

| 項目 | 決定 |
|---|---|
| 言語 | Python 3.11 以上（既存 MVE と同じリポジトリ、`pyproject.toml` に追加） |
| API | FastAPI + uvicorn |
| DB アクセス | psycopg 3（`psycopg[binary]`）。ORM は使わない。SQL は `siteinfo/sql/` に置く |
| 型・検証 | pydantic v2 |
| HTTP クライアント | httpx（アダプタ用。タイムアウト必須） |
| 幾何 | shapely 2（既存依存）。座標変換は PostGIS に任せる（Python 側で pyproj を増やさない） |
| テスト | pytest。DB テストは `SITEINFO_TEST_DSN` があるときだけ実行、なければ skip |
| Lint | ruff（`pyproject.toml` に設定を追加） |

パッケージ配置:

```
siteinfo/
  __init__.py
  config.py            # 環境変数（DSN、API キー、タイムアウト）
  db.py                # 接続、トランザクション、SQL ファイルの読み込み
  models.py            # pydantic モデル（API の入出力）
  geojson_io.py        # GeoJSON 取込・書き出し（v0.1 互換）
  plane.py             # 平面直角座標系の系番号判定
  provenance.py        # 取得元・確認状態の記録と確定判定
  autofill/
    __init__.py        # レジストリ（取得元名 → アダプタ）
    base.py            # Adapter 基底クラス、AutofillResult
    gsi_address.py     # 国土地理院 住所検索
    gsi_reverse.py     # 国土地理院 逆ジオコーダ
    reinfolib.py       # 不動産情報ライブラリ
    hazard.py          # ハザードマップポータル
    plateau.py         # PLATEAU（3D 表示用の URL 解決のみ）
    municipal_geojson.py  # 自治体が配布する GeoJSON/Shapefile（ローカルファイル）
  export/
    mve.py             # MVE YAML の生成
  api/
    app.py             # FastAPI アプリ
    routes_sites.py
    routes_autofill.py
    routes_catalog.py
  cli.py               # `siteinfo` コマンド（import/export/autofill/confirm）
tests/siteinfo/
  fixtures/            # 録画したレスポンス JSON、サンプル GeoJSON
  test_*.py
```

`pyproject.toml` の `[project.scripts]` に `siteinfo = "siteinfo.cli:main"` を追加。
optional-dependencies に `siteinfo = ["fastapi", "uvicorn", "psycopg[binary]", "httpx", "pydantic>=2"]`。

## 2. データの流れ

```
住所 or 地図ポリゴン or GeoJSON/DXF
        │
        ▼
 POST /sites  ──► site（draft）＋ plane_srid 自動判定 ＋ 辺の自動生成
        │
        ▼
 POST /sites/{id}/autofill ──► アダプタ群 ──► site_field_provenance（unconfirmed）
        │                                   ＋ 値テーブルへの「提案」書き込み
        ▼
 画面で 1 項目ずつ確認 ──► POST /sites/{id}/fields/{key}/confirm
        │
        ▼
 POST /sites/{id}/confirm ──► site_can_confirm() が空なら status=confirmed
        │
        ▼
 GET /sites/{id}/geojson（v0.1 互換）／GET /sites/{id}/mve.yaml ──► 下流エンジン
```

### 2.1 「提案」書き込みの規則

自動入力は次の 2 段階で書く。

1. `site_field_provenance` に `(site_id, field_key)` の行を upsert。
   `source_kind='auto'`、`gis_source_id`、`source_dataset`、`source_fetched_at`、
   `raw_value`（取得元の生の値）、`confirm_status='unconfirmed'`。
2. 値テーブル（`site_zoning` など）への書き込みは、**その項目が
   `confirmed` でない場合だけ**行う。`confirmed` の項目は `raw_value` に
   新しい値を残すだけにして、画面で「取得元の値と違います」と出す。

`rejected` は「自動値を見たうえで手入力に置き換えた」状態。以後の自動入力は
値テーブルを触らない（`raw_value` は更新する）。

## 3. API 仕様

ベースパス `/api/v1`。すべて JSON。エラーは `{"error": {"code": ..., "message": ..., "details": [...]}}`。

### 3.1 敷地

| メソッド | パス | 内容 |
|---|---|---|
| `POST` | `/sites` | 敷地を作る。本文は 3.4 の `SiteCreate` |
| `GET` | `/sites` | 一覧。`?status=&municipality_code=&q=`（名称・住所の部分一致） |
| `GET` | `/sites/{id}` | 敷地の全体（`SiteDetail`）。値と provenance を項目ごとに束ねて返す |
| `PATCH` | `/sites/{id}` | 手入力での更新。本文は変更する項目だけ。更新した項目の provenance を `manual` / `unconfirmed` にする（確認は別 API） |
| `DELETE` | `/sites/{id}` | `status='archived'` にする。物理削除しない |
| `GET` | `/sites/{id}/history` | `site_history` の一覧 |

### 3.2 GeoJSON 入出力

| メソッド | パス | 内容 |
|---|---|---|
| `POST` | `/sites/import/geojson` | v0.1 / v0.2 の GeoJSON Feature（または FeatureCollection の先頭 1 件）から敷地を作る。3.5 参照 |
| `GET` | `/sites/{id}/geojson` | `v_site_geojson.feature` をそのまま返す。`Content-Disposition` で `siteinfo.geojson` |
| `GET` | `/sites/{id}/geojson?full=1` | v0.2 の全項目＋各項目の provenance を `properties.fields` に含める |
| `GET` | `/sites/{id}/mve.yaml` | MVE 入力 YAML（4 章） |

### 3.2.1 用途地域の分割

| メソッド | パス | 内容 |
|---|---|---|
| `GET` | `/sites/{id}/zone-parts` | 部分の一覧（ポリゴン、用途地域、指定値、面積、割合）と `site_zoning_from_parts()` の導出値 |
| `PUT` | `/sites/{id}/zone-parts` | 部分を丸ごと置き換える。本文は `ZonePart[]`（GeoJSON ポリゴン、`zone_type`、`far_percent`、`bcr_percent`、`trace_source`）。保存後に導出値を `site_zoning` に `derived` として書き、`zoning_split = true` にする。部分が 0 件なら `zoning_split = false` に戻す |
| `POST` | `/sites/{id}/zone-parts/split` | 地図でトレースした境界線（GeoJSON LineString、複数可）で敷地ポリゴンを切り、部分の下書きを返す（保存はしない）。部分ごとの用途地域・指定値は空で返し、画面で入力させる |

規則（項目定義書 5.1）: 用途は過半の面積の部分の用途地域、容積率・建蔽率は
面積の加重平均。導出は DB の `site_zoning_from_parts()` に任せ、Python 側で
計算し直さない。部分の面積合計が敷地の図形面積の ±1% に収まらないときは 422。

### 3.3 自動入力・確認・確定

| メソッド | パス | 内容 |
|---|---|---|
| `GET` | `/autofill/sources` | 使えるアダプタの一覧（名前、対象項目、必要な設定、有効かどうか） |
| `POST` | `/sites/{id}/autofill` | 本文 `{"sources": ["reinfolib", "gsi_reverse", ...]}`（省略で有効なもの全部）。結果は 3.6 の `AutofillReport` |
| `GET` | `/sites/{id}/provenance` | 項目ごとの provenance 一覧 |
| `POST` | `/sites/{id}/fields/{field_key}/confirm` | 本文 `{"confirmed_by": "...", "note": "..."}`。`confirm_status='confirmed'` |
| `POST` | `/sites/{id}/fields/{field_key}/reject` | 本文 `{"value": ..., "confirmed_by": "...", "note": "..."}`。手入力値で置換して `rejected` |
| `GET` | `/sites/{id}/confirm-check` | `site_can_confirm()` の結果。`{"ok": bool, "reasons": [...]}` |
| `POST` | `/sites/{id}/confirm` | 確定。`site_can_confirm()` が空でなければ 409 と理由を返す |
| `POST` | `/sites/{id}/reopen` | `confirmed` → `draft`。理由必須。履歴に残る |

### 3.4 カタログ

| メソッド | パス | 内容 |
|---|---|---|
| `GET` | `/catalog/fields` | `field_definition` |
| `GET` | `/catalog/zone-types` | `zone_type_catalog` |
| `GET` | `/catalog/legal-restrictions` | `legal_restriction_catalog` |
| `GET` | `/catalog/gis-sources?municipality_code=` | `gis_source`（全国共通＋該当自治体） |

### 3.5 主要モデル（pydantic）

```python
class SiteCreate(BaseModel):
    site_name: str | None = None
    address: str | None = None
    geometry: dict | None = None          # GeoJSON Polygon/MultiPolygon（経緯度）
    points_plane: list[tuple[float, float]] | None = None  # 平面座標で与える場合
    plane_srid: int | None = None         # points_plane のときは必須
    shape_source: ShapeSource = "polygon"
    lot_numbers: list[LotNumber] = []
    created_by: str
    # geometry か points_plane のどちらか一方が必須（validator）

class FieldValue(BaseModel):
    key: str
    value: Any
    source_kind: Literal["auto", "manual", "derived"] | None
    source_name: str | None
    source_dataset: str | None
    fetched_at: datetime | None
    raw_value: Any | None
    confirm_status: Literal["unconfirmed", "confirmed", "rejected"] | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    note: str | None
    differs_from_raw: bool           # 値と raw_value が食い違うとき true

class SiteDetail(BaseModel):
    site_id: UUID
    status: SiteStatus
    version: int
    fields: dict[str, FieldValue]    # field_key → 値＋provenance
    edges: list[Edge]
    legal_restrictions: list[LegalRestriction]
    geometry: dict                   # GeoJSON
    area_geom_m2: float
    can_confirm: bool
    confirm_reasons: list[str]
```

### 3.6 GeoJSON 取込の規則

- `geometry` は Polygon か MultiPolygon。それ以外は 400。
- SRID は 4326 として受け取り、DB には `ST_SetSRID(..., 6668)` で入れる
  （JGD2011 と WGS84 の差は敷地規模では無視できる。変換はしない。理由を
  コードのコメントに書く）。
- 頂点は反時計回りに正規化（`ST_ForcePolygonCCW`）。無効なポリゴンは
  `ST_MakeValid` を試み、それでも無効なら 400。
- `plane_srid` は 5 章で判定。
- v0.1 の `properties` を次のように取り込む。値はすべて provenance
  `source_kind='manual'`、`source_dataset='geojson import'`、`unconfirmed`。

| v0.1 キー | 取込先 |
|---|---|
| `name` | `site.site_name` |
| `address` | `site.address` |
| `area_m2`, `area_is_manual` | `site.area_effective_m2`、`area_basis = 'manual' if area_is_manual else 'geom'` |
| `zone_id` | `site_zoning.zone_type`（`zone_type_catalog` に無ければ取り込まず警告） |
| `far_percent`, `bcr_percent` | `site_zoning` |
| `road_width_m` | 辺の自動生成後、最長辺を `road` にして幅員を入れる（暫定。画面で確認させる） |
| `district_plan`, `fire_zone`, `height_zone` | `site_zoning.district_plan`（「指定なし」→ null）、`fire_zone`（8.3 の対応表）、`height_district` |
| `shadow_regulation` | `none` → `shadow_applies='none'`、`3h_2h` 等 → `regulated` と時間、`unknown` → `unknown` |
| `walk_min`, `land_price_man_per_tsubo` | `site_market` |

### 3.7 AutofillReport

```python
class AutofillItem(BaseModel):
    field_key: str
    proposed: Any
    raw_value: Any
    applied: bool                    # 値テーブルに書いたか
    reason: str | None               # 書かなかった理由（confirmed / rejected / no data）
    source: str                      # アダプタ名
    dataset: str | None
    fetched_at: datetime

class AutofillReport(BaseModel):
    site_id: UUID
    items: list[AutofillItem]
    errors: list[dict]               # {"source": ..., "message": ...}
```

## 4. MVE 出力（`export/mve.py`）

`GET /sites/{id}/mve.yaml` と `siteinfo export-mve` は次の YAML を返す。
値の対応は `siteinfo_db_design.md` 5 節。

```yaml
site:
  name: <site_name>
  points: [[x, y], ...]           # site_points_plane() の結果
  north_angle_deg: <north_angle_deg>
  wall_setback_m: <辺の wall_setback_m が全て同じならその値、違えば 0 と警告>
  edges:
    - kind: road
      road_width_m: 12.0
    - kind: adjacent
      relaxation: {kind: water, width_m: 4.0}   # relaxation_kind != none のとき
zoning:
  zone_type: <zone_type_catalog.mve_code>   # 分割ありなら過半の用途地域
  far_ratio: <far_percent>                  # 分割ありなら面積按分値
  coverage_ratio: <bcr_percent>
  absolute_height_limit_m: <あれば>
shadow:                            # shadow_applies == regulated のときだけ
  measurement_height_m: <measurement_height_m>
  line_5m_max_hours: <hours_5m>
  line_10m_max_hours: <hours_10m>
  latitude_deg: <ST_Y(centroid)>
  hokkaido: <hokkaido>
```

`status != 'confirmed'` の敷地を出力するときは、YAML 先頭にコメントで
`# WARNING: SiteInfo は未確定です` を入れる。

## 5. 平面直角座標系の判定（`plane.py`）

代表点（centroid）の都道府県・市区町村コードから系番号（I〜XIX）を決め、
EPSG 6669〜6687 に対応させる。判定表は国土地理院「平面直角座標系（平成十四年
国土交通省告示第九号）」の区域表に従い、**告示の区域表を `siteinfo/data/plane_zones.json`
に出典 URL と取得日つきで置く**。北海道（XI〜XIII）、東京都の島しょ部
（XIV、XVIII、XIX）、鹿児島・沖縄（XV〜XVII）のように市区町村単位で分かれる
ところがあるので、都道府県だけで決めない。判定できないときは 422 でユーザーに
選ばせる。

## 6. 自動入力アダプタ

### 6.1 共通インターフェース（`autofill/base.py`）

```python
@dataclass
class AutofillContext:
    site_id: UUID
    centroid_lonlat: tuple[float, float]
    geometry_geojson: dict
    address: str | None
    municipality_code: str | None
    plane_srid: int

@dataclass
class AutofillResult:
    field_key: str            # field_definition.field_key
    value: Any                # 正規化した値（DB の型に合わせる）
    raw_value: Any            # 取得元の生の値（監査用。JSON 化できるもの）
    dataset: str              # レイヤ名・API 名（例: "XKT002"）
    fetched_at: datetime
    note: str | None = None   # 「z14 タイル内で最も近い地物」など

class Adapter(Protocol):
    name: str                 # レジストリのキー。gis_source.name と対応
    fields: frozenset[str]    # このアダプタが埋める field_key
    def available(self, settings) -> tuple[bool, str | None]: ...  # 有効か、無効なら理由
    def fetch(self, ctx: AutofillContext) -> list[AutofillResult]: ...
```

規則:

- `fetch` は例外を投げてよい。呼び出し側が捕まえて `AutofillReport.errors` に入れ、
  他のアダプタは続行する。
- タイムアウトは 10 秒。リトライは 1 回まで。
- 取得元のレスポンスは `raw_value` にそのまま残す（サイズ上限 64KB、超えたら要約）。
- **点で引くときは centroid、面で引くときは敷地ポリゴンとの交差**を使う。
  用途地域のように敷地が 2 区域にまたがることがある項目は、交差する地物を
  すべて `raw_value` に残す。交差が 2 件以上で、2 番目以降の交差面積が敷地の
  5% を超えるときは、交差ポリゴンから `site_zone_part` の下書き（`trace_source =
  'gis_intersection'`、`unconfirmed`）を作り、`zone_type` / `far_percent` /
  `bcr_percent` には `site_zoning_from_parts()` の導出値を提案する。5% 以下なら
  面積最大の地物だけを提案し、`note` に他の地物を書く。
- `gis_source` テーブルに該当行が無ければ、アダプタ初回実行時に登録する
  （`name`、`provider`、`dataset`、`url`、`license`）。

### 6.2 国土地理院 住所検索（`gsi_address.py`）

| 項目 | 内容 |
|---|---|
| URL | `https://msearch.gsi.go.jp/address-search/AddressSearch?q=<住所>` |
| 認証 | 不要 |
| 用途 | 住所文字列 → 候補の座標。**敷地作成前の補助**（`POST /geocode` として公開してもよい） |
| 埋める項目 | なし（`SiteCreate` の座標候補を返すだけ） |
| 注意 | 結果は複数。先頭を自動採用せず、画面で選ばせる |

### 6.3 国土地理院 逆ジオコーダ（`gsi_reverse.py`）

| 項目 | 内容 |
|---|---|
| URL | `https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress?lat=<lat>&lon=<lon>` |
| 認証 | 不要 |
| 埋める項目 | `municipality_code`（`muniCd`）、`address`（`lv01Nm` を市区町村名と結合）、`prefecture`、`city` |
| 注意 | `muniCd` は 5 桁。市区町村名は国土地理院の `muni.js` 相当の表が必要。表は `siteinfo/data/municipalities.json` に総務省の全国地方公共団体コード（出典・取得日つき）で置く |

### 6.4 不動産情報ライブラリ（`reinfolib.py`）

SiteInfo v0.1 が使っていた API をそのまま使う。

| 項目 | 内容 |
|---|---|
| ベース URL | `https://www.reinfolib.mlit.go.jp/ex-api/external/` |
| 認証 | ヘッダ `Ocp-Apim-Subscription-Key: <REINFOLIB_API_KEY>`（API キーは https://www.reinfolib.mlit.go.jp/api/request/ で申請） |
| 共通パラメータ | `response_format=geojson&z=<zoom>&x=<tile x>&y=<tile y>`。ズームは 14 を既定にし、返る地物が無ければ 13 で再試行 |
| タイル計算 | Web メルカトルのタイル番号（v0.1 の `lonLatToTile` と同じ式） |

| API | 内容 | 埋める項目 | 使う属性（v0.1 実績） |
|---|---|---|---|
| `XKT002` | 用途地域 | `zone_type`, `far_percent`, `bcr_percent` | `use_area_ja`（用途地域名 → `zone_type_catalog.label_ja` で引く）、`u_floor_area_ratio_ja`、`u_building_coverage_ratio_ja`（数値以外を除去） |
| `XKT023` | 地区計画 | `district_plan` | `plan_name` または `plan_type_ja` |
| `XKT014` | 防火・準防火地域 | `fire_zone` | `plan_type_ja`（8.3 の対応表） |
| `XKT024` | 高度地区 | `height_district` | `plan_name` または `plan_type_ja` |
| `XPT002` | 地価公示 | `official_land_price`, `land_price_man_per_tsubo` | `year` を今年から 4 年分さかのぼって最初に地物が返る年。最も近い地点。㎡単価 → 坪単価は ×3.30579 ÷ 10000 |

規則:

- 上記以外の API（都市計画区域・区域区分、立地適正化計画、災害リスクなど）は
  公式仕様書で存在と属性名を確認してから追加する。**属性名を推測して書かない。**
- 用途地域名が `zone_type_catalog.label_ja` に一致しないときは `value=None`、
  `raw_value` に名称を残し、`note` に「対応表に無い」と書く。
- 地物が返らないときは `AutofillResult` を返さない（「指定なし」とは断定しない。
  画面で「取得できず」と出す）。v0.1 が「指定なし」と表示していた挙動は
  引き継がない。

### 6.5 ハザードマップポータル（`hazard.py`）

| 項目 | 内容 |
|---|---|
| 取得元 | 重ねるハザードマップの配信タイル・WMS（https://disaportal.gsi.go.jp/ の「ハザードマップポータルサイトのデータ利用」に掲載の URL） |
| 認証 | 不要 |
| 埋める項目 | `site_legal_restriction` の `flood_hazard`、`sediment_disaster`、`tsunami`（`applies` と `detail`） |
| 方法 | 敷地ポリゴンと重なるタイルの画素値または WMS GetFeatureInfo。画素の色→区分の対応表は公式凡例から作り、出典つきで `siteinfo/data/hazard_legend.json` に置く |
| 注意 | 該当なしと判定できるのは、そのレイヤが敷地の自治体で整備済みのときだけ。整備状況の情報が取れなければ `applies='unknown'` のまま `note` に理由を書く |

### 6.6 PLATEAU（`plateau.py`）

| 項目 | 内容 |
|---|---|
| 取得元 | `https://api.plateauview.mlit.go.jp/datacatalog/plateau-datasets` |
| 認証 | 不要 |
| 埋める項目 | なし。`municipality_code` から建築物モデル（bldg、LOD2 優先）の 3D Tiles URL を解決し、画面の 3D 表示に渡す |
| API | `GET /sites/{id}/plateau-tilesets` |

### 6.7 自治体 GeoJSON／Shapefile（`municipal_geojson.py`）

自治体ごとに形式が違う「都市計画情報」を取り込む受け皿。ネットワークではなく
**ローカルに置いたファイル**を読む（ダウンロードは人が行い、`gis_source` に
出典・取得日を登録する）。

| 項目 | 内容 |
|---|---|
| 設定 | `siteinfo/data/municipal/<municipality_code>/sources.yaml` に、レイヤごとの
ファイルパス、`field_key`、属性名→値の対応を書く |
| 埋める項目 | `area_division`、`zone_type`、`height_district`、`district_plan`、`planned_road`、`shadow_applies`、`shadow_measurement_height_m`、`shadow_hours_5m`、`shadow_hours_10m`、`min_lot_area_m2` など、設定で指定したもの |
| 方法 | shapely で敷地ポリゴンと交差判定。CRS は `sources.yaml` に書く（EPSG）。変換は PostGIS に `ST_Transform` させる（`ST_GeomFromGeoJSON` → `ST_Transform`） |
| 最初の対象 | 東京都（都市計画情報の GeoJSON が公開されている区）。`sources.yaml` の例を 1 自治体分入れる |

設定例:

```yaml
crs_epsg: 6668
layers:
  - file: youto.geojson
    fields:
      zone_type:
        attribute: 用途地域
        map: {第一種低層住居専用地域: 1res, 商業地域: commercial}
      far_percent: {attribute: 容積率}
      bcr_percent: {attribute: 建ぺい率}
  - file: hikage.geojson
    fields:
      shadow_applies: {const: regulated}
      shadow_measurement_height_m: {attribute: 測定面}
      shadow_hours_5m: {attribute: 規制時間5m}
      shadow_hours_10m: {attribute: 規制時間10m}
```

## 7. CLI（`siteinfo/cli.py`）

| コマンド | 内容 |
|---|---|
| `siteinfo import-geojson <file> --by <user>` | 敷地を作って `site_id` を表示 |
| `siteinfo autofill <site_id> [--sources a,b]` | 自動入力。`AutofillReport` を表示 |
| `siteinfo show <site_id>` | 項目ごとの値・取得元・確認状態を表で表示 |
| `siteinfo confirm-field <site_id> <field_key> --by <user>` | 項目を確認済みにする |
| `siteinfo confirm <site_id> --by <user>` | 確定（できなければ理由を表示して終了コード 1） |
| `siteinfo export-geojson <site_id> [-o file]` | v0.1 互換 GeoJSON |
| `siteinfo export-mve <site_id> [-o file]` | MVE YAML |

## 8. 対応表・正規化

### 8.1 用途地域

`zone_type_catalog.label_ja` で引く。表記ゆれ（「建ぺい率」「建蔽率」、全角数字）は
正規化してから比較する。

### 8.2 日影規制のプリセット

| `shadow_preset` | `measurement_height_m` | `hours_5m` | `hours_10m` |
|---|---|---|---|
| `3h_2h` | 画面で選択（1.5 / 4.0） | 3 | 2 |
| `4h_2.5h` | 同上 | 4 | 2.5 |
| `5h_3h` | 同上（4.0 / 6.5） | 5 | 3 |
| `custom` | 自由入力 | 自由入力 | 自由入力 |

### 8.3 防火地域

| 取得元の文字列 | `fire_zone` |
|---|---|
| 防火地域 | `fire` |
| 準防火地域 | `quasi_fire` |
| 法22条区域／22条区域 | `article22` |
| 指定なし／該当なし | `none` |
| それ以外 | `None`（`raw_value` に残す） |

## 9. テスト

| 種類 | 内容 | 実行条件 |
|---|---|---|
| 単体 | GeoJSON 正規化、タイル計算、対応表、`plane.py` の系判定、各アダプタの fixture 解析 | 常時 |
| DB | `schema.sql` → `seed_catalog.sql` → `smoke_test.sql` に加え、API 経由で作成→自動入力（fixture）→確認→確定→GeoJSON→MVE YAML までの一連 | `SITEINFO_TEST_DSN` があるとき |
| 統合 | 実 API を叩く。reinfolib はキーがあるときだけ | `SITEINFO_LIVE_TESTS=1` |
| 回帰 | `sample_site.geojson`（v0.1）を取り込み、書き出した GeoJSON を HBU-ANALYZER／BVCE が読める形（v0.1 のキーがすべて存在）であること | 常時 |

fixture は `tests/siteinfo/fixtures/<adapter>/<case>.json` に、取得日と URL を
先頭の `_meta` に入れて保存する。

## 10. マイルストーンと受け入れ条件

各マイルストーンは 1 PR。PR 本文に受け入れ条件のチェックリストを貼る。

### M1: 基盤（DB 接続、敷地の作成と GeoJSON 入出力）

- [ ] `siteinfo` パッケージ、`config.py`、`db.py`、`models.py`、`plane.py`
- [ ] `POST /sites`、`GET /sites/{id}`、`POST /sites/import/geojson`、`GET /sites/{id}/geojson`
- [ ] 辺の自動生成（頂点順に `site_edge` を作る。種別は `adjacent`、道路辺は未指定）
- [ ] `sample_site.geojson` を取り込んで書き出すと、v0.1 のキーがすべて含まれる
- [ ] `plane.py` の判定表と出典
- [ ] `pytest`（DB あり／なしの両方）が通る。`ruff` が通る

### M2: provenance と確認・確定

- [ ] `provenance.py`、`PATCH /sites/{id}`、`confirm` / `reject` / `confirm-check` / `confirm` / `reopen`
- [ ] 用途地域の分割 API（3.2.1）。分割ありの敷地で導出値が `site_zoning` に `derived` として入り、覆率が範囲外なら確定できないテスト
- [ ] `SiteDetail.fields` に provenance が束ねられて返る
- [ ] 確認していない必須項目があると `confirm` が 409 で理由を返す
- [ ] `site_history` に版が残る

### M3: 自動入力（国土地理院、reinfolib）

- [ ] `autofill/base.py`、レジストリ、`GET /autofill/sources`、`POST /sites/{id}/autofill`
- [ ] `gsi_reverse`、`reinfolib`（XKT002／XKT023／XKT014／XKT024／XPT002）
- [ ] fixture で単体テスト。`confirmed` の項目を上書きしないテスト
- [ ] `gis_source` への自動登録

### M4: MVE 出力と CLI

- [ ] `export/mve.py`、`GET /sites/{id}/mve.yaml`
- [ ] 生成した YAML を `mve` コマンドに渡して計算が走る（`tests/siteinfo/test_mve_roundtrip.py`）
- [ ] CLI 7 コマンド

### M5: ハザード、自治体 GeoJSON、PLATEAU

- [ ] `hazard.py`（凡例表と出典）、`municipal_geojson.py`（東京都 1 区の設定例）、`plateau.py`
- [ ] `site_legal_restriction` への自動入力（`applies` は `yes` / `no` / `unknown` の判定根拠を `note` に書く）

### M6: 画面（[`siteinfo_ui_design.md`](siteinfo_ui_design.md)）

- [ ] 画面設計書の各画面と受け入れ条件

## 11. エージェントへの補足

- 分からないことは推測せず、`docs/worldsim/siteinfo_field_definitions.md` 13 節の
  「未決事項」に追記して PR 本文で質問する。
- 新しい取得元 API を使うときは、公式ドキュメントの URL と確認日を
  アダプタのモジュール docstring に書く。
- 既存の `mve/`、`web/`、`jwcad_volume/` は変更しない。必要なら別 PR で提案する。
- コミットメッセージは英語 1 行の要約＋日本語の本文で可。PR 本文は日本語。
