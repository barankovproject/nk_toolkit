"""Compact dump: grid perps, circles, and the NEWEST user-drawn polylines."""

from __future__ import annotations

import clr
import datetime
import os
import traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode, Polyline

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_grid_overlap\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_grid_overlap_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

ANCHOR_LAYERS = {
    "inf_md_anchor",
    "inf_md_anchor_axis",
    "inf_md_anchor_grid",
    "inf_md_anchor_div",
    "inf_md_anchor_pts",
}


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def hx(h) -> int:
    try:
        return int(h.ToString(), 16)
    except Exception:
        return 0


def ends(pl):
    n = int(pl.NumberOfVertices)
    a = pl.GetPoint2dAt(0)
    b = pl.GetPoint2dAt(n - 1)
    return (a.X, a.Y), (b.X, b.Y)


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        grid_pls = []
        circles = []
        other_pls = []  # (handle_int, ent)
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(ent, Polyline):
                if ent.Layer == "inf_md_anchor_grid":
                    grid_pls.append(ent)
                elif ent.Layer not in ANCHOR_LAYERS:
                    other_pls.append((hx(ent.Handle), ent))
            elif isinstance(ent, Circle):
                circles.append(ent)

        log(f"=== grid perpendiculars (inf_md_anchor_grid): {len(grid_pls)} ===")
        for pl in sorted(grid_pls, key=lambda p: hx(p.Handle)):
            (ax, ay), (bx, by) = ends(pl)
            ang = __import__("math").degrees(__import__("math").atan2(by - ay, bx - ax))
            log(
                f"  h={pl.Handle.ToString()} color={pl.Color.ColorIndex} "
                f"len={pl.Length:.2f} ang={ang:6.1f}  "
                f"({ax:.1f},{ay:.1f})->({bx:.1f},{by:.1f})"
            )

        log(f"\n=== circles total: {len(circles)} ===")
        by_layer = {}
        for c in circles:
            by_layer[c.Layer] = by_layer.get(c.Layer, 0) + 1
        for lyr, n in sorted(by_layer.items(), key=lambda kv: -kv[1]):
            log(f"  {lyr:28s} {n}")

        log("\n=== inf_md_anchor_grid polylines with >2 verts (hand-drawn piece) ===")
        for pl in sorted(grid_pls, key=lambda p: hx(p.Handle)):
            n = int(pl.NumberOfVertices)
            if n > 2:
                pts = [(pl.GetPoint2dAt(i).X, pl.GetPoint2dAt(i).Y) for i in range(n)]
                log(
                    f"  h={pl.Handle.ToString()} color={pl.Color.ColorIndex} "
                    f"verts={n} len={pl.Length:.2f} closed={pl.Closed}"
                )
                for p in pts:
                    log(f"     ({p[0]:.2f}, {p[1]:.2f})")

        log("\n=== DONE ===")
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
