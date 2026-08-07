"""JWC data-exchange format (JW-CAD/JWW 外部変形 の JWC_TEMP.TXT) の読み書き.

JWWの[その他]-[外部変形]は、選択図形(または図面全体)を `JWC_TEMP.TXT` という
テキストファイルに書き出して外部プログラムを起動し、外部プログラムが同じ
形式で上書きしたファイルを読み戻して図面に反映する、という仕組みで動きます。

## この実装が前提としている書式

本モジュールは以下の理解に基づいて実装しています。**実機のJWWで検証できて
いません**（開発はLinuxサンドボックス上で行っており、JWW本体を実行できない
ため）。実際の書式と食い違う可能性があるため、必ず `jww/診断_データ確認.bat`
で実機の `JWC_TEMP.TXT` を採取し、`docs/jww_integration.md` の手順で
突き合わせてから本運用してください。

- 文字コードは Shift-JIS、改行は CRLF
- 座標は実寸の **mm**（本パッケージの計算はm単位なので `UNITS_PER_METER` で換算）
- `#` で始まる行はコメント/ヘッダ情報
- 属性は状態行として指定し、以降の図形行に適用される:
  `lg<n>`=レイヤグループ, `ly<n>`=レイヤ, `lc<n>`=線色(ペン), `lt<n>`=線種
- 図形行:
  - 線: 数値4個 `x1 y1 x2 y2`
  - 円/円弧: `ci cx cy r [開始角 終了角 ...]`
  - 文字: `ch x1 y1 x2 y2 文字列`
  - 点: `pt x y`
  - ソリッド: `sl x1 y1 x2 y2 x3 y3 x4 y4`

読み込み側は「知らない行は捨てずに `unknown` に退避する」寛容な作りにして
あります。実機の書式が違っていても、まず何が来ているかを確認できます。
"""
from __future__ import annotations

from dataclasses import dataclass, field

UNITS_PER_METER = 1000.0  # JWCの座標はmm実寸

DEFAULT_ENCODING = "shift_jis"


@dataclass
class JwcLineSeg:
    """1本の線分（属性つき）。座標はm単位に換算済み。"""

    x1: float
    y1: float
    x2: float
    y2: float
    layer_group: int = 0
    layer: int = 0
    color: int = 1
    line_type: int = 1

    @property
    def p1(self) -> tuple[float, float]:
        return (self.x1, self.y1)

    @property
    def p2(self) -> tuple[float, float]:
        return (self.x2, self.y2)

    @property
    def length(self) -> float:
        return ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5


@dataclass
class JwcDocument:
    """JWC_TEMP.TXTの読み取り結果。"""

    lines: list[JwcLineSeg] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def lines_by_color(self) -> dict[int, list[JwcLineSeg]]:
        out: dict[int, list[JwcLineSeg]] = {}
        for seg in self.lines:
            out.setdefault(seg.color, []).append(seg)
        return out


def _parse_state(token: str, prefix: str) -> int | None:
    if not token.startswith(prefix):
        return None
    rest = token[len(prefix):]
    try:
        return int(rest, 16) if len(rest) == 1 and not rest.isdigit() else int(rest)
    except ValueError:
        return None


def parse_jwc(text: str, units_per_meter: float = UNITS_PER_METER) -> JwcDocument:
    """JWC形式のテキストをパースして線分等を取り出す。

    数値4個だけの行を線分とみなします。状態行(lg/ly/lc/lt)は以降の図形に
    適用されます。解釈できなかった行は `unknown` に保存されるので、実機の
    書式確認に使えます。
    """
    doc = JwcDocument()
    state = {"lg": 0, "ly": 0, "lc": 1, "lt": 1}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            doc.header.append(line)
            continue

        parts = line.split()
        if len(parts) == 1:
            for prefix in state:
                value = _parse_state(parts[0], prefix)
                if value is not None:
                    state[prefix] = value
                    break
            else:
                doc.unknown.append(line)
            continue

        try:
            nums = [float(p) for p in parts]
        except ValueError:
            doc.unknown.append(line)
            continue

        if len(nums) == 4:
            doc.lines.append(
                JwcLineSeg(
                    x1=nums[0] / units_per_meter,
                    y1=nums[1] / units_per_meter,
                    x2=nums[2] / units_per_meter,
                    y2=nums[3] / units_per_meter,
                    layer_group=state["lg"],
                    layer=state["ly"],
                    color=state["lc"],
                    line_type=state["lt"],
                )
            )
        else:
            doc.unknown.append(line)

    return doc


def read_jwc_file(path: str, units_per_meter: float = UNITS_PER_METER) -> JwcDocument:
    with open(path, encoding=DEFAULT_ENCODING, errors="replace") as f:
        return parse_jwc(f.read(), units_per_meter)


class JwcWriter:
    """JWC形式を書き出すビルダ。属性は変化したときだけ状態行を出力します。"""

    def __init__(self, units_per_meter: float = UNITS_PER_METER) -> None:
        self.units_per_meter = units_per_meter
        self._out: list[str] = []
        self._lg: int | None = None
        self._ly: int | None = None
        self._lc: int | None = None
        self._lt: int | None = None

    def _u(self, v: float) -> str:
        return f"{v * self.units_per_meter:.2f}"

    def set_attributes(
        self,
        layer_group: int | None = None,
        layer: int | None = None,
        color: int | None = None,
        line_type: int | None = None,
    ) -> None:
        if layer_group is not None and layer_group != self._lg:
            self._out.append(f"lg{layer_group}")
            self._lg = layer_group
        if layer is not None and layer != self._ly:
            self._out.append(f"ly{layer}")
            self._ly = layer
        if color is not None and color != self._lc:
            self._out.append(f"lc{color}")
            self._lc = color
        if line_type is not None and line_type != self._lt:
            self._out.append(f"lt{line_type}")
            self._lt = line_type

    def add_line(self, p1: tuple[float, float], p2: tuple[float, float]) -> None:
        self._out.append(f"{self._u(p1[0])} {self._u(p1[1])} {self._u(p2[0])} {self._u(p2[1])}")

    def add_polyline(self, points: list[tuple[float, float]], close: bool = False) -> None:
        pts = list(points)
        if close and pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        for a, b in zip(pts, pts[1:]):
            self.add_line(a, b)

    def add_text(self, position: tuple[float, float], text: str, height_m: float = 0.5) -> None:
        """文字を追加。JWCの `ch` は始点と終点(=文字列の伸びる方向と大きさ)を
        取るため、文字高さから終点を算出しています。"""
        x, y = position
        width = height_m * 0.7 * max(1, len(text))
        self._out.append(
            f"ch {self._u(x)} {self._u(y)} {self._u(x + width)} {self._u(y)} {text}"
        )

    def add_comment(self, text: str) -> None:
        self._out.append(f"# {text}")

    def getvalue(self) -> str:
        return "\r\n".join(self._out) + "\r\n"

    def save(self, path: str) -> None:
        with open(path, "w", encoding=DEFAULT_ENCODING, errors="replace", newline="") as f:
            f.write(self.getvalue())
