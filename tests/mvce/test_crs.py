"""平面直角座標系・子午線収差角の検証（基本設計 4.6・Phase 1）。

`mvce/crs.py` の投影計算は純 Python の Krüger 級数です。正しさは
**独立実装との突合**で担保します。ここでは pyproj（EPSG データベースと
PROJ の投影実装を同梱）を使います。pyproj は実行時には不要で、
入っていない環境ではその検証だけをスキップします。

この考え方は逆日影・逆天空率の自己検算（不変条件 M-8）と同じです。
"""
import math
import warnings

import pytest

from mvce.crs import (
    GRS80_INVERSE_FLATTENING,
    GRS80_SEMI_MAJOR_AXIS_M,
    PLANE_SCALE_FACTOR,
    ZONES,
    CrsContext,
    CrsError,
    meridian_convergence_deg,
    point_scale_factor,
    project,
    unproject,
    zone_for_epsg,
    zone_for_number,
)
from mvce.north import NORTH_DISAGREEMENT_TOLERANCE_DEG, NorthReference, resolve_north

try:  # pyproj はテスト専用の照合用。無くてもこのファイルは走る。
    import pyproj as _pyproj
except ImportError:  # pragma: no cover - CI では入っている
    _pyproj = None

needs_pyproj = pytest.mark.skipif(_pyproj is None, reason="pyproj（照合用）が無い")

# 全19系から最低1点。第IX系は中央経線の近くと東西の端も入れてある。
# (EPSG, 緯度, 経度)
SAMPLES = [
    (6669, 32.75, 129.87),    # I  長崎
    (6670, 33.60, 130.40),    # II 福岡
    (6671, 34.40, 132.46),    # III 広島
    (6672, 33.84, 132.77),    # IV 松山
    (6673, 34.66, 133.92),    # V  岡山
    (6674, 35.01, 135.77),    # VI 京都
    (6675, 35.17, 136.91),    # VII 名古屋
    (6676, 37.90, 139.02),    # VIII 新潟
    (6677, 35.6812, 139.7671),  # IX 東京
    (6677, 35.90, 140.55),    # IX 系の東端寄り（収差角が大きい）
    (6677, 34.90, 138.95),    # IX 系の西端寄り
    (6678, 38.27, 140.87),    # X  仙台
    (6679, 41.77, 140.73),    # XI 函館
    (6680, 43.06, 141.35),    # XII 札幌
    (6681, 42.98, 144.38),    # XIII 釧路
    (6682, 27.09, 142.19),    # XIV 小笠原
    (6683, 26.21, 127.68),    # XV 那覇
    (6684, 24.34, 124.16),    # XVI 石垣
    (6685, 25.83, 131.23),    # XVII 南大東島
    (6686, 20.42, 136.08),    # XVIII 沖ノ鳥島
    (6687, 24.28, 153.98),    # XIX 南鳥島
]


# --- 系の定義 ------------------------------------------------------------

def test_all_nineteen_zones_are_registered():
    assert len(ZONES) == 19
    assert sorted(ZONES) == list(range(6669, 6688))
    assert [z.number for z in ZONES.values()] == list(range(1, 20))


def test_every_zone_carries_a_source():
    """原則F: 外部由来の数値には出典を付ける。"""
    for zone in ZONES.values():
        assert zone.source.document
        assert zone.source.confirmed_on


def test_scale_factor_is_the_same_for_every_zone():
    assert all(z.scale_factor == PLANE_SCALE_FACTOR for z in ZONES.values())


def test_unknown_epsg_is_rejected_not_guessed():
    """原則H: 知らない座標系を既定値で処理しない。"""
    with pytest.raises(CrsError):
        zone_for_epsg(4326)      # WGS84 緯度経度
    with pytest.raises(CrsError):
        zone_for_epsg(6668)      # JGD2011 地理座標
    with pytest.raises(CrsError):
        zone_for_number(20)


def test_zone_lookup_by_number_matches_epsg():
    assert zone_for_number(9).epsg == 6677
    assert zone_for_epsg(6677).roman == "IX"


