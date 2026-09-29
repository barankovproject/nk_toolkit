"""Extract the ground contour at each elevation and clip it to the boundary.

This is the API equivalent of running MINIMUMDISTBETWEENSURFACES between the
ground and a flat plane at elevation Z: the line where the ground crosses Z is
exactly the ground contour at Z. ``TinSurface.ExtractContoursAt(Z)`` gives that
contour over the whole surface; we then clip it to the boundary polygon so only
the in-slope portion (the anchor row) survives.
"""

from __future__ import annotations

from typing import Any

from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline, Polyline3d
from Autodesk.AutoCAD.Geometry import Point2d

_EPS = 1e-9

# ---------------------------------------------------------------------------
# 2D clipping geometry (XY plane; the contour Z is constant at the elevation).
# ---------------------------------------------------------------------------


def _point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-cast point-in-polygon test against a (possibly open) ring."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + _EPS) + xi
        ):
            inside = not inside
        j = i
    return inside


def _seg_t(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float | None:
    """Parameter t in [0,1] along AB where AB crosses CD, or None if they don't."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    rxs = rx * sy - ry * sx
    if abs(rxs) < _EPS:
        return None
    qpx, qpy = c[0] - a[0], c[1] - a[1]
    t = (qpx * sy - qpy * sx) / rxs
    u = (qpx * ry - qpy * rx) / rxs
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t
    return None


def clip_to_polygon(
    pts: list[tuple[float, float]], poly: list[tuple[float, float]]
) -> list[list[tuple[float, float]]]:
    """Clip an open polyline to the inside of ``poly``; return inside runs.

    Each segment is split at every boundary crossing; sub-segments whose midpoint
    falls inside the polygon are kept and stitched into contiguous runs.
    """
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    n = len(poly)
    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        cuts = [0.0, 1.0]
        for i in range(n):
            c, d = poly[i], poly[(i + 1) % n]
            t = _seg_t(a, b, c, d)
            if t is not None and 0.0 < t < 1.0:
                cuts.append(t)
        cuts.sort()
        for m in range(len(cuts) - 1):
            t0, t1 = cuts[m], cuts[m + 1]
            if t1 - t0 < _EPS:
                continue
            tm = (t0 + t1) * 0.5
            mx = a[0] + (b[0] - a[0]) * tm
            my = a[1] + (b[1] - a[1]) * tm
            p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if _point_in_polygon(mx, my, poly):
                if not current:
                    current.append(p0)
                current.append(p1)
            elif current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)
    return runs


# ---------------------------------------------------------------------------
# Reading the extracted contour entities + drawing the clipped result.
# ---------------------------------------------------------------------------


def _read_xy(ent: Any, tx: Any) -> list[tuple[float, float]]:
    """Plan vertices of a contour entity (LWPolyline or 3D polyline)."""
    if isinstance(ent, Polyline):
        return [
            (ent.GetPoint2dAt(i).X, ent.GetPoint2dAt(i).Y)
            for i in range(int(ent.NumberOfVertices))
        ]
    if isinstance(ent, Polyline3d):
        pts: list[tuple[float, float]] = []
        for vid in ent:
            v = tx.GetObject(vid, OpenMode.ForRead)
            pos = v.Position
            pts.append((float(pos.X), float(pos.Y)))
        return pts
    return []


def _draw_run(
    db: Any,
    tx: Any,
    run: list[tuple[float, float]],
    elevation: float,
    layer: str,
    color_index: int,
) -> str:
    """Draw one clipped run as an LWPolyline at ``elevation`` on ``layer``."""
    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
    pl = Polyline()
    for i, (x, y) in enumerate(run):
        pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
    pl.Elevation = elevation
    pl.Layer = layer
    pl.Color = Color.FromColorIndex(ColorMethod.ByAci, color_index)
    ms.AppendEntity(pl)
    tx.AddNewlyCreatedDBObject(pl, True)
    return pl.Handle.ToString()


def extract_clipped_contour(
    db: Any,
    tx: Any,
    ground: Any,
    elevation: float,
    boundary_xy: list[tuple[float, float]],
    layer: str,
    color_index: int,
) -> list[str]:
    """Extract ground contour at ``elevation``, clip to boundary, draw, return handles.

    The raw contour entities created by ExtractContoursAt are erased after their
    clipped portions are redrawn on ``layer`` with the given ACI ``color_index``.
    """
    handles: list[str] = []
    raw_ids = ground.ExtractContoursAt(elevation)
    for oid in raw_ids:
        ent = tx.GetObject(oid, OpenMode.ForRead)
        xy = _read_xy(ent, tx)
        for run in clip_to_polygon(xy, boundary_xy):
            if len(run) >= 2:
                handles.append(_draw_run(db, tx, run, elevation, layer, color_index))
        ent.UpgradeOpen()
        ent.Erase()
    return handles
