"""Dump the example GSI kolodec: enumerate all Solid3d + polylines in model space.

Goal: learn how 1.5x1x1 gabion blocks are laid out in the ring (orientation via
bbox dims, tiers by Z, corner handling) and how the 6x2x0.5 bottom mats relate to
the outer dashed polyline. For each solid we log its bbox (min/max, dx/dy/dz), the
implied block size class, the bbox center, and its layer. For each polyline we log
its layer, closed flag, and vertices.
"""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Polyline,
    Polyline2d,
    Polyline3d,
    Solid3d,
    SymbolUtilityServices,
)

BASE = r"C:\Arhyz\automation\scripts\debug\dump_gsi_kolodec"
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
LOG = os.path.join(BASE, "logs", f"dump_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")


def log(m=""):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


def classify(dx, dy, dz):
    """Guess block class from sorted bbox dims."""
    dims = sorted([dx, dy, dz])

    def near(a, b):
        return abs(a - b) <= 0.15

    if near(dims[0], 0.5) and near(dims[1], 2.0) and near(dims[2], 6.0):
        return "MAT 6x2x0.5"
    if near(dims[0], 1.0) and near(dims[1], 1.0) and near(dims[2], 1.5):
        return "GABION 1.5x1x1"
    return "?"


def main(tx, db):
    ms = tx.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead)
    solids = []
    plines = []
    for oid in ms:
        o = tx.GetObject(oid, OpenMode.ForRead)
        if isinstance(o, Solid3d):
            solids.append(o)
        elif isinstance(o, (Polyline, Polyline2d, Polyline3d)):
            plines.append(o)

    log(f"solids: {len(solids)}   polylines: {len(plines)}")

    # per-layer summary: count + z-bottom histogram, so mine (inf_gsi_well_*) and the
    # manual example (layer '0') can be compared side by side.
    by_layer: dict = {}
    for s in solids:
        try:
            ext = s.GeometricExtents
            zb = round(ext.MinPoint.Z, 2)
            d = by_layer.setdefault(s.Layer, {})
            d[zb] = d.get(zb, 0) + 1
        except Exception:
            pass
    log("")
    log("=== SOLIDS PER LAYER (z_bottom histogram) ===")
    for lay in sorted(by_layer):
        tot = sum(by_layer[lay].values())
        hist = "  ".join(f"z{z:.2f}:{c}" for z, c in sorted(by_layer[lay].items()))
        log(f"layer '{lay}': {tot} solids | {hist}")

    log("")
    log("=== POLYLINES ===")
    for p in plines:
        lay = p.Layer
        typ = type(p).__name__
        try:
            n = p.NumberOfVertices
            verts = []
            for i in range(n):
                pt = p.GetPoint3dAt(i)
                verts.append(f"({pt.X:.3f},{pt.Y:.3f},{pt.Z:.3f})")
            closed = p.Closed
            log(f"[{typ}] layer='{lay}' closed={closed} nverts={n}")
            for v in verts:
                log(f"    {v}")
        except Exception as e:
            log(f"[{typ}] layer='{lay}' vertex-read-error: {e}")

    log("")
    log("=== SOLID3D (sorted by Z then Y then X of bbox center) ===")
    rows = []
    for s in solids:
        try:
            ext = s.GeometricExtents
            mn, mx = ext.MinPoint, ext.MaxPoint
            dx, dy, dz = mx.X - mn.X, mx.Y - mn.Y, mx.Z - mn.Z
            cx, cy, cz = (mn.X + mx.X) / 2, (mn.Y + mx.Y) / 2, (mn.Z + mx.Z) / 2
            rows.append((cz, cy, cx, dx, dy, dz, s.Layer))
        except Exception as e:
            log(f"solid bbox error: {e}")
    rows.sort(key=lambda r: (round(r[0], 2), round(r[1], 2), round(r[2], 2)))
    for cz, cy, cx, dx, dy, dz, lay in rows:
        cls = classify(dx, dy, dz)
        log(
            f"[{cls:14s}] layer='{lay}' center=({cx:.3f},{cy:.3f},{cz:.3f}) "
            f"dims dx={dx:.3f} dy={dy:.3f} dz={dz:.3f}"
        )

    # z-level histogram to see tiers
    log("")
    log("=== Z-BOTTOM LEVELS (tier detection) ===")
    zbottoms = {}
    for s in solids:
        try:
            ext = s.GeometricExtents
            zb = round(ext.MinPoint.Z, 2)
            zbottoms[zb] = zbottoms.get(zb, 0) + 1
        except Exception:
            pass
    for zb in sorted(zbottoms):
        log(f"  z_bottom={zb:.2f}  count={zbottoms[zb]}")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== DUMP GSI KOLODEC ===")
        main(tx, db)
        log("=== DONE ===")
        tx.Commit()
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()
finally:
    lock.Dispose()

OUT = LOG
