-- SiteInfo v0.2 カタログ初期データ（draft）
-- schema.sql を流したあとに実行する。
set search_path to siteinfo, public;

-- 用途地域（MVE zoning.zone_type と同じコード）
insert into zone_type_catalog (zone_type, label_ja, mve_code, shadow_target, sort_order) values
    ('1res',   '第一種低層住居専用地域',   '1res',   'eaves7m_or_3f', 1),
    ('2res',   '第二種低層住居専用地域',   '2res',   'eaves7m_or_3f', 2),
    ('rural',  '田園住居地域',             'rural',  'eaves7m_or_3f', 3),
    ('1mres',  '第一種中高層住居専用地域', '1mres',  'height10m', 4),
    ('2mres',  '第二種中高層住居専用地域', '2mres',  'height10m', 5),
    ('1hres',  '第一種住居地域',           '1hres',  'height10m', 6),
    ('2hres',  '第二種住居地域',           '2hres',  'height10m', 7),
    ('quasi_res', '準住居地域',            'quasi_res', 'height10m', 8),
    ('neighborhood', '近隣商業地域',       'neighborhood', 'height10m', 9),
    ('commercial', '商業地域',             'commercial', null, 10),
    ('quasi_ind', '準工業地域',            'quasi_ind', 'height10m', 11),
    ('industrial', '工業地域',             'industrial', null, 12),
    ('industrial_exclusive', '工業専用地域', 'industrial_exclusive', null, 13),
    ('none',   '用途地域の指定なし',       'none',   'height10m', 14)
on conflict (zone_type) do update
    set label_ja = excluded.label_ja, mve_code = excluded.mve_code,
        shadow_target = excluded.shadow_target, sort_order = excluded.sort_order;

-- 重要事項説明書「法令に基づく制限」の法令コード
insert into legal_restriction_catalog (law_code, law_name_ja, typical_zones, auto_fill, source_hint, sort_order) values
    ('national_land_use', '国土利用計画法', '届出の要否（規制区域・監視区域）', 'varies', '自治体', 10),
    ('agricultural_land', '農地法', '農地転用許可', 'varies', '農地台帳', 20),
    ('landslide_fill', '宅地造成及び特定盛土等規制法', '宅地造成等工事規制区域、特定盛土等規制区域、造成宅地防災区域', 'varies', '自治体 GIS', 30),
    ('sediment_disaster', '土砂災害防止法', '土砂災害警戒区域、特別警戒区域', 'established', 'ハザードマップポータル', 40),
    ('steep_slope', '急傾斜地の崩壊による災害の防止に関する法律', '急傾斜地崩壊危険区域', 'varies', '都道府県 GIS', 50),
    ('tsunami', '津波防災地域づくりに関する法律', '津波災害警戒区域、特別警戒区域', 'established', 'ハザードマップポータル', 60),
    ('flood_hazard', '水防法（水害ハザードマップ）', '浸水想定区域、想定浸水深', 'established', 'ハザードマップポータル', 70),
    ('river', '河川法', '河川区域、河川保全区域', 'varies', '都道府県 GIS', 80),
    ('port_coast', '港湾法・海岸法', '臨港地区、海岸保全区域', 'varies', '自治体', 90),
    ('landscape', '景観法', '景観計画区域、届出の要否', 'varies', '自治体', 100),
    ('cultural_property', '文化財保護法', '周知の埋蔵文化財包蔵地', 'varies', '自治体 GIS', 110),
    ('natural_park', '自然公園法', '特別地域、普通地域', 'varies', '環境省 GIS', 120),
    ('urban_green', '都市緑地法', '特別緑地保全地区、緑化地域', 'varies', '都市計画 GIS', 130),
    ('productive_green', '生産緑地法', '生産緑地地区', 'varies', '都市計画 GIS', 140),
    ('soil_contamination', '土壌汚染対策法', '要措置区域、形質変更時要届出区域', 'varies', '都道府県', 150),
    ('large_retail', '大規模小売店舗立地法', '届出の要否', 'none', null, 160),
    ('parking_ordinance', '駐車場法・附置義務条例', '附置義務の有無', 'none', null, 170),
    ('airport_height', '航空法', '高さ制限（制限表面）', 'varies', '空港周辺 GIS', 180),
    ('radio_propagation', '電波法', '伝搬障害防止区域', 'varies', '総務省', 190),
    ('other', 'その他', '自由記述', 'none', null, 900)
on conflict (law_code) do update
    set law_name_ja = excluded.law_name_ja, typical_zones = excluded.typical_zones,
        auto_fill = excluded.auto_fill, source_hint = excluded.source_hint,
        sort_order = excluded.sort_order;

