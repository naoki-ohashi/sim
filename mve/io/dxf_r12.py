"""JW-CAD向けの最小構成 DXF R12 ライター（外部ライブラリを使わない）.

ezdxf が書く R12 は AutoCAD 互換としては正しいのですが、JW-CAD のDXF読込は
さらに古い前提で作られており、次の点が引っかかる可能性があります。

| ezdxf の R12 | ここで書く形 |
|---|---|
| 線種名 `Continuous` / 文字スタイル名 `Standard` | **大文字** `CONTINUOUS` / `STANDARD` |
| ハンドル（グループコード5）が付く | **付けない**（R12では省略可） |
| VIEW/UCS/APPID/DIMSTYLE/VPORT テーブルが入る | **LTYPE/LAYER/STYLE だけ** |

扱うのは **LINE と TEXT だけ**です。JW-CADが確実に解釈できる要素に絞って
います。座標はm単位で受け取り、mmに直して書きます（`dxf_pen.py` と同じ）。

**実機のJW-CADで表示を確認済みです（2026-08）。** ezdxf が書くR12は、上の
表の左側の状態になるため同じ図面でも表示されませんでした。切り分けには
`tools/make_jww_test_dxf.py` を使い、線のみ→文字→レイヤ4枚→レイヤ19枚の
順に試して、いずれも表示されることを確認しています。

`JwwDrawing`（ezdxf版）と同じ使い方ができるよう、メソッド名を揃えてあります。
どちらで書き出しても図面の内容は同じです。
"""
from __future__ import annotations

import pathlib
from typing import Iterable, Sequence

Point = tuple[float, float]

#: JWWはmmで作図するので、mの座標を1000倍して渡す
JWW_UNITS_PER_METER = 1000.0

#: 日本語をJWWで読めるようにするための文字コード
DXF_ENCODING = "cp932"

#: JW-CADのレイヤは1グループ16枚。これを超えないよう呼び出し側で調整する。
JWW_MAX_LAYERS = 16


def _pair(code: int, value) -> str:
    """DXFは「グループコード → 値」を1行ずつ並べた形式。"""
    return f"{code:>3}\n{value}\n"


