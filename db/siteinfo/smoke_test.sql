-- SiteInfo v0.2 スキーマの動作確認
-- 使い方:
--   psql -d <db> -v ON_ERROR_STOP=1 -f schema.sql
--   psql -d <db> -v ON_ERROR_STOP=1 -f seed_catalog.sql
--   psql -d <db> -v ON_ERROR_STOP=1 -f smoke_test.sql
-- すべてロールバックするので、DB に痕跡は残らない。
set search_path to siteinfo, public;
begin;

-- sample_site.geojson（SiteInfo v0.1 の検証用A敷地）を投入
insert into site (site_id, site_name, address, municipality_code, lot_numbers,
                  geom, shape_source, plane_srid, north_angle_deg,
                  area_effective_m2, area_basis, created_by)
values ('00000000-0000-0000-0000-000000000001', '検証用A敷地',
        '東京都千代田区丸の内一丁目', '13101',
        '[{"lot": "1-1", "land_category": "宅地", "area_m2": 990}]',
        ST_SetSRID(ST_Multi(ST_GeomFromGeoJSON('{"type":"Polygon","coordinates":[[
            [139.766,35.681],[139.76649766505997,35.681],
            [139.76649766505997,35.6811976293625],[139.766,35.6811976293625],
            [139.766,35.681]]]}')), 6668),
        'geojson', 6677, 0, 990, 'manual', 'smoke');
-- 図形面積が採用面積（990㎡）と近いこと
do $$
declare a numeric;
begin
    select site_area_geom_m2(s) into a from site s
    where site_id = '00000000-0000-0000-0000-000000000001';
    raise notice '図形面積 = % ㎡', a;
    if a not between 950 and 1030 then
        raise exception '図形面積が想定外: %', a;
    end if;
end $$;

-- 履歴トリガ: 更新で version が上がり、旧行が site_history に残る
update site set site_name = '検証用A敷地（改）', updated_by = 'smoke'
where site_id = '00000000-0000-0000-0000-000000000001';
do $$
declare v int; h int;
begin
    select version into v from site where site_id = '00000000-0000-0000-0000-000000000001';
    select count(*) into h from site_history where site_id = '00000000-0000-0000-0000-000000000001';
    if v <> 2 or h <> 1 then
        raise exception '履歴トリガが動いていない: version=%, history=%', v, h;
    end if;
end $$;

-- 確定判定: 何も確認していないので確定不可
do $$
declare n int;
begin
    select count(*) into n from site_can_confirm('00000000-0000-0000-0000-000000000001');
    raise notice '確定を妨げる理由の数 = %', n;
    if n = 0 then raise exception '未入力なのに確定できてしまう'; end if;
end $$;

-- 用途地域・日影・法令・辺を入力
insert into site_zoning (site_id, area_division, zone_type, far_percent, bcr_percent,
                         fire_zone, height_district, district_plan,
                         road_slant_applies, adjacent_slant_applies, north_slant_applies)
values ('00000000-0000-0000-0000-000000000001', 'urbanization_promotion', 'commercial',
        500, 80, 'fire', null, null, true, true, false);

insert into site_shadow_regulation (site_id, shadow_applies, hokkaido)
values ('00000000-0000-0000-0000-000000000001', 'none', false);

-- 規制ありなのに時間が無い → 制約で弾かれること
do $$
begin
    update site_shadow_regulation set shadow_applies = 'regulated'
    where site_id = '00000000-0000-0000-0000-000000000001';
    raise exception '日影規制の必須値チェックが効いていない';
exception when check_violation then
    raise notice '日影規制の必須値チェック OK';
end $$;

-- 条例値（4h/2.5h, 測定面4m）を入れれば通ること
update site_shadow_regulation
   set shadow_applies = 'regulated', measurement_height_m = 4.0,
       hours_5m = 4, hours_10m = 2.5, target_criteria = 'height10m'
 where site_id = '00000000-0000-0000-0000-000000000001';

insert into site_legal_restriction (site_id, law_code, applies, detail)
select '00000000-0000-0000-0000-000000000001', law_code, 'no', null
from legal_restriction_catalog where active;
update site_legal_restriction
   set applies = 'yes', detail = '浸水想定 0.5m 未満'
 where site_id = '00000000-0000-0000-0000-000000000001' and law_code = 'flood_hazard';

