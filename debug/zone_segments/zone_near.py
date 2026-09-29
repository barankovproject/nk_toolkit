"""For each marker, find the nearest line segments across ALL layers (what actually bounds it)."""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Line, Polyline, MText

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_near_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        # segs: (layer, x1, y1, x2, y2)
        segs = []
        markers = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            ly = getattr(ent, "Layer", None)
            if isinstance(ent, Line):
                s, e = ent.StartPoint, ent.EndPoint
                segs.append((ly, s.X, s.Y, e.X, e.Y))
            elif isinstance(ent, Polyline):
                n = ent.NumberOfVertices
                for i in range(n - 1):
                    a = ent.GetPoint2dAt(i)
                    b = ent.GetPoint2dAt(i + 1)
                    segs.append((ly, a.X, a.Y, b.X, b.Y))
            elif isinstance(ent, MText) and ent.Text in ("1", "2"):
                p = ent.Location
                markers.append((ent.Text, p.X, p.Y))

        log(f"{len(segs)} sub-segments total; markers={markers}")
        for mtext, mx, my in markers:
            dists = []
            for ly, x1, y1, x2, y2 in segs:
                d = seg_dist(mx, my, x1, y1, x2, y2)
                dists.append((d, ly, (x1 + x2) / 2, (y1 + y2) / 2))
            dists.sort(key=lambda t: t[0])
            log("")
            log(
                f"=== marker '{mtext}' ({mx:.1f},{my:.1f}) — 12 nearest sub-segments ==="
            )
            for d, ly, mxs, mys in dists[:12]:
                log(f"   d={d:8.2f} m  [{ly}]  mid=({mxs:.1f},{mys:.1f})")
            # per-layer nearest
            bylayer = {}
            for d, ly, _, _ in dists:
                if ly not in bylayer or d < bylayer[ly]:
                    bylayer[ly] = d
            log(
                "   nearest per layer: "
                + "; ".join(
                    f"[{k}]={v:.1f}"
                    for k, v in sorted(bylayer.items(), key=lambda kv: kv[1])
                )
            )

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
