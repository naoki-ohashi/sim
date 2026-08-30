"""FreeCADのオブジェクトから部屋（床面積）を取り出す。

FreeCADの内部長さ単位はmmなので、面積は㎟で扱い、出力の直前に
1,000,000で割って㎡にします。

**床面積に `Shape.Area` を使ってはいけません。** `Shape.Area` は立体の
全表面積（床＋天井＋壁）なので、単純な直方体の部屋でも床面積の数倍に
なります。Arch Space は水平投影の床面積を `Area` プロパティに持っている
ので、まずそれを使い、無い場合だけ形状の最下面から求めます。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

MM2_PER_M2 = 1_000_000.0

#: `IfcType` / `IfcRole` がこの値なら部屋とみなす。
SPACE_IFC_TYPES = frozenset({"space", "ifcspace"})

#: FreeCADが自動で付ける内部名（Space, Space001 ...）。
_SPACE_NAME_RE = re.compile(r"^Space\d*$")

#: 面が水平かどうかの判定（法線のZ成分の許容誤差）。
_HORIZONTAL_TOL = 1e-3
#: 最下面かどうかの判定（mm）。
_Z_TOL = 1e-3


@dataclass(frozen=True)
class Room:
    """1部屋分の集計結果。

    `floor_area_m2` が None のものは面積を決められなかった部屋です
    （`Area` プロパティが無く、形状からも水平な最下面が取れなかった場合）。
    """

    name: str
    floor_area_m2: Optional[float] = None
    level: str = ""
    source: str = ""  # "Area"（プロパティ）または "Shape"（形状から算出）


def _text(value) -> str:
    """列挙型プロパティ等、文字列とは限らない値を文字列にする。"""
    if isinstance(value, str):
        return value
    return ""


def is_space(obj) -> bool:
    """オブジェクトがArchの部屋（Space）かどうか。

    FreeCADのバージョンによって手がかりが違うので、次のいずれかに
    当てはまれば部屋とみなします。

    * `IfcType` / `IfcRole` が "Space"（FreeCAD 0.19以降）
    * Pythonプロキシのクラスが `_Space`（`obj.Proxy.Type == "Space"`）
    * `TypeId` に "Space" を含む
    * 内部名が `Space` / `Space001` … で、かつ面積プロパティを持つ

    Arch Space の `TypeId` は `Part::FeaturePython` なので、`TypeId` だけを
    見る判定（元スクリプトの `"Space" in obj.TypeId`）では1件も拾えません。
    """
    for attr in ("IfcType", "IfcRole"):
        if _text(getattr(obj, attr, None)).replace(" ", "").lower() in SPACE_IFC_TYPES:
            return True

    proxy = getattr(obj, "Proxy", None)
    if _text(getattr(proxy, "Type", None)).lower() == "space":
        return True

    if "space" in _text(getattr(obj, "TypeId", None)).lower():
        return True

    name = _text(getattr(obj, "Name", None))
    if _SPACE_NAME_RE.match(name) and getattr(obj, "Area", None) is not None:
        return True

    return False


def _quantity_mm2(value) -> Optional[float]:
    """`App::PropertyArea`（Quantity）でも素の数値でも㎟の値を取り出す。"""
    if value is None:
        return None
    raw = getattr(value, "Value", value)
    try:
        area = float(raw)
    except (TypeError, ValueError):
        return None
    if area != area:  # NaN
        return None
    return area


def _face_normal_z(face) -> Optional[float]:
    """平面の法線のZ成分。取れなければ None。"""
    for getter in (
        lambda: face.normalAt(0, 0),
        lambda: face.Surface.Axis,
    ):
        try:
            normal = getter()
        except Exception:  # noqa: BLE001 - FreeCAD側の例外は種類が多い
            continue
        z = getattr(normal, "z", None)
        if z is None:
            continue
        try:
            length = float(getattr(normal, "Length", 1.0)) or 1.0
            return float(z) / length
        except (TypeError, ValueError):
            continue
    return None


def floor_area_from_shape(shape) -> Optional[float]:
    """形状の最下部にある水平面の面積の合計（㎟）。

    `Area` プロパティを持たない立体（Arch以外のソリッドなど）の床面積を
    求めるための予備手段です。底が水平な立体を想定しています。
    L字型でも底面が複数の面に分かれていれば合算します。斜めの床や、
    底面が水平でない立体では None を返します。
    """
    faces = getattr(shape, "Faces", None)
    bbox = getattr(shape, "BoundBox", None)
    if not faces or bbox is None:
        return None

    z_min = float(bbox.ZMin)
    total = 0.0
    for face in faces:
        normal_z = _face_normal_z(face)
        if normal_z is None or abs(abs(normal_z) - 1.0) > _HORIZONTAL_TOL:
            continue  # 水平面以外（壁など）は床ではない
        face_bbox = getattr(face, "BoundBox", None)
        if face_bbox is None or abs(float(face_bbox.ZMin) - z_min) > _Z_TOL:
            continue  # 天井など、最下部以外の水平面は数えない
        total += float(face.Area)

    return total if total > 0.0 else None


def room_area_mm2(obj) -> tuple[Optional[float], str]:
    """オブジェクトの床面積（㎟）と、その取得元を返す。"""
    area = _quantity_mm2(getattr(obj, "Area", None))
    if area is not None and area > 0.0:
        return area, "Area"

    shape = getattr(obj, "Shape", None)
    if shape is not None:
        area = floor_area_from_shape(shape)
        if area is not None:
            return area, "Shape"

    return None, ""


def _parent_labels(objects) -> dict:
    """内部名 → それを直接含むグループのラベル（＝階）の対応表。

    Arch では階（BuildingPart）が `Group` に部屋を持つので、部屋を含む
    グループのラベルをそのまま「階」として扱います。建物（Building）が
    部屋を直接持っている場合は建物名が入ります。
    """
    parents: dict = {}
    for obj in objects:
        group = getattr(obj, "Group", None)
        if not group:
            continue
        label = _text(getattr(obj, "Label", None)) or _text(getattr(obj, "Name", None))
        for child in group:
            key = _text(getattr(child, "Name", None)) or _text(child)
            if key and key not in parents:
                parents[key] = label
    return parents


def collect_rooms(doc, *, predicate=None) -> list:
    """文書中の部屋を文書順に集めて `Room` のリストにする。

    `doc` は FreeCAD の Document（`.Objects` を持つもの）です。
    `predicate` を渡すと部屋の判定を差し替えられます。
    """
    check = predicate or is_space
    objects = list(getattr(doc, "Objects", ()) or ())
    levels = _parent_labels(objects)

    rooms = []
    for obj in objects:
        if not check(obj):
            continue
        area_mm2, source = room_area_mm2(obj)
        name = _text(getattr(obj, "Label", None)) or _text(getattr(obj, "Name", None))
        rooms.append(
            Room(
                name=name,
                floor_area_m2=None if area_mm2 is None else area_mm2 / MM2_PER_M2,
                level=levels.get(_text(getattr(obj, "Name", None)), ""),
                source=source,
            )
        )
    return rooms


def total_area_m2(rooms: Iterable[Room]) -> float:
    """床面積の合計（㎡）。面積不明の部屋は除きます。"""
    return sum(r.floor_area_m2 for r in rooms if r.floor_area_m2 is not None)
