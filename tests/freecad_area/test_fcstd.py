"""FreeCADを使わずに .FCStd から面積を読むテスト。

FreeCADはCIに入れられないので、FreeCADが書く `Document.xml` と同じ構造の
ファイルを組み立てて読ませています（実ファイルでの確認は
`docs/freecad_floor_area.md` の手順を参照）。
"""
import zipfile

import pytest

from freecad_area.fcstd import FcstdError, any_object_with_area, read_document, read_rooms
from freecad_area.rooms import is_space

from .fcstd_fixture import document_xml, space_xml, storey_xml, write_fcstd

@pytest.fixture()
def house(tmp_path):
    xml = document_xml(
        [
            space_xml("Space", "リビング", 16.56),
            space_xml("Space001", "キッチン", 8.28),
            space_xml("Space002", "主寝室", 13.24),
            storey_xml("Floor", "1階", ["Space", "Space001"]),
            storey_xml("Floor001", "2階", ["Space002"]),
        ],
        [
            ("Space", "Part::FeaturePython"),
            ("Space001", "Part::FeaturePython"),
            ("Space002", "Part::FeaturePython"),
            ("Floor", "App::DocumentObjectGroupPython"),
            ("Floor001", "App::DocumentObjectGroupPython"),
        ],
    )
    return write_fcstd(tmp_path / "住宅.FCStd", xml)


def test_reads_rooms_areas_and_levels(house):
    rooms = read_rooms(house)
    assert [(r.name, r.level) for r in rooms] == [
        ("リビング", "1階"), ("キッチン", "1階"), ("主寝室", "2階"),
    ]
    assert [r.floor_area_m2 for r in rooms] == pytest.approx([16.56, 8.28, 13.24])
    assert {r.source for r in rooms} == {"Area"}


def test_proxy_class_marks_the_object_as_a_space(house):
    doc = read_document(house)
    space = next(o for o in doc.Objects if o.Name == "Space")
    assert space.Proxy.Type == "Space"
    assert is_space(space)
    # 列挙型のIfcTypeは添字の整数でしか保存されないので、判定には使えない。
    assert space.IfcType == 7


def test_group_links_are_resolved_to_objects(house):
    doc = read_document(house)
    floor = next(o for o in doc.Objects if o.Name == "Floor")
    assert [child.Label for child in floor.Group] == ["リビング", "キッチン"]


def test_room_without_saved_area_has_no_area(tmp_path):
    path = write_fcstd(
        tmp_path / "面積なし.FCStd",
        document_xml([space_xml("Space", "物置", None)],
                      [("Space", "Part::FeaturePython")]),
    )
    rooms = read_rooms(path)
    assert rooms[0].floor_area_m2 is None


def test_all_areas_predicate_picks_up_non_space_objects(tmp_path):
    xml = document_xml(
        [space_xml("Slab", "スラブ", 20.0, proxy=False)],
        [("Slab", "Part::Feature")],
    )
    path = write_fcstd(tmp_path / "スラブ.FCStd", xml)
    assert read_rooms(path) == []
    rooms = read_rooms(path, predicate=any_object_with_area)
    assert rooms[0].floor_area_m2 == pytest.approx(20.0)


def test_missing_and_broken_files_raise_fcstd_error(tmp_path):
    with pytest.raises(FcstdError):
        read_document(str(tmp_path / "ない.FCStd"))

    not_a_zip = tmp_path / "壊れ.FCStd"
    not_a_zip.write_text("これはZIPではありません", encoding="utf-8")
    with pytest.raises(FcstdError):
        read_document(str(not_a_zip))

    empty_zip = tmp_path / "空.FCStd"
    with zipfile.ZipFile(empty_zip, "w") as archive:
        archive.writestr("readme.txt", "x")
    with pytest.raises(FcstdError, match="Document.xml"):
        read_document(str(empty_zip))
