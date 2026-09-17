-- SiteInfo v0.2 PostgreSQL / PostGIS schema (draft)
--
-- 設計の説明は docs/worldsim/siteinfo_db_design.md、
-- 項目の定義は docs/worldsim/siteinfo_field_definitions.md を参照。
--
-- 座標系: 保存は JGD2011 経緯度 (EPSG:6668)。面積・距離は site.plane_srid
-- (EPSG:6669-6687, 平面直角座標系 I-XIX) に ST_Transform して計算する。

create extension if not exists postgis;
create extension if not exists pgcrypto;  -- gen_random_uuid()

create schema if not exists siteinfo;
set search_path to siteinfo, public;

-- ---------------------------------------------------------------------
-- 列挙型
-- ---------------------------------------------------------------------
create type site_status as enum ('draft', 'confirmed', 'archived');
create type shape_source as enum
    ('survey_triangles', 'polygon', 'coordinates', 'geojson', 'dxf', 'cadastral');
create type area_basis as enum ('registered', 'measured', 'geom', 'manual');
create type edge_kind as enum ('road', 'adjacent', 'none');
create type relaxation_kind as enum ('none', 'park', 'water', 'railway');
create type road_type as enum (
    'art42_1_1',  -- 法42条1項1号 道路法による道路
    'art42_1_2',  -- 1項2号 都市計画法等による道路
    'art42_1_3',  -- 1項3号 既存道路
    'art42_1_4',  -- 1項4号 計画道路
    'art42_1_5',  -- 1項5号 位置指定道路
    'art42_2',    -- 2項道路（みなし道路）
    'art42_3',    -- 3項道路
    'art43_proviso',  -- 43条ただし書
    'not_road',   -- 建築基準法上の道路でない
    'unknown'
);
create type area_division as enum (
    'urbanization_promotion', 'urbanization_control', 'undivided',
    'outside', 'quasi_city_planning'
);
create type fire_zone as enum ('fire', 'quasi_fire', 'article22', 'none');
create type shadow_applies as enum ('regulated', 'none', 'unknown');
create type shadow_target as enum ('eaves7m_or_3f', 'height10m');
create type applies_state as enum ('yes', 'no', 'unknown');
create type source_kind as enum ('auto', 'manual', 'derived');
create type confirm_status as enum ('unconfirmed', 'confirmed', 'rejected');
create type requirement_level as enum ('required', 'recommended', 'optional');
create type auto_fill_level as enum ('established', 'varies', 'none');

-- ---------------------------------------------------------------------
-- カタログ（コード表）
-- ---------------------------------------------------------------------

-- 項目定義書そのもの。画面の必須表示・確定判定をデータで駆動する。
create table field_definition (
    field_key       text primary key,
    group_code      text not null,          -- A..K（定義書の節）
    label_ja        text not null,
    data_type       text not null,          -- text/int/num/bool/enum/date/geom/json
    unit            text,
    required        requirement_level not null default 'optional',
    auto_fill       auto_fill_level not null default 'none',
    law_reference   text,
    description     text,
    sort_order      int not null default 0
);

-- 用途地域コード表。mve_code は MVE zoning.zone_type と一致させる。
create table zone_type_catalog (
    zone_type   text primary key,           -- 例: '1res'
    label_ja    text not null,              -- 例: '第一種低層住居専用地域'
    mve_code    text not null,
    shadow_target shadow_target,            -- 別表第四の対象建築物基準
    sort_order  int not null default 0
);

-- 重要事項説明書「法令に基づく制限」の法令コード表。
create table legal_restriction_catalog (
    law_code        text primary key,       -- 例: 'sediment_disaster'
    law_name_ja     text not null,          -- 例: '土砂災害防止法'
    typical_zones   text,                   -- 主な区域・制限の説明
    auto_fill       auto_fill_level not null default 'none',
    source_hint     text,                   -- 取得元候補
    sort_order      int not null default 0,
    active          boolean not null default true
);

-- 自動入力に使う GIS・API 取得元。自治体ごとに登録する。
create table gis_source (
    gis_source_id       uuid primary key default gen_random_uuid(),
    name                text not null,      -- 例: '国土交通省 不動産情報ライブラリ'
    provider            text,               -- 例: '国土交通省'
    municipality_code   text,               -- 全国共通なら null
    dataset             text,               -- レイヤ名・API 名
    url                 text,
    license             text,
    format              text,               -- geojson / wms / rest / manual
    note                text,
    active              boolean not null default true
);

