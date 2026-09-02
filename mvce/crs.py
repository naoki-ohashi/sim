"""平面直角座標系（JGD2011）とエンジン内部のローカル系.

SIM WORLD は PLATEAU や自治体 GIS から敷地形状を受け取ります。その時点の
座標は **JGD2011 平面直角座標系**（第I〜XIX系、EPSG:6669〜6687）です。
このモジュールは、そこからエンジンが計算に使うローカル直交系への変換と、
**真北の決定**を担います。

## 気をつけることが2つあります

### 1. 平面直角座標系は X が北・Y が東

数学の慣習（x が東・y が北）と**軸が逆**です。EPSG の軸定義も
`Axis(name=Northing, abbrev=X) , Axis(name=Easting, abbrev=Y)` の順で、
測量成果もこの順で配布されます。エンジン側は図面と同じ「x が右（東）・
y が上（北）」で計算するので、取り込みの一点で必ず入れ替えます
（`CrsContext.to_local`）。入れ替え忘れは敷地が転置されるだけなので
面積は合ってしまい、斜線と日影だけが静かに狂います。

### 2. 座標北は真北ではない

平面直角座標系の +X（座標北）は、その系の**中央子午線に平行な向き**です。
真北（その地点の子午線の向き）とは一致しません。両者の差が
**子午線収差角**（meridian convergence）γ で、中央経線から東西に離れる
ほど大きくなります。日本の各系は中央経線から±1.5度ほどの幅を持つので、
系の端では 0.8〜0.9 度に達します。

北側斜線（法56条1項3号）と日影規制（法56条の2）はどちらも**真北**が
基準です。座標北のまま計算すると、系の端の敷地で系統的に誤ります。
1度のずれは、10m 先で 17cm、30m 先で 52cm の位置ずれに相当します。

γ の符号は「真北から座標北への時計回りの角度」です。したがって
`NorthReference.north_angle_deg`（真北が +Y からどれだけ反時計回りに
ずれているか）は、座標北を +Y に取ったローカル系では **+γ** に等しく
なります。この対応は `true_north_angle_deg()` が持ちます。

## 面積について

平面直角座標系は縮尺係数 k0 = 0.9999 の横メルカトル図法です。図上の距離は
中央経線上で実距離の 0.9999 倍、中央経線から 1.5 度離れると 1.0002 倍
程度になります。面積はその2乗なので、**最大で 0.042% 程度**（600 m² の
敷地で 0.25 m²）図上面積が実面積とずれます。

建築確認で使う敷地面積は登記・測量成果の値であってこの計算値ではないので、
MVCE は図上面積をそのまま使い、補正しません。必要なら
`point_scale_factor()` で倍率を取れます。

## 実装

投影計算は Krüger 級数（6次）です。純関数で、外部ライブラリに依存しません
（L1 は純関数であること、という基本設計 3.1 の制約）。正しさは
`tests/mvce/test_crs.py` が pyproj（EPSG データベース同梱）を独立実装
として突き合わせて担保します。pyproj は実行時には要りません。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .geometry import Point
from .sources import SourceRef

# --- GRS80 楕円体 -------------------------------------------------------
# 測量法施行令2条1項が定める日本の測地基準系（JGD2011）の準拠楕円体。
# 数値は EPSG:7019 (GRS 1980) と同一。
GRS80_SEMI_MAJOR_AXIS_M = 6378137.0
GRS80_INVERSE_FLATTENING = 298.257222101

_F = 1.0 / GRS80_INVERSE_FLATTENING
_E2 = _F * (2.0 - _F)
_E = math.sqrt(_E2)
_N = _F / (2.0 - _F)

# 子午線弧長の正規化半径 A（Krüger）
_A_RECTIFYING = (
    GRS80_SEMI_MAJOR_AXIS_M
    / (1.0 + _N)
    * (1.0 + _N ** 2 / 4 + _N ** 4 / 64 + _N ** 6 / 256)
)

# Krüger 級数の係数（6次まで）。順変換 α、逆変換 β。
_ALPHA = (
    0.0,
    _N / 2 - 2 * _N ** 2 / 3 + 5 * _N ** 3 / 16 + 41 * _N ** 4 / 180
    - 127 * _N ** 5 / 288 + 7891 * _N ** 6 / 37800,
    13 * _N ** 2 / 48 - 3 * _N ** 3 / 5 + 557 * _N ** 4 / 1440
    + 281 * _N ** 5 / 630 - 1983433 * _N ** 6 / 1935360,
    61 * _N ** 3 / 240 - 103 * _N ** 4 / 140 + 15061 * _N ** 5 / 26880
    + 167603 * _N ** 6 / 181440,
    49561 * _N ** 4 / 161280 - 179 * _N ** 5 / 168 + 6601661 * _N ** 6 / 7257600,
    34729 * _N ** 5 / 80640 - 3418889 * _N ** 6 / 1995840,
    212378941 * _N ** 6 / 319334400,
)
_BETA = (
    0.0,
    _N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96 - _N ** 4 / 360
    - 81 * _N ** 5 / 512 + 96199 * _N ** 6 / 604800,
    _N ** 2 / 48 + _N ** 3 / 15 - 437 * _N ** 4 / 1440 + 46 * _N ** 5 / 105
    - 1118711 * _N ** 6 / 3870720,
    17 * _N ** 3 / 480 - 37 * _N ** 4 / 840 - 209 * _N ** 5 / 4480
    + 5569 * _N ** 6 / 90720,
    4397 * _N ** 4 / 161280 - 11 * _N ** 5 / 504 - 830251 * _N ** 6 / 7257600,
    4583 * _N ** 5 / 161280 - 108847 * _N ** 6 / 3991680,
    20648693 * _N ** 6 / 638668800,
)

#: 平面直角座標系の縮尺係数。全19系で共通。
PLANE_SCALE_FACTOR = 0.9999

_EPSG_SOURCE = SourceRef(
    document="EPSG Geodetic Parameter Dataset（JGD2011 / Japan Plane Rectangular CS I–XIX）",
    confirmed_on="2026-08-29",
    url="https://epsg.org/",
    note="pyproj 3.7.2 同梱の EPSG データベースから原点緯経度・縮尺係数を取得して照合",
)


@dataclass(frozen=True)
class PlaneRectangularZone:
    """平面直角座標系の1つの系（第I系〜第XIX系）。"""

    number: int
    """系番号（1〜19）。"""

    epsg: int
    """JGD2011 の EPSG コード（6669〜6687）。"""

    origin_lat_deg: float
    """座標原点の緯度。"""

    origin_lon_deg: float
    """座標原点の経度（＝中央経線）。"""

    scale_factor: float = PLANE_SCALE_FACTOR
    source: SourceRef = _EPSG_SOURCE

    @property
    def roman(self) -> str:
        return _ROMAN[self.number - 1]

    @property
    def label(self) -> str:
        return f"第{self.roman}系（EPSG:{self.epsg}）"


_ROMAN = (
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX",
)

def _dm(degrees: int, minutes: int = 0) -> float:
    """度分表記を十進度へ。原点は度分で定義されているのでそのまま書く。"""
    return degrees + minutes / 60.0


# 原点の緯度・経度。出典は _EPSG_SOURCE、突合は tests/mvce/test_crs.py が
# pyproj 同梱の EPSG データベースに対して毎回行います。
#      系  EPSG  原点緯度      原点経度（＝中央経線）
_ZONE_TABLE = (
    (1, 6669, _dm(33), _dm(129, 30)),
    (2, 6670, _dm(33), _dm(131, 0)),
    (3, 6671, _dm(36), _dm(132, 10)),
    (4, 6672, _dm(33), _dm(133, 30)),
    (5, 6673, _dm(36), _dm(134, 20)),
    (6, 6674, _dm(36), _dm(136, 0)),
    (7, 6675, _dm(36), _dm(137, 10)),
    (8, 6676, _dm(36), _dm(138, 30)),
    (9, 6677, _dm(36), _dm(139, 50)),
    (10, 6678, _dm(40), _dm(140, 50)),
    (11, 6679, _dm(44), _dm(140, 15)),
    (12, 6680, _dm(44), _dm(142, 15)),
    (13, 6681, _dm(44), _dm(144, 15)),
    (14, 6682, _dm(26), _dm(142, 0)),
    (15, 6683, _dm(26), _dm(127, 30)),
    (16, 6684, _dm(26), _dm(124, 0)),
    (17, 6685, _dm(26), _dm(131, 0)),
    (18, 6686, _dm(20), _dm(136, 0)),
    (19, 6687, _dm(26), _dm(154, 0)),
)

ZONES: Dict[int, PlaneRectangularZone] = {
    epsg: PlaneRectangularZone(number=num, epsg=epsg,
                               origin_lat_deg=lat, origin_lon_deg=lon)
    for num, epsg, lat, lon in _ZONE_TABLE
}
"""EPSG コード → 系。JGD2011 の19系のみ。"""

ZONES_BY_NUMBER: Dict[int, PlaneRectangularZone] = {z.number: z for z in ZONES.values()}


class CrsError(ValueError):
    """座標系の指定が解決できないとき。"""


def zone_for_epsg(epsg: int) -> PlaneRectangularZone:
    """EPSG コードから系を引く。未知のコードは推測せずに落とす（原則H）。"""
    zone = ZONES.get(epsg)
    if zone is None:
        raise CrsError(
            f"EPSG:{epsg} は JGD2011 平面直角座標系（6669〜6687）ではありません。"
            f"別の測地系や UTM のデータは、取り込み前に平面直角座標系へ変換してください"
        )
    return zone


def zone_for_number(number: int) -> PlaneRectangularZone:
    """系番号（1〜19）から系を引く。"""
    zone = ZONES_BY_NUMBER.get(number)
    if zone is None:
        raise CrsError(f"平面直角座標系は第1系〜第19系です: {number}")
    return zone


# --- 投影計算（Krüger 級数・6次） ---------------------------------------

def _tau_prime(tau: float) -> float:
    """緯度の tan から、等角緯度の tan（τ'）へ。"""
    sigma = math.sinh(_E * math.atanh(_E * tau / math.hypot(1.0, tau)))
    return tau * math.hypot(1.0, sigma) - sigma * math.hypot(1.0, tau)


