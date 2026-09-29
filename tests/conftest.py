from __future__ import annotations

import os
import sys
from types import ModuleType

# -- Stub clr (IronPython / Dynamo host API, not available in CPython pytest) --
_clr = ModuleType("clr")
_clr.AddReference = lambda name: None  # type: ignore[attr-defined]
sys.modules["clr"] = _clr


# -- Stub Autodesk.AutoCAD.Geometry types used by geometry.py --
class Point3d:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.X = float(x)
        self.Y = float(y)
        self.Z = float(z)

    def __repr__(self) -> str:
        return f"Point3d({self.X}, {self.Y}, {self.Z})"


class Vector3d:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.X = float(x)
        self.Y = float(y)
        self.Z = float(z)


class Plane:
    def __init__(
        self, origin: Point3d | None = None, normal: Vector3d | None = None
    ) -> None:
        self.origin = origin
        self.normal = normal


_geom = ModuleType("Autodesk.AutoCAD.Geometry")
_geom.Point3d = Point3d  # type: ignore[attr-defined]
_geom.Vector3d = Vector3d  # type: ignore[attr-defined]
_geom.Plane = Plane  # type: ignore[attr-defined]

_acad = ModuleType("Autodesk.AutoCAD")
_autodesk = ModuleType("Autodesk")

sys.modules.setdefault("Autodesk", _autodesk)
sys.modules.setdefault("Autodesk.AutoCAD", _acad)
sys.modules["Autodesk.AutoCAD.Geometry"] = _geom

# -- Add automation/ and automation/scripts to sys.path (civil lives in automation/) --
_AUTOMATION = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "automation")
)
if _AUTOMATION not in sys.path:
    sys.path.insert(0, _AUTOMATION)

_SCRIPTS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "automation", "scripts")
)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

# -- Add tests/ itself so test files can do: from helpers import MockAlignment --
_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