-- ---------------------------------------------------------------------
-- 敷地本体
-- ---------------------------------------------------------------------
create table site (
    site_id             uuid primary key default gen_random_uuid(),
    site_name           text,
    status              site_status not null default 'draft',

    -- 所在
    address             text,
    prefecture          text,
    city                text,
    municipality_code   text,               -- JIS X 0402
    lot_numbers         jsonb not null default '[]'::jsonb,
        -- [{"lot": "1-2", "land_category": "宅地", "area_m2": 123.45}]
    owner_summary       text,

    -- 形状・位置
    geom                geometry(MultiPolygon, 6668) not null,
    shape_source        shape_source not null default 'polygon',
    plane_srid          int not null check (plane_srid between 6669 and 6687),
    centroid            geometry(Point, 6668)
                        generated always as (ST_Centroid(geom)) stored,
    elevation_m         numeric(7, 2),
    north_angle_deg     numeric(6, 3) not null default 0,
    survey_drawing_ref  text,

    -- 面積
    area_registered_m2  numeric(12, 2),
    area_measured_m2    numeric(12, 2),
    area_effective_m2   numeric(12, 2),
    area_basis          area_basis,
    setback_area_m2     numeric(12, 2),

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    created_by          text,
    updated_by          text,
    version             int not null default 1,

    constraint site_geom_valid check (ST_IsValid(geom)),
    constraint site_area_basis_pair check (
        (area_effective_m2 is null) = (area_basis is null)
    )
);

create index site_geom_gix on site using gist (geom);
create index site_municipality_idx on site (municipality_code);
create index site_status_idx on site (status);

-- 図形面積（㎡）。平面直角座標に変換して計算する。生成列にはできない
-- （ST_Transform は immutable でない）ので、ビューで提供する。
create or replace function site_area_geom_m2(s site)
returns numeric language sql stable as $$
    select round(ST_Area(ST_Transform(s.geom, s.plane_srid))::numeric, 2)
$$;

-- ---------------------------------------------------------------------
-- 境界辺（MVE の edges と同じ構造）
-- ---------------------------------------------------------------------
create table site_edge (
    site_id             uuid not null references site on delete cascade,
    edge_seq            int  not null,      -- 反時計回りの辺番号（0 始まり）
    geom                geometry(LineString, 6668),
    edge_kind           edge_kind not null default 'adjacent',
    road_width_m        numeric(6, 2),
    road_type           road_type,
    road_setback_m      numeric(6, 2),
    is_private_road     boolean,
    private_road_burden text,
    wall_setback_m      numeric(6, 2),
    relaxation_kind     relaxation_kind not null default 'none',
    relaxation_width_m  numeric(6, 2),
    note                text,
    primary key (site_id, edge_seq),
    constraint site_edge_road_needs_width check (
        edge_kind <> 'road' or road_width_m is not null
    ),
    constraint site_edge_relaxation_width check (
        relaxation_kind = 'none' or relaxation_width_m is not null
    )
);

-- ---------------------------------------------------------------------
-- 都市計画法・建築基準法（形態規制）
-- ---------------------------------------------------------------------
create table site_zoning (
    site_id                     uuid primary key references site on delete cascade,

    -- 都市計画法
    area_division               area_division,
    zone_type                   text references zone_type_catalog,
    zone_type_secondary         jsonb,      -- [{"zone_type": "...", "area_m2": ...}]
    far_percent                 int check (far_percent between 50 and 1300),
    bcr_percent                 int check (bcr_percent between 30 and 100),
    bcr_bonus_corner            boolean,
    bcr_bonus_fireproof         boolean,
    fire_zone                   fire_zone,
    height_district             text,
    height_district_max_m       numeric(6, 2),
    height_district_min_m       numeric(6, 2),
    special_use_district        text,
    high_use_district           boolean,
    district_plan               text,       -- 名称。指定なしは null
    district_plan_rules         jsonb,
    scenic_district             text,
    planned_road                jsonb,      -- [{"name":..., "width_m":..., "decided": true, "overlap_m2": ...}]
    redevelopment_project       text,
    development_permit_required applies_state,
    min_lot_area_m2             numeric(10, 2),

    -- 建築基準法（形態規制）
    absolute_height_limit_m     numeric(6, 2),
    road_slant_applies          boolean,
    adjacent_slant_applies      boolean,
    north_slant_applies         boolean,
    sky_ratio_allowed           boolean,
    exterior_wall_setback_m     numeric(5, 2),
    wall_line                   text,
    building_agreement          text,
    local_ordinances            jsonb       -- [{"name":..., "summary":...}]
);