def _tau_from_prime(taup: float) -> float:
    """τ' から τ へ（`_tau_prime` の逆）。Newton 法で反復する。"""
    # 初期値は球面近似。日本の緯度帯なら3回で倍精度の限界に達する。
    tau = taup / (1.0 - _E2)
    for _ in range(8):
        current = _tau_prime(tau)
        residual = current - taup
        if abs(residual) < 1e-15 * max(1.0, abs(taup)):
            break
        derivative = (            # d(τ')/dτ
            (1.0 - _E2)
            * math.hypot(1.0, current)
            * math.hypot(1.0, tau)
            / (1.0 + (1.0 - _E2) * tau * tau)
        )
        tau -= residual / derivative
    return tau


def _series(xip: float, etap: float, coefficients: Tuple[float, ...], sign: float):
    """Krüger 級数の本体。ξ・η と、その微分（収差角・縮尺に使う）を返す。"""
    xi, eta = xip, etap
    p, q = 1.0, 0.0
    for j in range(1, 7):
        c = coefficients[j]
        xi += sign * c * math.sin(2 * j * xip) * math.cosh(2 * j * etap)
        eta += sign * c * math.cos(2 * j * xip) * math.sinh(2 * j * etap)
        p += sign * 2 * j * c * math.cos(2 * j * xip) * math.cosh(2 * j * etap)
        q += sign * 2 * j * c * math.sin(2 * j * xip) * math.sinh(2 * j * etap)
    return xi, eta, p, q


