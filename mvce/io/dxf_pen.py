"""JW-CAD（JWW）が確実に読めるDXFを書くための最小限のペン.

JWWのDXF読込は古い仕様しか受け付けません。次の3点を守らないと、読み込みは
成功したように見えるのに**図面に何も表示されません**。

1. **バージョンは R12（AC1009）**
   R2000以降（AC1015〜）はJWWが解釈できないことがあります。

2. **図形は LINE と TEXT だけを使う**
   `LWPOLYLINE` はR14以降で追加された要素で、JWWは読み飛ばします。
   閉じた図形も、辺を1本ずつ LINE として書き出します。

3. **座標はmmで書く**
   JWWはmmで作図します。mのまま（敷地30m→30単位）渡すと1/1000の
   大きさになり、画面上は点にもならず「表示されない」ように見えます。

日本語の文字は Shift-JIS（`$DWGCODEPAGE=ANSI_932`）で書きます。既定の
cp1252のままだと `\\U+XXXX` というエスケープで出力され、JWWでは文字化けします。
"""
from __future__ import annotations

import contextlib
import logging
import pathlib
from typing import Iterable, Sequence

import ezdxf
from ezdxf import zoom

Point = tuple[float, float]

#: JWWはmmで作図するので、mの座標を1000倍して渡す
JWW_UNITS_PER_METER = 1000.0

#: JWWが読めるDXFのバージョン
DXF_VERSION = "R12"

#: 日本語をJWWで読めるようにするための文字コード
DXF_ENCODING = "cp932"


@contextlib.contextmanager
def _quiet_ezdxf():
    """R12では単位($INSUNITS)を書けない、という警告を画面に出さない。

    こちらは意図してR12を選んでいるので、利用者には無関係な警告です。
    """
    logger = logging.getLogger("ezdxf")
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)


class JwwDrawing:
    """m単位で受け取り、JWWが読めるDXFとして書き出す。

    呼び出し側は今までどおりm単位の座標を渡します。mm変換・LINEへの分解・
    文字コードの面倒はこのクラスが引き受けます。
    """

    def __init__(self, units_per_meter: float = JWW_UNITS_PER_METER) -> None:
        if units_per_meter <= 0:
            raise ValueError("units_per_meter は正の数にしてください")
        self.units_per_meter = float(units_per_meter)
        with _quiet_ezdxf():
            self.doc = ezdxf.new(DXF_VERSION, setup=False)
        self.doc.encoding = DXF_ENCODING
        self.msp = self.doc.modelspace()

    # -- レイヤ ---------------------------------------------------------
    def add_layer(self, name: str, color: int = 7) -> None:
        if name not in self.doc.layers:
            self.doc.layers.add(name, color=color)

    # -- 座標 -----------------------------------------------------------
    def _xy(self, p: Sequence[float]) -> Point:
        return (p[0] * self.units_per_meter, p[1] * self.units_per_meter)

    # -- 図形 -----------------------------------------------------------
    def line(self, p1: Sequence[float], p2: Sequence[float], layer: str,
             color: int = 7) -> None:
        self.msp.add_line(self._xy(p1), self._xy(p2),
                          dxfattribs={"layer": layer, "color": color})

    def polyline(self, points: Iterable[Sequence[float]], layer: str,
                 color: int = 7, close: bool = True) -> None:
        """折れ線を1本ずつのLINEとして書く（LWPOLYLINEはJWWが読めない）。"""
        pts = list(points)
        if len(pts) < 2:
            return
        for a, b in zip(pts, pts[1:]):
            self.line(a, b, layer, color)
        if close and pts[0] != pts[-1]:
            self.line(pts[-1], pts[0], layer, color)

    def text(self, value: str, at: Sequence[float], height_m: float, layer: str,
             color: int = 7) -> None:
        """文字を書く。`height_m` はm単位の文字高さ。"""
        self.msp.add_text(
            value, height=max(height_m, 1e-6) * self.units_per_meter,
            dxfattribs={"layer": layer, "color": color},
        ).set_placement(self._xy(at))

    # -- 保存 -----------------------------------------------------------
    def save(self, path: str) -> None:
        # 開いたときに図面全体が見えるよう、表示範囲を図形に合わせる
        zoom.extents(self.msp, factor=1.05)
        ensure_parent_dir(path)
        self.doc.saveas(path, encoding=DXF_ENCODING)


def ensure_parent_dir(path: str) -> None:
    """出力先のフォルダが無ければ作る。

    設定ファイルに `C:\\Users\\...\\Desktop\\敷地検討.dxf` のような絶対パスを
    書いたとき、途中のフォルダが無いだけで例外になるのを防ぎます。
    """
    parent = pathlib.Path(path).expanduser().parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