-- ---------------------------------------------------------------------
-- 日影規制（条例の組み合わせをそのまま持つ）
-- ---------------------------------------------------------------------
create table site_shadow_regulation (
    site_id                 uuid primary key references site on delete cascade,
    shadow_applies          shadow_applies not null default 'unknown',
    measurement_height_m    numeric(3, 1)
                            check (measurement_height_m in (1.5, 4.0, 6.5)),
    hours_5m                numeric(3, 1) check (hours_5m > 0),   -- 5m超10m以内
    hours_10m               numeric(3, 1) check (hours_10m > 0),  -- 10m超
    target_criteria         shadow_target,
    hokkaido                boolean not null default false,
    ordinance_ref           text,
    constraint shadow_regulated_needs_values check (
        shadow_applies <> 'regulated'
        or (measurement_height_m is not null
            and hours_5m is not null and hours_10m is not null)
    ),
    constraint shadow_hours_order check (
        hours_5m is null or hours_10m is null or hours_5m >= hours_10m
    )
);

-- ---------------------------------------------------------------------
-- 重要事項説明書「法令に基づく制限」（法令ごとに 1 行）
-- ---------------------------------------------------------------------
create table site_legal_restriction (
    site_id     uuid not null references site on delete cascade,
    law_code    text not null references legal_restriction_catalog,
    applies     applies_state not null default 'unknown',
    detail      text,
    reference   text,
    primary key (site_id, law_code),
    constraint legal_restriction_detail_when_yes check (
        applies <> 'yes' or detail is not null
    )
);

-- ---------------------------------------------------------------------
-- 供給施設・既存建物
-- ---------------------------------------------------------------------
create table site_utility (
    site_id             uuid primary key references site on delete cascade,
    water_supply        text,   -- front_road / on_site / none
    water_pipe_mm       int,
    sewerage            text,   -- public / septic / none
    gas                 text,   -- city_gas / lp / none
    electricity         text,
    utility_notes       text,
    asbestos_survey     text,
    seismic_diagnosis   text,
    existing_building   jsonb   -- {"structure":..., "floors":..., "gfa_m2":..., "built_year":...}
);

-- ---------------------------------------------------------------------
-- 市場・立地
-- ---------------------------------------------------------------------
create table site_market (
    site_id                     uuid primary key references site on delete cascade,
    nearest_station             text,
    walk_min                    int check (walk_min >= 0),
    land_price_man_per_tsubo    numeric(10, 1),
    official_land_price         jsonb,  -- [{"point":..., "year":..., "yen_per_m2":...}]
    route_price_k_yen_per_m2    numeric(10, 1)
);

-- ---------------------------------------------------------------------
-- 添付資料
-- ---------------------------------------------------------------------
create table site_attachment (
    attachment_id   uuid primary key default gen_random_uuid(),
    site_id         uuid not null references site on delete cascade,
    kind            text not null,  -- survey / cadastral / registry / city_plan / geojson / dxf / other
    title           text,
    storage_uri     text not null,
    mime_type       text,
    uploaded_at     timestamptz not null default now(),
    uploaded_by     text,
    note            text
);
create index site_attachment_site_idx on site_attachment (site_id);

-- ---------------------------------------------------------------------
-- 項目ごとの取得元・確認状態（自動入力は補助、最終確認は必須）
-- ---------------------------------------------------------------------
create table site_field_provenance (
    site_id             uuid not null references site on delete cascade,
    field_key           text not null references field_definition,
    source_kind         source_kind not null default 'manual',
    gis_source_id       uuid references gis_source,
    source_dataset      text,
    source_fetched_at   timestamptz,
    raw_value           jsonb,          -- 取得元から得た生の値（比較・監査用）
    confirm_status      confirm_status not null default 'unconfirmed',
    confirmed_by        text,
    confirmed_at        timestamptz,
    note                text,
    primary key (site_id, field_key),
    constraint provenance_auto_needs_source check (
        source_kind <> 'auto' or gis_source_id is not null
    ),
    constraint provenance_confirmed_has_who check (
        confirm_status <> 'confirmed'
        or (confirmed_by is not null and confirmed_at is not null)
    )
);

-- ---------------------------------------------------------------------
-- 変更履歴（site 行を丸ごと保存）
-- ---------------------------------------------------------------------
create table site_history (
    history_id  bigserial primary key,
    site_id     uuid not null,
    version     int not null,
    changed_at  timestamptz not null default now(),
    changed_by  text,
    row_data    jsonb not null
);
create index site_history_site_idx on site_history (site_id, version);

create or replace function site_history_trigger() returns trigger
language plpgsql as $$
begin
    insert into site_history (site_id, version, changed_by, row_data)
    values (old.site_id, old.version, old.updated_by, to_jsonb(old));
    new.version := old.version + 1;
    new.updated_at := now();
    return new;
end $$;

create trigger site_history_before_update
    before update on site
    for each row execute function site_history_trigger();