insert into site_edge (site_id, edge_seq, edge_kind, road_width_m, road_type, is_private_road)
values ('00000000-0000-0000-0000-000000000001', 0, 'road', 12, 'art42_1_1', false),
       ('00000000-0000-0000-0000-000000000001', 1, 'adjacent', null, null, null),
       ('00000000-0000-0000-0000-000000000001', 2, 'adjacent', null, null, null),
       ('00000000-0000-0000-0000-000000000001', 3, 'adjacent', null, null, null);

-- 道路辺なのに幅員なし → 制約で弾かれること
do $$
begin
    insert into site_edge (site_id, edge_seq, edge_kind)
    values ('00000000-0000-0000-0000-000000000001', 9, 'road');
    raise exception '道路幅員の必須チェックが効いていない';
exception when check_violation then
    raise notice '道路幅員の必須チェック OK';
end $$;

insert into site_utility (site_id, water_supply, sewerage, gas)
values ('00000000-0000-0000-0000-000000000001', 'front_road', 'public', 'city_gas');
insert into site_market (site_id, walk_min, land_price_man_per_tsubo)
values ('00000000-0000-0000-0000-000000000001', 5, 320);

-- 自動入力値を provenance に記録（未確認）
insert into site_field_provenance (site_id, field_key, source_kind, gis_source_id, source_fetched_at, raw_value)
select '00000000-0000-0000-0000-000000000001', 'zone_type', 'auto', gis_source_id, now(), '"商業地域"'
from gis_source where name = '国土交通省 不動産情報ライブラリ';

-- 自動入力なのに取得元なし → 制約で弾かれること
do $$
begin
    insert into site_field_provenance (site_id, field_key, source_kind)
    values ('00000000-0000-0000-0000-000000000001', 'far_percent', 'auto');
    raise exception '自動入力の取得元必須チェックが効いていない';
exception when check_violation then
    raise notice '自動入力の取得元必須チェック OK';
end $$;

-- まだ未確認項目があるので確定不可
do $$
declare r record; n int := 0;
begin
    for r in select * from site_can_confirm('00000000-0000-0000-0000-000000000001') loop
        n := n + 1; raise notice '確定不可の理由: %', r.reason;
    end loop;
    if n = 0 then raise exception '未確認なのに確定できてしまう'; end if;
end $$;

-- すべての必須項目を確認済みにする
insert into site_field_provenance (site_id, field_key, source_kind, confirm_status, confirmed_by, confirmed_at)
select '00000000-0000-0000-0000-000000000001', field_key, 'manual', 'confirmed', 'smoke', now()
from field_definition where required = 'required'
on conflict (site_id, field_key) do update
    set confirm_status = 'confirmed', confirmed_by = 'smoke', confirmed_at = now();

do $$
declare n int;
begin
    select count(*) into n from site_can_confirm('00000000-0000-0000-0000-000000000001');
    if n <> 0 then raise exception 'すべて確認済みなのに確定できない'; end if;
    raise notice '確定判定 OK';
end $$;

-- GeoJSON 出力（v0.1 互換キー）
do $$
declare f jsonb;
begin
    select feature into f from v_site_geojson
    where site_id = '00000000-0000-0000-0000-000000000001';
    if f->'properties'->>'zone_id' <> 'commercial'
       or (f->'properties'->>'far_percent')::numeric <> 500
       or (f->'properties'->>'road_width_m')::numeric <> 12
       or f->'properties'->>'zone' <> '商業地域' then
        raise exception 'GeoJSON の properties が想定と違う: %', f->'properties';
    end if;
    raise notice 'GeoJSON OK: %', f->'properties';
end $$;

-- MVE 向け平面座標（反時計回り、閉じる終点を除いた 4 点）
do $$
declare n int; x0 numeric; y0 numeric;
begin
    select count(*) into n from site_points_plane('00000000-0000-0000-0000-000000000001');
    if n <> 4 then raise exception '平面座標の点数が想定外: %', n; end if;
    select x, y into x0, y0 from site_points_plane('00000000-0000-0000-0000-000000000001') where seq = 0;
    if x0 is null or y0 is null then raise exception '平面座標が NULL'; end if;
    raise notice '平面座標 先頭点 = (%, %)', x0, y0;
