"""Dump Hatch entities and their boundary loops to read the user's hatched zone-1 polygon."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Hatch
from Autodesk.AutoCAD.Geometry import Point2d

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_hatch_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        n_hatch = 0
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if not isinstance(ent, Hatch):
                continue
            n_hatch += 1
            log(
                f"=== Hatch #{n_hatch} layer=[{ent.Layer}] pattern={ent.PatternName} "
                f"area={getattr(ent, 'Area', 'n/a')} loops={ent.NumberOfLoops} ==="
            )
            for li in range(ent.NumberOfLoops):
                try:
                    loop = ent.GetLoopAt(li)
                    lt = ent.LoopTypeAt(li)
                    log(f"  loop {li}: type={lt}")
                    # Try polyline vertices first
                    try:
                        verts = loop.Polyline
                        if verts is not None and verts.Count > 0:
                            pts = [verts[k].Vertex for k in range(verts.Count)]
                            log(f"    polyline verts={len(pts)}")
                            xs = [p.X for p in pts]
                            ys = [p.Y for p in pts]
                            log(
                                f"    bbox=({min(xs):.1f},{min(ys):.1f})-({max(xs):.1f},{max(ys):.1f})"
                            )
                            log(
                                "    pts: "
                                + " ".join(f"({p.X:.1f},{p.Y:.1f})" for p in pts[:40])
                            )
                            if len(pts) > 40:
                                log(f"    ... (+{len(pts) - 40} more)")
                            continue
                    except Exception as e:
                        log(f"    (no Polyline accessor: {e})")
                    # Fallback: enumerate curves in the loop
                    try:
                        curves = loop.Curves
                        log(f"    curves={curves.Count if curves else 0}")
                    except Exception as e2:
                        log(f"    (no Curves accessor: {e2})")
                except Exception as e:
                    log(f"  loop {li}: ERROR {e}")
        log(f"total hatches: {n_hatch}")
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