-- 全国共通の GIS 取得元
insert into gis_source (name, provider, dataset, url, format, note) values
    ('国土地理院 住所検索', '国土地理院', 'AddressSearch', 'https://msearch.gsi.go.jp/address-search/AddressSearch', 'rest', '住所→座標'),
    ('国土地理院 逆ジオコーダ', '国土地理院', 'LonLatToAddress', 'https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress', 'rest', '座標→住所・市区町村コード'),
    ('国土交通省 不動産情報ライブラリ', '国土交通省', 'reinfolib external API', 'https://www.reinfolib.mlit.go.jp/ex-api/external/', 'rest', '用途地域、容積率、建蔽率、防火地域、高度地区、地区計画、地価、駅'),
    ('国土交通省 ハザードマップポータル', '国土交通省', '重ねるハザードマップ', 'https://disaportal.gsi.go.jp/', 'wms', '洪水、土砂災害、津波、高潮'),
    ('PLATEAU', '国土交通省', 'plateau-datasets', 'https://api.plateauview.mlit.go.jp/datacatalog/plateau-datasets', 'rest', '3D 都市モデル');

-- 必須項目の定義（項目定義書 ◎ の項目）。○・△ は追って追加する。
insert into field_definition (field_key, group_code, label_ja, data_type, unit, required, auto_fill, law_reference, sort_order) values
    ('address', 'A', '所在（住居表示）', 'text', null, 'required', 'established', '宅建業法35条', 110),
    ('lot_numbers', 'A', '地番', 'json', null, 'required', 'none', '登記', 120),
    ('municipality_code', 'A', '市区町村コード', 'text', null, 'required', 'established', 'JIS X 0402', 130),
    ('geom', 'B', '敷地ポリゴン', 'geom', null, 'required', 'varies', null, 210),
    ('shape_source', 'B', '形状の由来', 'enum', null, 'required', 'none', null, 220),
    ('plane_srid', 'B', '平面直角座標系', 'int', null, 'required', 'established', null, 230),
    ('north_angle_deg', 'B', '真北方位角', 'num', '度', 'required', 'established', null, 240),
    ('area_effective_m2', 'C', '採用面積', 'num', '㎡', 'required', 'varies', null, 310),
    ('area_basis', 'C', '採用面積の根拠', 'enum', null, 'required', 'none', null, 320),
    ('edges', 'D', '境界辺（種別・道路幅員・道路種別）', 'json', null, 'required', 'varies', '法42条・43条・52条2項', 410),
    ('area_division', 'E', '区域区分', 'enum', null, 'required', 'varies', '都市計画法7条', 510),
    ('zone_type', 'E', '用途地域', 'enum', null, 'required', 'established', '法48条・別表第二', 520),
    ('far_percent', 'E', '指定容積率', 'int', '%', 'required', 'established', '法52条1項', 530),
    ('bcr_percent', 'E', '指定建蔽率', 'int', '%', 'required', 'established', '法53条1項', 540),
    ('fire_zone', 'E', '防火・準防火地域', 'enum', null, 'required', 'established', '法61条', 550),
    ('height_district', 'E', '高度地区', 'text', null, 'required', 'established', '都市計画法9条', 560),
    ('district_plan', 'E', '地区計画', 'text', null, 'required', 'established', '都市計画法12条の4', 570),
    ('planned_road', 'E', '都市計画道路', 'json', null, 'required', 'varies', '都市計画法11条・53条', 580),
    ('slant_applies', 'F', '斜線制限の適用（道路・隣地・北側）', 'json', null, 'required', 'established', '法56条', 610),
    ('shadow_applies', 'G', '日影規制の有無', 'enum', null, 'required', 'varies', '法56条の2・別表第四', 710),
    ('shadow_values', 'G', '日影規制の測定面・規制時間', 'json', null, 'required', 'varies', '別表第四・自治体条例', 720),
    ('shadow_hokkaido', 'G', '北海道区分', 'bool', null, 'required', 'established', '法56条の2', 730),
    ('legal_restrictions', 'H', '法令に基づく制限（重要事項説明書）', 'json', null, 'required', 'varies', '宅建業法35条1項2号', 810),
    ('water_supply', 'I', '上水道', 'enum', null, 'required', 'none', '宅建業法35条1項4号', 910),
    ('sewerage', 'I', '下水道', 'enum', null, 'required', 'none', '宅建業法35条1項4号', 920),
    ('gas', 'I', 'ガス', 'enum', null, 'required', 'none', '宅建業法35条1項4号', 930)
on conflict (field_key) do update
    set group_code = excluded.group_code, label_ja = excluded.label_ja,
        data_type = excluded.data_type, unit = excluded.unit,
        required = excluded.required, auto_fill = excluded.auto_fill,
        law_reference = excluded.law_reference, sort_order = excluded.sort_order;
