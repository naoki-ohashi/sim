"""FreeCADを起動せずに `.FCStd` から部屋と床面積を読み出す。

`.FCStd` はZIPで、中の `Document.xml` に各オブジェクトのプロパティ値が
そのまま入っています。床面積（Arch Space の `Area`）も保存されるので、
FreeCADが無い環境（サーバ、CI、Pythonだけの端末）でも集計できます。

**限界**: 読めるのは保存時点で記録されている値だけです。形状（BREP）は
解析しないので、`Area` プロパティを持たないオブジェクトの床面積は
求められません。その場合はFreeCADの中でマクロ
（`freecad/床面積集計.FCMacro`）を実行してください。また、`Document.xml`
の書式はFreeCADのバージョンに依存します。手元のファイルで一度結果を
確認してから常用してください。
"""
from __future__ import annotations

import zipfile
from xml.etree import ElementTree

from .rooms import Room, collect_rooms

DOCUMENT_XML = "Document.xml"


class FcstdError(Exception):
    """`.FCStd` を読めなかった。"""


class _Proxy:
    """`obj.Proxy.Type` だけを真似た入れ物（`is_space` の判定に使います）。"""

    def __init__(self, type_name: str):
        self.Type = type_name


class FcstdObject:
    """`Document.xml` に保存されていたオブジェクト1件。

    FreeCADのオブジェクトと同じ名前の属性（`Name` / `Label` / `TypeId` /
    `Area` / `IfcType` / `Group` / `Proxy`）を持つので、`rooms` の関数を
    そのまま使えます。
    """

    def __init__(self, name: str, type_id: str, properties: dict):
        self.Name = name
        self.TypeId = type_id
        self._properties = properties
        self.Label = properties.get("Label") or name
        self.Group: list = []  # あとで解決します

        proxy = properties.get("Proxy")
        self.Proxy = None
        if isinstance(proxy, dict):
            class_name = str(proxy.get("class") or "").lstrip("_")
            module = str(proxy.get("module") or "")
            if class_name:
                self.Proxy = _Proxy(class_name)
            elif module.startswith("Arch"):
                self.Proxy = _Proxy(module[len("Arch"):])

    def __getattr__(self, item):
        # Area / IfcType など、保存されていたプロパティを属性として見せます。
        if item.startswith("_"):  # __init__ 前の再帰を避けます
            raise AttributeError(item)
        try:
            return self._properties[item]
        except KeyError:
            raise AttributeError(item) from None

    def __repr__(self) -> str:  # pragma: no cover - デバッグ用
        return f"<FcstdObject {self.Name} ({self.TypeId})>"


class FcstdDocument:
    """`collect_rooms` に渡せる、読み取り専用の文書。"""

    def __init__(self, objects: list):
        self.Objects = objects


def _property_value(prop: ElementTree.Element):
    """`<Property>` の中身をPythonの値にする。

    未知のタグでも `value` 属性があれば拾い、数値に見えれば数値にします。
    列挙型（`App::PropertyEnumeration`）は添字の整数しか保存されないので、
    文字列にはなりません。
    """
    for child in prop:
        tag = child.tag
        if tag == "LinkList":
            return [link.get("value") for link in child if link.get("value")]
        if tag == "Link":
            value = child.get("value")
            return [value] if value else []
        if tag == "Python":
            return {"module": child.get("module"), "class": child.get("class")}
        value = child.get("value")
        if value is None:
            continue
        if tag == "String":
            return value
        try:
            return float(value) if tag in ("Float", "Quantity") else int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value
    return None


def _parse_document_xml(data: bytes) -> FcstdDocument:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise FcstdError(f"Document.xmlを解析できませんでした: {exc}") from exc

    type_ids = {}
    for element in root.iter("Object"):
        name = element.get("name") or element.get("Name")
        type_id = element.get("type") or element.get("Type")
        if name and type_id:
            type_ids.setdefault(name, type_id)

    objects = []
    by_name = {}
    object_data = root.find("ObjectData")
    for element in (object_data if object_data is not None else []):
        name = element.get("name") or element.get("Name")
        if not name:
            continue
        properties = {}
        for prop in element.iter("Property"):
            prop_name = prop.get("name")
            if not prop_name:
                continue
            properties[prop_name] = _property_value(prop)
        obj = FcstdObject(name, type_ids.get(name, ""), properties)
        objects.append(obj)
        by_name[name] = obj

    # Group（リンク名の並び）を実体に置き換えます。
    for obj in objects:
        links = obj._properties.get("Group")
        if isinstance(links, list):
            obj.Group = [by_name[n] for n in links if n in by_name]

    return FcstdDocument(objects)


def read_document(path: str) -> FcstdDocument:
    """`.FCStd` を開いて、読み取り専用の文書として返す。"""
    try:
        with zipfile.ZipFile(path) as archive:
            data = archive.read(DOCUMENT_XML)
    except FileNotFoundError as exc:
        raise FcstdError(f"ファイルが見つかりません: {path}") from exc
    except KeyError as exc:
        raise FcstdError(
            f"{path} に {DOCUMENT_XML} がありません（FreeCADのファイルですか）。"
        ) from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise FcstdError(f"FCStdファイルを開けませんでした: {exc}") from exc
    return _parse_document_xml(data)


def read_rooms(path: str, *, predicate=None) -> list:
    """`.FCStd` から部屋の一覧（`Room`）を読み出す。"""
    return collect_rooms(read_document(path), predicate=predicate)


def any_object_with_area(obj) -> bool:
    """部屋の判定を緩める用の述語。面積を持つオブジェクトをすべて拾います。"""
    return getattr(obj, "Area", None) is not None


__all__ = [
    "FcstdDocument",
    "FcstdError",
    "FcstdObject",
    "Room",
    "any_object_with_area",
    "read_document",
    "read_rooms",
]