def _normalize_lon_diff(delta_deg: float) -> float:
    """経度差を [-180, 180) へ畳む。"""
    return (delta_deg + 180.0) % 360.0 - 180.0


_ORIGIN_XI_CACHE: Dict[float, float] = {}


def _meridian_xi(lat_deg: float) -> float:
    """中央経線上（Δλ=0）の ξ。原点緯度からの弧長を引くために使う。

    原点緯度は系ごとに固定なので結果を覚えておく。`project()` が呼ばれる
    たびに級数を回し直す必要はない。
    """
    cached = _ORIGIN_XI_CACHE.get(lat_deg)
    if cached is None:
        taup = _tau_prime(math.tan(math.radians(lat_deg)))
        cached, _, _, _ = _series(math.atan(taup), 0.0, _ALPHA, 1.0)
        _ORIGIN_XI_CACHE[lat_deg] = cached
    return cached


@dataclass(frozen=True)
class ProjectedPoint:
    """平面直角座標に落とした1点と、その点での座標北・縮尺。"""

    x_north_m: float
    """X 座標（北向き・原点から）。"""

    y_east_m: float
    """Y 座標（東向き・中央経線から）。"""

    convergence_deg: float
    """子午線収差角 γ（真北から座標北への時計回り角）。"""

    scale: float
    """点縮尺（図上距離 ÷ 実距離）。"""