-- ---------------------------------------------------------------------
-- 確定条件（項目定義書 12 節）
-- ---------------------------------------------------------------------

-- 未確認の必須項目
create or replace view v_site_unconfirmed_required as
select s.site_id, d.field_key, d.label_ja,
       coalesce(p.confirm_status, 'unconfirmed') as confirm_status
from site s
cross join field_definition d
left join site_field_provenance p
       on p.site_id = s.site_id and p.field_key = d.field_key
where d.required = 'required'
  and coalesce(p.confirm_status, 'unconfirmed') <> 'confirmed';

-- 確定できるかどうかの判定
create or replace function site_can_confirm(p_site_id uuid)
returns table (ok boolean, reason text) language sql stable as $$
    select false, '未確認の必須項目: ' || string_agg(label_ja, '、')
    from v_site_unconfirmed_required where site_id = p_site_id
    having count(*) > 0
    union all
    select false, '該当有無が未確認の法令: ' || string_agg(c.law_name_ja, '、')
    from site_legal_restriction r
    join legal_restriction_catalog c using (law_code)
    where r.site_id = p_site_id and r.applies = 'unknown'
    having count(*) > 0
    union all
    select false, '日影規制の有無が未確認'
    from site_shadow_regulation
    where site_id = p_site_id and shadow_applies = 'unknown'
    union all
    select false, '道路に接する辺がない'
    where not exists (
        select 1 from site_edge
        where site_id = p_site_id and edge_kind = 'road'
    )
    union all
    select false, '道路辺に道路種別が未入力'
    where exists (
        select 1 from site_edge
        where site_id = p_site_id and edge_kind = 'road'
          and (road_type is null or road_type = 'unknown')
    )
$$;

-- ---------------------------------------------------------------------
-- MVE / 下流エンジン向けの出力
-- ---------------------------------------------------------------------

-- SiteInfo v0.1 互換の GeoJSON Feature
create or replace view v_site_geojson as
select s.site_id,
       jsonb_build_object(
           'type', 'Feature',
           'geometry', ST_AsGeoJSON(s.geom)::jsonb,
           'properties', jsonb_build_object(
               'site_id', s.site_id,
               'name', s.site_name,
               'address', s.address,
               'area_m2', s.area_effective_m2,
               'area_tsubo', round(s.area_effective_m2 / 3.30579, 1),
               'area_is_manual', s.area_basis = 'manual',
               'zone_id', z.zone_type,
               'zone', zc.label_ja,
               'far_percent', z.far_percent,
               'bcr_percent', z.bcr_percent,
               'road_width_m', (select max(road_width_m) from site_edge e
                                where e.site_id = s.site_id and e.edge_kind = 'road'),
               'walk_min', m.walk_min,
               'land_price_man_per_tsubo', m.land_price_man_per_tsubo,
               'district_plan', coalesce(z.district_plan, '指定なし'),
               'fire_zone', z.fire_zone,
               'height_zone', coalesce(z.height_district, '指定なし'),
               'shadow_regulation', sh.shadow_applies,
               'shadow_measurement_height_m', sh.measurement_height_m,
               'shadow_hours_5m', sh.hours_5m,
               'shadow_hours_10m', sh.hours_10m,
               'north_angle_deg', s.north_angle_deg,
               'plane_srid', s.plane_srid,
               'source', 'SiteInfo',
               'source_version', '0.2',
               'status', s.status,
               'generated_at', now()
           )
       ) as feature
from site s
left join site_zoning z on z.site_id = s.site_id
left join zone_type_catalog zc on zc.zone_type = z.zone_type
left join site_shadow_regulation sh on sh.site_id = s.site_id
left join site_market m on m.site_id = s.site_id;

-- MVE 用の平面座標（m）。反時計回りに正規化した外周。閉じるための終点は
-- 含めない（MVE 側の dedupe_ring と同じ扱い）。
create or replace function site_points_plane(p_site_id uuid)
returns table (seq int, x numeric, y numeric) language sql stable as $$
    select (dp).path[1] - 1 as seq,
           round(ST_X((dp).geom)::numeric, 3),
           round(ST_Y((dp).geom)::numeric, 3)
    from (
        select ST_DumpPoints(
                   ST_ExteriorRing(
                       ST_ForcePolygonCCW(
                           ST_Transform(ST_GeometryN(geom, 1), plane_srid)
                       )
                   )
               ) as dp,
               ST_NPoints(ST_ExteriorRing(ST_GeometryN(geom, 1))) as npts
        from site where site_id = p_site_id
    ) t
    where (dp).path[1] < npts   -- 閉じる終点を除く
    order by seq
$$;