@needs_pyproj
@pytest.mark.parametrize("epsg", sorted(ZONES))
def test_zone_parameters_match_the_epsg_database(epsg):
    """原点緯経度・縮尺係数・楕円体を EPSG データベースと突き合わせる。"""
    zone = ZONES[epsg]
    with warnings.catch_warnings():
        # to_dict() は「PROJ 文字列に落とすと情報が落ちる」と毎回警告する。
        # ここで見るのは lat_0 / lon_0 / k という PROJ 文字列に残る値だけ。
        warnings.simplefilter("ignore", UserWarning)
        params = _pyproj.CRS.from_epsg(epsg).to_dict()
    assert params["proj"] == "tmerc"
    assert params["ellps"] == "GRS80"
    assert params["lat_0"] == pytest.approx(zone.origin_lat_deg, abs=1e-9)
    assert params["lon_0"] == pytest.approx(zone.origin_lon_deg, abs=1e-9)
    assert params["k"] == pytest.approx(zone.scale_factor, abs=1e-12)
    assert params["x_0"] == 0 and params["y_0"] == 0


@needs_pyproj
def test_ellipsoid_matches_grs80():
    ellipsoid = _pyproj.CRS.from_epsg(6677).ellipsoid
    assert ellipsoid.semi_major_metre == pytest.approx(GRS80_SEMI_MAJOR_AXIS_M, abs=1e-9)
    assert ellipsoid.inverse_flattening == pytest.approx(
        GRS80_INVERSE_FLATTENING, abs=1e-9
    )


# --- 投影計算 ------------------------------------------------------------

@needs_pyproj
@pytest.mark.parametrize("epsg,lat,lon", SAMPLES)
def test_projection_matches_pyproj_to_a_micrometre(epsg, lat, lon):
    zone = ZONES[epsg]
    got = project(lat, lon, zone)
    # pyproj は平面直角座標系の軸順（X=北, Y=東）で返す
    north, east = _pyproj.Transformer.from_crs("EPSG:6668", f"EPSG:{epsg}").transform(
        lat, lon
    )
    assert got.x_north_m == pytest.approx(north, abs=1e-6)
    assert got.y_east_m == pytest.approx(east, abs=1e-6)


@needs_pyproj
@pytest.mark.parametrize("epsg,lat,lon", SAMPLES)
def test_convergence_matches_pyproj(epsg, lat, lon):
    zone = ZONES[epsg]
    expected = _pyproj.Proj(f"EPSG:{epsg}").get_factors(lon, lat).meridian_convergence
    assert project(lat, lon, zone).convergence_deg == pytest.approx(expected, abs=1e-7)


@needs_pyproj
@pytest.mark.parametrize("epsg,lat,lon", SAMPLES)
def test_point_scale_matches_pyproj(epsg, lat, lon):
    zone = ZONES[epsg]
    expected = _pyproj.Proj(f"EPSG:{epsg}").get_factors(lon, lat).meridional_scale
    assert project(lat, lon, zone).scale == pytest.approx(expected, abs=1e-10)


@pytest.mark.parametrize("epsg,lat,lon", SAMPLES)
def test_round_trip_is_sub_millimetre(epsg, lat, lon):
    """順変換 → 逆変換 で元の緯度経度に戻る。pyproj が無くても走る自己検算。"""
    zone = ZONES[epsg]
    p = project(lat, lon, zone)
    back_lat, back_lon = unproject(p.x_north_m, p.y_east_m, zone)
    # 緯度1度 ≒ 111km。1e-9 度 ≒ 0.1mm。
    assert back_lat == pytest.approx(lat, abs=1e-9)
    assert back_lon == pytest.approx(lon, abs=1e-9)


def test_origin_projects_to_zero():
    for zone in ZONES.values():
        p = project(zone.origin_lat_deg, zone.origin_lon_deg, zone)
        assert p.x_north_m == pytest.approx(0.0, abs=1e-6)
        assert p.y_east_m == pytest.approx(0.0, abs=1e-6)
        assert p.convergence_deg == pytest.approx(0.0, abs=1e-12)
        assert p.scale == pytest.approx(PLANE_SCALE_FACTOR, abs=1e-12)


# --- 子午線収差角の意味 ---------------------------------------------------

def test_convergence_is_zero_on_the_central_meridian():
    zone = ZONES[6677]
    assert project(35.0, zone.origin_lon_deg, zone).convergence_deg == \
        pytest.approx(0.0, abs=1e-12)


def test_convergence_is_positive_east_of_the_central_meridian():
    """東にずれると座標北は真北より東を向く（γ > 0）。"""
    zone = ZONES[6677]
    east = project(35.0, zone.origin_lon_deg + 1.0, zone).convergence_deg
    west = project(35.0, zone.origin_lon_deg - 1.0, zone).convergence_deg
    assert east > 0 > west
    assert east == pytest.approx(-west, abs=1e-9)   # 中央経線に対して対称