def project(lat_deg: float, lon_deg: float, zone: PlaneRectangularZone) -> ProjectedPoint:
    """緯度経度（JGD2011）→ 平面直角座標。"""
    phi = math.radians(lat_deg)
    lam = math.radians(_normalize_lon_diff(lon_deg - zone.origin_lon_deg))
    tau = math.tan(phi)
    taup = _tau_prime(tau)
    cos_lam = math.cos(lam)
    xip = math.atan2(taup, cos_lam)
    etap = math.asinh(math.sin(lam) / math.hypot(taup, cos_lam))
    xi, eta, p, q = _series(xip, etap, _ALPHA, 1.0)

    k0a = zone.scale_factor * _A_RECTIFYING
    x_north = k0a * (xi - _meridian_xi(zone.origin_lat_deg))
    y_east = k0a * eta

    gamma = math.degrees(math.atan(taup / math.hypot(1.0, taup) * math.tan(lam)))
    gamma += math.degrees(math.atan2(q, p))

    r = math.hypot(math.sinh(etap), math.cos(xip))
    w = math.sqrt(1.0 - _E2 * math.sin(phi) ** 2)
    scale = zone.scale_factor * (_A_RECTIFYING / GRS80_SEMI_MAJOR_AXIS_M)
    scale *= w * math.hypot(1.0, tau) * r * math.hypot(p, q)

    return ProjectedPoint(x_north, y_east, gamma, scale)


def unproject(
    x_north_m: float, y_east_m: float, zone: PlaneRectangularZone
) -> Tuple[float, float]:
    """平面直角座標 → 緯度経度（JGD2011）。度で返す。"""
    k0a = zone.scale_factor * _A_RECTIFYING
    xi = x_north_m / k0a + _meridian_xi(zone.origin_lat_deg)
    eta = y_east_m / k0a
    xip, etap, _, _ = _series(xi, eta, _BETA, -1.0)

    sinh_etap = math.sinh(etap)
    cos_xip = math.cos(xip)
    taup = math.sin(xip) / math.hypot(sinh_etap, cos_xip)
    lat = math.degrees(math.atan(_tau_from_prime(taup)))
    lon = zone.origin_lon_deg + math.degrees(math.atan2(sinh_etap, cos_xip))
    return lat, lon


def meridian_convergence_deg(
    x_north_m: float, y_east_m: float, zone: PlaneRectangularZone
) -> float:
    """平面直角座標のある点での子午線収差角 γ（度）。

    正なら座標北が真北より東を向いています。中央経線上では 0、系の端では
    0.8〜0.9 度程度になります。
    """
    lat, lon = unproject(x_north_m, y_east_m, zone)
    return project(lat, lon, zone).convergence_deg


def point_scale_factor(
    x_north_m: float, y_east_m: float, zone: PlaneRectangularZone
) -> float:
    """平面直角座標のある点での点縮尺（図上距離 ÷ 実距離）。

    面積の倍率はこの2乗です。中央経線上で 0.9999、中央経線から 1.5 度
    離れると 1.0002 程度になります。
    """
    lat, lon = unproject(x_north_m, y_east_m, zone)
    return project(lat, lon, zone).scale


