"""FreeCADが書く `Document.xml` と同じ構造のファイルを組み立てるヘルパー。

FreeCAD本体はCIに入れられないので、テストではここで作った .FCStd を
読ませています（実ファイルでの確認手順は `docs/freecad_floor_area.md`）。
"""
import zipfile

from freecad_area.rooms import MM2_PER_M2

SPACE_PROXY = (
    '<Property name="Proxy" type="App::PropertyPythonObject">'
    '<Python value="gAJ9cQAu" encoded="yes" module="ArchSpace" class="_Space"/>'
    "</Property>"
)


def space_xml(name, label, area_m2, proxy=True):
    area = "" if area_m2 is None else (
        '<Property name="Area" type="App::PropertyArea" status="1">'
        '<Float value="{:.1f}"/></Property>'.format(area_m2 * MM2_PER_M2)
    )
    return (
        '<Object name="{name}"><Properties Count="3">'
        '<Property name="Label" type="App::PropertyString">'
        '<String value="{label}"/></Property>'
        '<Property name="IfcType" type="App::PropertyEnumeration">'
        '<Integer value="7"/></Property>'
        "{area}{proxy}</Properties></Object>"
    ).format(name=name, label=label, area=area, proxy=SPACE_PROXY if proxy else "")


def storey_xml(name, label, children):
    links = "".join('<Link value="{}"/>'.format(c) for c in children)
    return (
        '<Object name="{name}"><Properties Count="2">'
        '<Property name="Label" type="App::PropertyString">'
        '<String value="{label}"/></Property>'
        '<Property name="Group" type="App::PropertyLinkList">'
        '<LinkList count="{n}">{links}</LinkList></Property>'
        "</Properties></Object>"
    ).format(name=name, label=label, n=len(children), links=links)


def document_xml(objects, types):
    declared = "".join(
        '<Object type="{}" name="{}" />'.format(type_id, name) for name, type_id in types
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Document SchemaVersion="4" ProgramVersion="1.0" FileVersion="1">'
        '<Objects Count="{n}">{declared}</Objects>'
        '<ObjectData Count="{n}">{data}</ObjectData>'
        "</Document>"
    ).format(n=len(types), declared=declared, data="".join(objects))


def write_fcstd(path, xml):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Document.xml", xml)
        archive.writestr("GuiDocument.xml", "<Document/>")
    return str(path)