def test_convergence_is_close_to_the_textbook_first_order_term():
    """γ ≒ Δλ・sinφ。1次近似と 0.001 度以内で一致する。"""
    zone = ZONES[6677]
    lat, dlon = 35.0, 1.2
    got = project(lat, zone.origin_lon_deg + dlon, zone).convergence_deg
    assert got == pytest.approx(dlon * math.sin(math.radians(lat)), abs=1e-3)


def test_convergence_reaches_roughly_one_degree_at_the_zone_edge():
    """系の端では 0.8 度を超える。無視できない大きさであることの確認。"""
    zone = ZONES[6680]        # 第XII系（北海道・緯度が高いので収差角も大きい）
    got = project(44.0, zone.origin_lon_deg + 1.2, zone).convergence_deg
    assert 0.8 < got < 0.9


def test_grid_north_versus_true_north_is_measured_geometrically():
    """収差角の符号と大きさを、投影の幾何そのものから確かめる。

    同じ経度で緯度だけ上げた点は、地球上では**真北**へ動きます。その動きを
    平面直角座標で見たときの向きが座標北からどれだけ傾いているかが、
    符号込みの子午線収差角です。式の出どころに依存しない検証になります。
    """
    zone = ZONES[6677]
    lat, lon = 35.5, zone.origin_lon_deg + 1.0
    p0 = project(lat, lon, zone)
    p1 = project(lat + 0.001, lon, zone)          # 真北へ約111m
    # ローカル系（x=東, y=北）での真北ベクトル
    dx_east = p1.y_east_m - p0.y_east_m
    dy_north = p1.x_north_m - p0.x_north_m
    # +Y（座標北）から反時計回りに測った角度
    angle = math.degrees(math.atan2(-dx_east, dy_north))
    assert angle == pytest.approx(p0.convergence_deg, abs=1e-4)


# --- ローカル系への変換 ---------------------------------------------------

def _tokyo_context():
    zone = ZONES[6677]
    ring = [
        project(35.6810, 139.7660, zone),
        project(35.6810, 139.7666, zone),
        project(35.6814, 139.7666, zone),
        project(35.6814, 139.7660, zone),
    ]
    plane = [(p.x_north_m, p.y_east_m) for p in ring]
    return CrsContext.from_plane_points(plane, 6677), plane


def test_to_local_swaps_the_axes():
    """平面直角座標は X が北・Y が東。ローカル系は x が東・y が北。"""
    ctx, _ = _tokyo_context()
    x0, y0 = ctx.origin_x_north_m, ctx.origin_y_east_m
    # 北へ10m
    assert ctx.to_local(x0 + 10.0, y0) == pytest.approx((0.0, 10.0))
    # 東へ10m
    assert ctx.to_local(x0, y0 + 10.0) == pytest.approx((10.0, 0.0))


def test_local_round_trip():
    ctx, plane = _tokyo_context()
    for x_north, y_east in plane:
        back = ctx.to_plane(ctx.to_local(x_north, y_east))
        assert back[0] == pytest.approx(x_north, abs=1e-9)
        assert back[1] == pytest.approx(y_east, abs=1e-9)


def test_local_coordinates_are_small():
    """倍精度の有効桁を原点までの距離に食わせないための原点オフセット。"""
    ctx, plane = _tokyo_context()
    local = ctx.ring_to_local(plane)
    assert max(abs(v) for point in local for v in point) < 100.0
    assert max(abs(v) for point in plane for v in point) > 1000.0


def test_context_requires_at_least_one_point():
    with pytest.raises(CrsError):
        CrsContext.from_plane_points([], 6677)


def test_area_scale_stays_within_half_a_thousandth():
    """縮尺係数による図上面積のずれの大きさを固定する。

    各系は中央経線から±1.5度ほどの幅を持ちます。その範囲で図上面積は
    実面積の 0.9998〜1.0005 倍。600 m² の敷地なら最大 0.25 m² で、
    建築確認で使う敷地面積（登記・測量成果の値）とは別物なので補正は
    しません。値が想定より大きく振れたら投影計算を疑う、という趣旨の
    テストです。
    """
    for zone in ZONES.values():
        for dlon in (-1.5, 0.0, 1.5):
            for dlat in (-1.5, 0.0, 1.5):
                p = project(zone.origin_lat_deg + dlat, zone.origin_lon_deg + dlon, zone)
                ctx = CrsContext.from_plane_points([(p.x_north_m, p.y_east_m)], zone.epsg)
                assert 0.9998 < ctx.area_scale() < 1.0005