# --- エンジンが使う文脈 --------------------------------------------------

@dataclass(frozen=True)
class CrsContext:
    """敷地に付く座標系の文脈。

    エンジン内部の計算は、原点をずらしたローカル直交系（x が東・y が北・
    単位はメートル）で行います。平面直角座標のままだと座標値が数万〜数十万
    メートルになり、倍精度の有効桁を敷地の寸法ではなく原点までの距離に
    使ってしまうためです。
    """

    zone: PlaneRectangularZone
    origin_x_north_m: float
    """ローカル系の原点に対応する平面直角座標の X（北）。"""

    origin_y_east_m: float
    """ローカル系の原点に対応する平面直角座標の Y（東）。"""

    meridian_convergence_deg: float
    """ローカル原点での子午線収差角 γ。真北の決定に使う。"""

    scale: float = PLANE_SCALE_FACTOR
    """ローカル原点での点縮尺。面積の倍率はこの2乗。"""

    source: SourceRef = _EPSG_SOURCE
    notes: Tuple[str, ...] = ()

    # --- 生成 -----------------------------------------------------
    @classmethod
    def from_plane_points(
        cls,
        points_x_north_y_east,
        epsg: int,
        notes: Tuple[str, ...] = (),
    ) -> "CrsContext":
        """平面直角座標の点列（X=北, Y=東 の順）から文脈を作る。

        原点は与えられた点列の平均に取ります。子午線収差角と点縮尺も
        そこで評価します（基本設計 4.6「敷地重心で算出」）。敷地の大きさ
        （数十メートル）の範囲では収差角はほぼ一定なので、頂点の平均か
        多角形の重心かで結果は変わりません。
        """
        zone = zone_for_epsg(epsg)
        pts = [(float(x), float(y)) for x, y in points_x_north_y_east]
        if not pts:
            raise CrsError("点が1つもありません")
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        projected = project(*unproject(cx, cy, zone), zone=zone)
        return cls(
            zone=zone,
            origin_x_north_m=cx,
            origin_y_east_m=cy,
            meridian_convergence_deg=projected.convergence_deg,
            scale=projected.scale,
            notes=tuple(notes),
        )

    # --- 変換 -----------------------------------------------------
    def to_local(self, x_north_m: float, y_east_m: float) -> Point:
        """平面直角座標（X=北, Y=東）→ ローカル系（x=東, y=北）。

        **軸が入れ替わります。** 平面直角座標系は X が北・Y が東ですが、
        エンジンと図面は x が右（東）・y が上（北）です。
        """
        return (y_east_m - self.origin_y_east_m, x_north_m - self.origin_x_north_m)

    def to_plane(self, point: Point) -> Tuple[float, float]:
        """ローカル系（x=東, y=北）→ 平面直角座標（X=北, Y=東）。"""
        return (point[1] + self.origin_x_north_m, point[0] + self.origin_y_east_m)

    def ring_to_local(self, ring) -> list:
        """平面直角座標の点列をまとめてローカル系へ。"""
        return [self.to_local(x, y) for x, y in ring]

    # --- 真北 -----------------------------------------------------
    def true_north_angle_deg(self) -> float:
        """真北が ローカル系の +Y からどれだけ反時計回りにずれているか（度）。

        ローカル系の +Y は座標北なので、この値は子午線収差角そのものです。
        `NorthReference(north_angle_deg=...)` にそのまま渡せます。
        """
        return self.meridian_convergence_deg

    def area_scale(self) -> float:
        """図上面積 ÷ 実面積。0.9998〜1.0005 程度（中央経線からの距離しだい）。"""
        return self.scale * self.scale

    def describe(self) -> str:
        return (
            f"{self.zone.label} / 子午線収差角 {self.meridian_convergence_deg:+.4f}度 "
            f"/ 点縮尺 {self.scale:.7f}"
        )