end $$;

-- 用途地域が 2 つにまたがる敷地: 西 60% が商業(500/80)、東 40% が第一種住居(300/60)
insert into site (site_id, site_name, geom, shape_source, plane_srid, created_by)
values ('00000000-0000-0000-0000-000000000002', '分割検証',
        ST_SetSRID(ST_Multi(ST_GeomFromText(
            'POLYGON((139.7660 35.6810,139.7670 35.6810,139.7670 35.6812,139.7660 35.6812,139.7660 35.6810))')), 6668),
        'polygon', 6677, 'smoke');
insert into site_zone_part (site_id, part_seq, zone_type, geom, far_percent, bcr_percent, trace_source)
values ('00000000-0000-0000-0000-000000000002', 0, 'commercial',
        ST_SetSRID(ST_Multi(ST_GeomFromText(
            'POLYGON((139.7660 35.6810,139.7666 35.6810,139.7666 35.6812,139.7660 35.6812,139.7660 35.6810))')), 6668),
        500, 80, 'map_trace'),
       ('00000000-0000-0000-0000-000000000002', 1, '1hres',
        ST_SetSRID(ST_Multi(ST_GeomFromText(
            'POLYGON((139.7666 35.6810,139.7670 35.6810,139.7670 35.6812,139.7666 35.6812,139.7666 35.6810))')), 6668),
        300, 60, 'map_trace');
do $$
declare r record;
begin
    select * into r from site_zoning_from_parts('00000000-0000-0000-0000-000000000002');
    raise notice '分割: 用途=% (%), 容積率=%, 建蔽率=%, 覆率=%',
        r.zone_type, r.zone_share, r.far_percent, r.bcr_percent, r.coverage;
    if r.zone_type <> 'commercial' then raise exception '過半の用途地域が違う: %', r.zone_type; end if;
    if r.zone_share not between 0.59 and 0.61 then raise exception '過半の割合が想定外: %', r.zone_share; end if;
    -- 0.6*500 + 0.4*300 = 420, 0.6*80 + 0.4*60 = 72
    if r.far_percent not between 419 and 421 then raise exception '容積率の按分が想定外: %', r.far_percent; end if;
    if r.bcr_percent not between 71.5 and 72.5 then raise exception '建蔽率の按分が想定外: %', r.bcr_percent; end if;
    if r.coverage not between 0.99 and 1.01 then raise exception '覆率が想定外: %', r.coverage; end if;
end $$;

-- 分割ありなのに site_zoning が導出値と違う → 確定不可の理由に出ること
insert into site_zoning (site_id, zone_type, zoning_split, far_percent, bcr_percent)
values ('00000000-0000-0000-0000-000000000002', '1hres', true, 300, 60);
do $$
declare n int;
begin
    select count(*) into n from site_can_confirm('00000000-0000-0000-0000-000000000002')
    where reason like '用途地域の分割と%';
    if n <> 1 then raise exception '分割と敷地の値の不一致が検出されない'; end if;
    raise notice '分割の不一致検出 OK';
end $$;
-- 導出値を反映すれば、その理由は消えること
update site_zoning z
   set zone_type = p.zone_type, far_percent = p.far_percent, bcr_percent = p.bcr_percent
  from site_zoning_from_parts('00000000-0000-0000-0000-000000000002') p
 where z.site_id = '00000000-0000-0000-0000-000000000002';
do $$
declare n int;
begin
    select count(*) into n from site_can_confirm('00000000-0000-0000-0000-000000000002')
    where reason like '用途地域の分割%';
    if n <> 0 then raise exception '導出値を反映したのに分割の理由が残る'; end if;
    raise notice '分割の整合 OK';
end $$;
-- GeoJSON に分割情報が出ること
do $$
declare f jsonb;
begin
    select feature into f from v_site_geojson where site_id = '00000000-0000-0000-0000-000000000002';
    if (f->'properties'->>'zoning_split')::boolean is not true
       or jsonb_array_length(f->'properties'->'zone_parts') <> 2 then
        raise exception 'GeoJSON の分割情報が想定外: %', f->'properties';
    end if;
    raise notice 'GeoJSON 分割情報 OK';
end $$;

rollback;
