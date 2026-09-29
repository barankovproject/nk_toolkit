"""Dump curves (by layer) + circle/text markers to understand the two zones to contour."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Line,
    Arc,
    Polyline,
    Polyline2d,
    Polyline3d,
    Circle,
    DBText,
    MText,
)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_segments_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def p2(x: float, y: float) -> str:
    return f"({x:.3f}, {y:.3f})"


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)

        # --- Section A: per-layer histogram of entity types ---
        hist: dict[str, dict[str, int]] = {}
        curves: list[tuple] = []  # (layer, type, ent)
        markers: list[tuple] = []  # (kind, layer, text, x, y)

        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            tname = type(ent).__name__
            layer = getattr(ent, "Layer", "<none>")
            hist.setdefault(layer, {}).setdefault(tname, 0)
            hist[layer][tname] += 1

            if isinstance(ent, (Line, Arc, Polyline, Polyline2d, Polyline3d)):
                curves.append((layer, tname, ent))
            elif isinstance(ent, Circle):
                c = ent.Center
                markers.append(("Circle", layer, f"r={ent.Radius:.2f}", c.X, c.Y))
            elif isinstance(ent, DBText):
                p = ent.Position
                markers.append(("DBText", layer, ent.TextString, p.X, p.Y))
            elif isinstance(ent, MText):
                p = ent.Location
                markers.append(("MText", layer, ent.Text, p.X, p.Y))

        log("=== SECTION A: per-layer entity histogram ===")
        for layer in sorted(hist):
            parts = ", ".join(f"{t}={n}" for t, n in sorted(hist[layer].items()))
            log(f"  [{layer}] {parts}")

        # --- Section B: markers (circles + texts) ---
        log("")
        log(f"=== SECTION B: markers (circles + texts): {len(markers)} ===")
        for kind, layer, txt, x, y in markers:
            log(f"  {kind} [{layer}] '{txt}' at {p2(x, y)}")

        # --- Section C: curve geometry (endpoints + polyline vertices) ---
        log("")
        log(f"=== SECTION C: curves: {len(curves)} ===")
        for layer, tname, ent in curves:
            try:
                if isinstance(ent, Line):
                    s, e = ent.StartPoint, ent.EndPoint
                    log(f"  Line [{layer}] {p2(s.X, s.Y)} -> {p2(e.X, e.Y)}")
                elif isinstance(ent, Arc):
                    s, e = ent.StartPoint, ent.EndPoint
                    log(
                        f"  Arc  [{layer}] {p2(s.X, s.Y)} -> {p2(e.X, e.Y)} r={ent.Radius:.3f}"
                    )
                elif isinstance(ent, Polyline):
                    n = ent.NumberOfVertices
                    vs = [ent.GetPoint2dAt(i) for i in range(n)]
                    closed = ent.Closed
                    log(f"  Polyline [{layer}] n={n} closed={closed}")
                    log("      " + " ".join(p2(v.X, v.Y) for v in vs))
                elif isinstance(ent, Polyline2d):
                    pts = []
                    for vid in ent:
                        v = tx.GetObject(vid, OpenMode.ForRead)
                        pos = v.Position
                        pts.append((pos.X, pos.Y))
                    log(f"  Polyline2d [{layer}] n={len(pts)} closed={ent.Closed}")
                    log("      " + " ".join(p2(x, y) for x, y in pts))
                elif isinstance(ent, Polyline3d):
                    pts = []
                    for vid in ent:
                        v = tx.GetObject(vid, OpenMode.ForRead)
                        pos = v.Position
                        pts.append((pos.X, pos.Y))
                    log(f"  Polyline3d [{layer}] n={len(pts)} closed={ent.Closed}")
                    log("      " + " ".join(p2(x, y) for x, y in pts))
            except Exception as e:
                log(f"  {tname} [{layer}] ERROR: {e}")

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