def _num(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0.0"


class R12Drawing:
    """m単位で受け取り、JW-CAD向けの最小構成 DXF R12 として書き出す。"""

    def __init__(self, units_per_meter: float = JWW_UNITS_PER_METER) -> None:
        if units_per_meter <= 0:
            raise ValueError("units_per_meter は正の数にしてください")
        self.units_per_meter = float(units_per_meter)
        self._layers: dict[str, int] = {}
        self._entities: list[str] = []
        self._min = [float("inf"), float("inf")]
        self._max = [float("-inf"), float("-inf")]

    # -- レイヤ ---------------------------------------------------------
    def add_layer(self, name: str, color: int = 7) -> None:
        self._layers.setdefault(self._layer_name(name), color)

    @staticmethod
    def _layer_name(name: str) -> str:
        """R12のレイヤ名は大文字・31文字以内・限られた文字だけ。"""
        cleaned = "".join(c if (c.isalnum() or c in "$-_") else "_" for c in name.upper())
        return cleaned[:31] or "0"

    @property
    def layer_count(self) -> int:
        return len(self._layers)

    # -- 座標 -----------------------------------------------------------
    def _xy(self, p: Sequence[float]) -> Point:
        x = p[0] * self.units_per_meter
        y = p[1] * self.units_per_meter
        self._min[0] = min(self._min[0], x)
        self._min[1] = min(self._min[1], y)
        self._max[0] = max(self._max[0], x)
        self._max[1] = max(self._max[1], y)
        return (x, y)

    # -- 図形 -----------------------------------------------------------
    def line(self, p1: Sequence[float], p2: Sequence[float], layer: str,
             color: int = 7) -> None:
        name = self._layer_name(layer)
        self.add_layer(name, color)
        (x1, y1), (x2, y2) = self._xy(p1), self._xy(p2)
        self._entities.append(
            _pair(0, "LINE") + _pair(8, name) + _pair(62, color)
            + _pair(10, _num(x1)) + _pair(20, _num(y1)) + _pair(30, "0.0")
            + _pair(11, _num(x2)) + _pair(21, _num(y2)) + _pair(31, "0.0")
        )

    def polyline(self, points: Iterable[Sequence[float]], layer: str,
                 color: int = 7, close: bool = True) -> None:
        """折れ線を1本ずつのLINEとして書く（LWPOLYLINEはJWWが読めない）。"""
        pts = list(points)
        if len(pts) < 2:
            return
        for a, b in zip(pts, pts[1:]):
            self.line(a, b, layer, color)
        if close and tuple(pts[0]) != tuple(pts[-1]):
            self.line(pts[-1], pts[0], layer, color)

    def text(self, value: str, at: Sequence[float], height_m: float, layer: str,
             color: int = 7) -> None:
        name = self._layer_name(layer)
        self.add_layer(name, color)
        x, y = self._xy(at)
        # 改行やDXFを壊す文字は落とす
        safe = value.replace("\n", " ").replace("\r", " ")
        self._entities.append(
            _pair(0, "TEXT") + _pair(8, name) + _pair(62, color)
            + _pair(10, _num(x)) + _pair(20, _num(y)) + _pair(30, "0.0")
            + _pair(40, _num(max(height_m, 1e-6) * self.units_per_meter))
            + _pair(1, safe) + _pair(7, "STANDARD")
        )

    # -- 組み立て -------------------------------------------------------
    def _header(self) -> str:
        lo = self._min if self._min[0] != float("inf") else [0.0, 0.0]
        hi = self._max if self._max[0] != float("-inf") else [0.0, 0.0]
        return (
            _pair(0, "SECTION") + _pair(2, "HEADER")
            + _pair(9, "$ACADVER") + _pair(1, "AC1009")
            + _pair(9, "$DWGCODEPAGE") + _pair(3, "ANSI_932")
            + _pair(9, "$INSBASE")
            + _pair(10, "0.0") + _pair(20, "0.0") + _pair(30, "0.0")
            + _pair(9, "$EXTMIN")
            + _pair(10, _num(lo[0])) + _pair(20, _num(lo[1])) + _pair(30, "0.0")
            + _pair(9, "$EXTMAX")
            + _pair(10, _num(hi[0])) + _pair(20, _num(hi[1])) + _pair(30, "0.0")
            + _pair(0, "ENDSEC")
        )

    def _tables(self) -> str:
        layers = self._layers or {"0": 7}
        out = _pair(0, "SECTION") + _pair(2, "TABLES")

        # 線種：実線ひとつだけ
        out += (_pair(0, "TABLE") + _pair(2, "LTYPE") + _pair(70, 1)
                + _pair(0, "LTYPE") + _pair(2, "CONTINUOUS") + _pair(70, 64)
                + _pair(3, "Solid line") + _pair(72, 65) + _pair(73, 0)
                + _pair(40, "0.0")
                + _pair(0, "ENDTAB"))

        # レイヤ：レイヤ0は必ず要る
        names = dict(layers)
        names.setdefault("0", 7)
        out += _pair(0, "TABLE") + _pair(2, "LAYER") + _pair(70, len(names))
        for name, color in names.items():
            out += (_pair(0, "LAYER") + _pair(2, name) + _pair(70, 0)
                    + _pair(62, color) + _pair(6, "CONTINUOUS"))
        out += _pair(0, "ENDTAB")

        # 文字スタイル：標準ひとつだけ
        out += (_pair(0, "TABLE") + _pair(2, "STYLE") + _pair(70, 1)
                + _pair(0, "STYLE") + _pair(2, "STANDARD") + _pair(70, 0)
                + _pair(40, "0.0") + _pair(41, "1.0") + _pair(50, "0.0")
                + _pair(71, 0) + _pair(42, "2.5")
                + _pair(3, "txt") + _pair(4, "")
                + _pair(0, "ENDTAB"))

        return out + _pair(0, "ENDSEC")

    def to_text(self) -> str:
        return (self._header() + self._tables()
                + _pair(0, "SECTION") + _pair(2, "ENTITIES")
                + "".join(self._entities) + _pair(0, "ENDSEC")
                + _pair(0, "EOF"))

    # -- 保存 -----------------------------------------------------------
    def save(self, path: str) -> None:
        target = pathlib.Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        # JW-CADはCRLF・Shift-JISを前提にしている。読めない文字は落とす。
        data = self.to_text().replace("\n", "\r\n").encode(DXF_ENCODING, errors="replace")
        target.write_bytes(data)