def test_convergence_helpers_agree_with_project():
    zone = ZONES[6677]
    p = project(35.9, 140.55, zone)
    assert meridian_convergence_deg(p.x_north_m, p.y_east_m, zone) == \
        pytest.approx(p.convergence_deg, abs=1e-9)
    assert point_scale_factor(p.x_north_m, p.y_east_m, zone) == \
        pytest.approx(p.scale, abs=1e-12)


# --- 真北の決定 ------------------------------------------------------------

def test_true_north_angle_equals_the_convergence():
    ctx, _ = _tokyo_context()
    assert ctx.true_north_angle_deg() == ctx.meridian_convergence_deg


def test_resolve_north_from_crs_alone():
    ctx, _ = _tokyo_context()
    north, notes = resolve_north(ctx)
    assert north.north_angle_deg == pytest.approx(ctx.meridian_convergence_deg)
    assert any("子午線収差角" in n for n in notes)


def test_resolve_north_prefers_the_manual_value_and_reports_the_gap():
    ctx, _ = _tokyo_context()
    north, notes = resolve_north(ctx, manual_north_angle_deg=-3.5)
    assert north.north_angle_deg == -3.5
    assert any("手入力値" in n for n in notes)
    assert any("差は" in n for n in notes)


def test_resolve_north_warns_when_the_two_disagree():
    ctx, _ = _tokyo_context()
    off_by = ctx.meridian_convergence_deg + NORTH_DISAGREEMENT_TOLERANCE_DEG + 0.5
    _, notes = resolve_north(ctx, manual_north_angle_deg=off_by)
    assert any("系番号が違う可能性" in n for n in notes)


def test_resolve_north_does_not_warn_within_tolerance():
    ctx, _ = _tokyo_context()
    close = ctx.meridian_convergence_deg + NORTH_DISAGREEMENT_TOLERANCE_DEG / 2
    _, notes = resolve_north(ctx, manual_north_angle_deg=close)
    assert not any("系番号が違う可能性" in n for n in notes)


def test_resolve_north_says_so_when_it_is_assuming():
    """原則H: 既定値を黙って使わない。"""
    north, notes = resolve_north()
    assert north.north_angle_deg == 0.0
    assert any("仮定" in n for n in notes)


def test_resolve_north_manual_only():
    north, notes = resolve_north(manual_north_angle_deg=-15.0)
    assert north.north_angle_deg == -15.0
    assert notes and "手入力値" in notes[0]


def test_north_reference_still_measures_azimuth_the_same_way():
    """既存の方位角の定義は変えていない（parity テストが依存している）。"""
    north = NorthReference(0.0)
    assert north.azimuth_of_vector((0.0, 1.0)) == pytest.approx(0.0)
    assert north.azimuth_of_vector((1.0, 0.0)) == pytest.approx(90.0)


def test_site_carries_the_crs_context():
    """Site が座標系の文脈を持ち運べる（基本設計 4.1）。"""
    from mvce.site import Site
    from mvce.zoning import ZoningParams

    ctx, plane = _tokyo_context()
    local = ctx.ring_to_local(plane)
    site = Site.from_rings(
        local,
        [{"kind": "road", "road_width_m": 6.0}] + [{"kind": "adjacent"}] * 3,
        zoning=ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6),
        north=resolve_north(ctx)[0],
        crs=ctx,
    )
    assert site.crs is ctx
    assert site.area_m2 > 0
    assert site.north.north_angle_deg == pytest.approx(ctx.meridian_convergence_deg)


def test_site_without_a_crs_is_unchanged():
    """手描き図面から起こした敷地は crs=None のまま。既存の入力を壊さない。"""
    from mvce.site import Site
    from mvce.zoning import ZoningParams

    site = Site.from_rings(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 30.0), (0.0, 30.0)],
        [{"kind": "road", "road_width_m": 6.0}] + [{"kind": "adjacent"}] * 3,
        zoning=ZoningParams(zone_type="1res", far_ratio=2.0, coverage_ratio=0.6),
    )
    assert site.crs is None
    assert site.area_m2 == pytest.approx(600.0)
