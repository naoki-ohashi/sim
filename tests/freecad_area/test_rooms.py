"""部屋の判定と床面積の取り出しのテスト。"""
import pytest

from freecad_area.rooms import (
    MM2_PER_M2,
    Room,
    collect_rooms,
    floor_area_from_shape,
    is_space,
    room_area_mm2,
    total_area_m2,
)

from .fakes import Doc, Face, Obj, Proxy, Quantity, Shape, Vector, box_shape


# === 部屋かどうかの判定 ================================================

def test_arch_space_is_detected_by_ifc_type():
    assert is_space(Obj("Space", "リビング", IfcType="Space"))
    assert is_space(Obj("Space001", "寝室", IfcRole="Space"))


def test_arch_space_is_detected_by_proxy_and_name():
    assert is_space(Obj("Space002", "台所", Proxy=Proxy("Space")))
    # プロキシも IfcType も無い場合は、内部名＋面積プロパティで拾います。
    assert is_space(Obj("Space003", "納戸", Area=1000.0))
    assert not is_space(Obj("Space004", "面積なし"))


def test_type_id_alone_does_not_match_arch_space():
    """元のスクリプトの `"Space" in obj.TypeId` では1件も拾えないことの確認。"""
    space = Obj("Space", "リビング", type_id="Part::FeaturePython", IfcType="Space")
    assert "Space" not in space.TypeId
    assert is_space(space)


def test_other_objects_are_not_rooms():
    assert not is_space(Obj("Wall", "壁", IfcType="Wall"))
    assert not is_space(Obj("Box", "直方体", type_id="Part::Box"))
    # 列挙型は数値でしか保存されないことがあるので、数値は無視します。
    assert not is_space(Obj("Wall001", "壁", IfcType=3))


# === 床面積 ============================================================

def test_floor_area_uses_bottom_horizontal_faces_not_total_surface():
    shape = box_shape(4000.0, 3000.0, 2400.0)  # 4m x 3m x 2.4m
    assert floor_area_from_shape(shape) == pytest.approx(12.0 * MM2_PER_M2)
    # `Shape.Area`（全表面積）は床面積の3倍近くある。
    assert shape.Area > 3 * floor_area_from_shape(shape)


def test_floor_area_sums_split_bottom_faces():
    """L字型など、底面が複数の面に分かれていても合算する。"""
    down = Vector(0, 0, -1)
    shape = Shape([Face(6.0 * MM2_PER_M2, down, 0.0),
                   Face(4.0 * MM2_PER_M2, down, 0.0),
                   Face(10.0 * MM2_PER_M2, Vector(0, 0, 1), 2400.0)])
    assert floor_area_from_shape(shape) == pytest.approx(10.0 * MM2_PER_M2)


def test_floor_area_ignores_horizontal_faces_above_the_bottom():
    down, up = Vector(0, 0, -1), Vector(0, 0, 1)
    shape = Shape([Face(5.0 * MM2_PER_M2, down, 0.0),
                   Face(5.0 * MM2_PER_M2, down, 3000.0),  # 中2階の床
                   Face(5.0 * MM2_PER_M2, up, 6000.0)])
    assert floor_area_from_shape(shape) == pytest.approx(5.0 * MM2_PER_M2)


def test_floor_area_returns_none_without_horizontal_bottom():
    shape = Shape([Face(3.0 * MM2_PER_M2, Vector(0, 0.7071, 0.7071), 0.0)])
    assert floor_area_from_shape(shape) is None


def test_area_property_wins_over_shape():
    obj = Obj("Space", "リビング", IfcType="Space",
              Area=Quantity(12.5 * MM2_PER_M2), Shape=box_shape(1000.0, 1000.0, 2400.0))
    area, source = room_area_mm2(obj)
    assert area == pytest.approx(12.5 * MM2_PER_M2)
    assert source == "Area"


def test_shape_is_used_when_area_property_is_missing():
    obj = Obj("Space", "物置", IfcType="Space", Shape=box_shape(2000.0, 1500.0, 2400.0))
    area, source = room_area_mm2(obj)
    assert area == pytest.approx(3.0 * MM2_PER_M2)
    assert source == "Shape"


def test_unknown_area_is_reported_as_none():
    assert room_area_mm2(Obj("Space", "不明", IfcType="Space")) == (None, "")


# === 文書全体の集計 ====================================================

def _space(name, label, area_m2, **kwargs):
    return Obj(name, label, IfcType="Space", Area=Quantity(area_m2 * MM2_PER_M2), **kwargs)


def test_collect_rooms_keeps_document_order_and_converts_to_m2():
    doc = Doc([
        _space("Space", "リビング", 16.56),
        Obj("Wall", "外壁", IfcType="Wall"),
        _space("Space001", "キッチン", 8.28),
    ])
    rooms = collect_rooms(doc)
    assert [r.name for r in rooms] == ["リビング", "キッチン"]
    assert rooms[0].floor_area_m2 == pytest.approx(16.56)
    assert total_area_m2(rooms) == pytest.approx(24.84)


def test_collect_rooms_picks_up_the_floor_from_the_group():
    first = _space("Space", "リビング", 16.0)
    second = _space("Space001", "主寝室", 13.0)
    doc = Doc([
        Obj("Floor", "1階", IfcType="Building Storey", Group=[first]),
        Obj("Floor001", "2階", IfcType="Building Storey", Group=[second]),
        first,
        second,
    ])
    rooms = collect_rooms(doc)
    assert [(r.name, r.level) for r in rooms] == [("リビング", "1階"), ("主寝室", "2階")]


def test_collect_rooms_accepts_a_custom_predicate():
    doc = Doc([Obj("Box", "土間", Area=Quantity(5.0 * MM2_PER_M2))])
    assert collect_rooms(doc) == []
    rooms = collect_rooms(doc, predicate=lambda o: getattr(o, "Area", None) is not None)
    assert rooms == [Room("土間", 5.0, "", "Area")]
