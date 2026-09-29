"""List every Polyline / Polyline2d / Line group: layer, closed, nverts, area, bbox."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline, Polyline2d

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_polys_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        n = 0
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if isinstance(ent, Polyline):
                pts = [
                    (ent.GetPoint2dAt(i).X, ent.GetPoint2dAt(i).Y)
                    for i in range(ent.NumberOfVertices)
                ]
            elif isinstance(ent, Polyline2d):
                pts = []
                for vid in ent:
                    v = tx.GetObject(vid, OpenMode.ForRead)
                    pts.append((v.Position.X, v.Position.Y))
            else:
                continue
            n += 1
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            log(
                f"{type(ent).__name__} [{ent.Layer}] color={ent.ColorIndex} closed={ent.Closed} "
                f"nverts={len(pts)} area={area(pts):.1f} "
                f"bbox=({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f})"
            )
        log(f"total polylines: {n}")
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

OUT = LOG_FILE
