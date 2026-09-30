"""Build flat (planar) TIN surfaces at given elevations from a boundary polygon.

A single closed ring of points at constant Z triangulates to a flat sheet; an
outer boundary made of the same ring clips the surface to the polygon footprint
(so concave outlines stay inside their shape). These flat surfaces are the input
the Civil ``MINIMUMDISTBETWEENSURFACES`` command consumes to draw the horizontal
line where the ground meets each elevation.
"""

from __future__ import annotations

from typing import Any

from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.AutoCAD.Geometry import Point3d, Point3dCollection
from Autodesk.Civil import SurfaceBoundaryType
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import TinSurface

# Breakline/boundary tessellation: straight segments need no supplementing, so
# mid-ordinate / max-distance / weeding are all neutral.
_MID_ORDINATE = 1.0
_MAX_DISTANCE = 0.0
_WEED_DISTANCE = 0.0
_WEED_ANGLE = 0.0


def extract_boundary_points(pline: Any) -> list[tuple[float, float]]:
    """Plan (X, Y) vertices of an LWPolyline, in order.

    Bulges/arcs are read as their vertex points only — adequate for a slope
    boundary, which is straight-segment in practice.
    """
    pts: list[tuple[float, float]] = []
    n = int(pline.NumberOfVertices)
    for i in range(n):
        p = pline.GetPoint2dAt(i)
        pts.append((float(p.X), float(p.Y)))
    return pts


def _closed_ring(xy: list[tuple[float, float]], elevation: float) -> Point3dCollection:
    """Point3dCollection at constant Z, closed back to the first vertex."""
    coll = Point3dCollection()
    for x, y in xy:
        coll.Add(Point3d(x, y, elevation))
    if xy and xy[0] != xy[-1]:
        coll.Add(Point3d(xy[0][0], xy[0][1], elevation))
    return coll


def delete_surface_named(db: Any, tx: Any, name: str) -> bool:
    """Erase any existing surface with this exact name. Return True if erased."""
    civil_db = CivilApplication.ActiveDocument
    for oid in civil_db.GetSurfaceIds():
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if getattr(ent, "Name", None) == name:
            ent.UpgradeOpen()
            ent.Erase()
            return True
    return False


def build_flat_surface(
    db: Any,
    tx: Any,
    name: str,
    xy: list[tuple[float, float]],
    elevation: float,
) -> Any:
    """Create a flat TIN surface named ``name`` at ``elevation`` over the ``xy`` ring.

    Replaces any existing surface of the same name first (idempotent re-run).
    Returns the opened TinSurface (caller reads its Handle).
    """
    if len(xy) < 3:
        raise Exception(f"Boundary has only {len(xy)} vertices; need at least 3.")

    delete_surface_named(db, tx, name)

    oid = TinSurface.Create(db, name)
    surf = tx.GetObject(oid, OpenMode.ForWrite)

    ring = _closed_ring(xy, elevation)
    surf.BreaklinesDefinition.AddStandardBreaklines(
        ring, _MID_ORDINATE, _MAX_DISTANCE, _WEED_DISTANCE, _WEED_ANGLE
    )
    surf.BoundariesDefinition.AddBoundaries(
        ring, _MID_ORDINATE, SurfaceBoundaryType.Outer, False
    )
    surf.Rebuild()
    return surf
