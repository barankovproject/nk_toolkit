"""Extract the toe-of-slope (подошва) as the slope-break line of a picked TIN and draw it.

The floor (дно) is sloped (pipe invert grade), so the toe is NOT a contour. It is the set
of TIN edges between 'steep' (side-slope) triangles and 'gentle' (floor) triangles. We
classify each triangle by slope, collect mixed-class shared edges, and draw them red on
layer DBG_TOE for visual confirmation. Logs a triangle-slope histogram to tune _THR.
"""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import (
    Line,
    OpenMode,
    SymbolUtilityServices,
    LayerTable,
    LayerTableRecord,
)
from Autodesk.AutoCAD.EditorInput import PromptEntityOptions
from Autodesk.AutoCAD.Geometry import Point3d
from Autodesk.Civil.DatabaseServices import TinSurface

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_excavation_surface\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"toe_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")

# Steep/gentle split (rise/run). 0.5 = 1:2. Side slopes are far steeper than the floor.
_THR = 0.5
_DBG_LAYER = "DBG_TOE"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def tri_slope(p1, p2, p3) -> float:
    """rise/run of the steepest line on the triangle plane (0=flat, big=steep/vertical)."""
    ax, ay, az = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
    bx, by, bz = p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    horiz = math.hypot(nx, ny)
    if abs(nz) < 1e-12:
        return 999.0
    return horiz / abs(nz)


def ensure_layer(db, tx, name):
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    if lt.Has(name):
        return
    lt.UpgradeOpen()
    ltr = LayerTableRecord()
    ltr.Name = name
    ltr.Color = Color.FromColorIndex(ColorMethod.ByAci, 1)  # red
    lt.Add(ltr)
    tx.AddNewlyCreatedDBObject(ltr, True)


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
ed = doc.Editor
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        opts = PromptEntityOptions("\nВыберите поверхность откопки: ")
        opts.SetRejectMessage("\nНужна TIN-поверхность.")
        opts.AddAllowedClass(TinSurface, False)
        per = ed.GetEntity(opts)
        if int(per.Status) != 5100:
            log(f"pick cancelled, status={int(per.Status)}")
            raise SystemExit
        surf = tx.GetObject(per.ObjectId, OpenMode.ForRead)
        log(f"surface '{surf.Name}'  threshold _THR={_THR}")

        tris = surf.GetTriangles(False)  # visible only
        # edge_key (sorted vertex coords) -> list of triangle slope-classes (True=steep)
        edge_cls = {}
        slopes = []
        n_tri = 0

        def vkey(p):
            return (round(p[0], 3), round(p[1], 3))

        for t in tris:
            try:
                v1, v2, v3 = t.Vertex1.Location, t.Vertex2.Location, t.Vertex3.Location
            except Exception:
                continue
            p1 = (float(v1.X), float(v1.Y), float(v1.Z))
            p2 = (float(v2.X), float(v2.Y), float(v2.Z))
            p3 = (float(v3.X), float(v3.Y), float(v3.Z))
            s = tri_slope(p1, p2, p3)
            slopes.append(s)
            steep = s >= _THR
            n_tri += 1
            for a, b in ((p1, p2), (p2, p3), (p3, p1)):
                k = tuple(sorted((vkey(a), vkey(b))))
                edge_cls.setdefault(k, []).append((steep, a, b))

        log(f"triangles: {n_tri}")
        if slopes:
            hist = {}
            for s in slopes:
                bb = min(int(s / 0.25), 8)  # bins of 0.25 up to >=2.0
                hist[bb] = hist.get(bb, 0) + 1
            log("triangle-slope histogram (rise/run bins):")
            for bb in sorted(hist):
                lo = bb * 0.25
                lab = f">={lo:.2f}" if bb == 8 else f"{lo:.2f}..{lo + 0.25:.2f}"
                log(f"  {lab}: {hist[bb]}")

        # toe edges = shared edges with one steep + one gentle triangle
        ensure_layer(db, tx, _DBG_LAYER)
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite
        )
        n_toe, length = 0, 0.0
        for k, lst in edge_cls.items():
            if len(lst) != 2:
                continue  # border edge or non-manifold
            if lst[0][0] == lst[1][0]:
                continue  # same class → not a break
            _, a, b = lst[0]
            ln = Line(Point3d(*a), Point3d(*b))
            ln.Layer = _DBG_LAYER
            ms.AppendEntity(ln)
            tx.AddNewlyCreatedDBObject(ln, True)
            n_toe += 1
            length += math.dist(a, b)
        log(
            f"toe break edges drawn: {n_toe}, total length {length:.1f} (layer {_DBG_LAYER})"
        )

        log("\n=== DONE ===")
        tx.Commit()
    except SystemExit:
        log("=== aborted (no pick) ===")
        tx.Commit()
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()
finally:
    lock.Dispose()

OUT = LOG_FILE
