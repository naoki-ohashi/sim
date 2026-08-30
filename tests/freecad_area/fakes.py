"""FreeCADのオブジェクトを真似た、テスト用のダミー。

FreeCAD本体はCIに入れられないので、`freecad_area` が実際に触る属性
（Label / Area / Shape / Group / IfcType / Proxy）だけを再現しています。
"""


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    @property
    def Length(self):
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5


class BoundBox:
    def __init__(self, z_min=0.0, z_max=0.0):
        self.ZMin, self.ZMax = z_min, z_max


class Face:
    """平面。`normal` は単位ベクトル、`z` は面の高さ(mm)。"""

    def __init__(self, area, normal, z=0.0):
        self.Area = area
        self._normal = normal
        self.BoundBox = BoundBox(z, z)

    def normalAt(self, u, v):  # noqa: N802 - FreeCADのAPI名に合わせています
        return self._normal


class Shape:
    def __init__(self, faces, z_min=0.0):
        self.Faces = faces
        self.BoundBox = BoundBox(z_min, z_min + 1.0)

    @property
    def Area(self):
        """FreeCADの `Shape.Area` と同じく、全表面積（床面積ではない）。"""
        return sum(f.Area for f in self.Faces)


def box_shape(width_mm, depth_mm, height_mm, z_min=0.0):
    """直方体の形状（床・天井・壁4面）。"""
    up, down = Vector(0, 0, 1), Vector(0, 0, -1)
    faces = [
        Face(width_mm * depth_mm, down, z_min),
        Face(width_mm * depth_mm, up, z_min + height_mm),
        Face(width_mm * height_mm, Vector(0, -1, 0), z_min),
        Face(width_mm * height_mm, Vector(0, 1, 0), z_min),
        Face(depth_mm * height_mm, Vector(-1, 0, 0), z_min),
        Face(depth_mm * height_mm, Vector(1, 0, 0), z_min),
    ]
    return Shape(faces, z_min)


class Quantity:
    """`App::PropertyArea` のように `.Value`（㎟）を持つ値。"""

    def __init__(self, value):
        self.Value = value


class Proxy:
    def __init__(self, type_name):
        self.Type = type_name


class Obj:
    def __init__(self, name, label=None, type_id="Part::FeaturePython", **kwargs):
        self.Name = name
        self.Label = label if label is not None else name
        self.TypeId = type_id
        for key, value in kwargs.items():
            setattr(self, key, value)


class Doc:
    def __init__(self, objects):
        self.Objects = list(objects)
