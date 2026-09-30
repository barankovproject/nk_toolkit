"""Dump the blue approximating polyline + all anchor horizontals (inf_md_anchor)."""

from __future__ import annotations

import clr
import datetime
import os
import traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import BlockTableRecord, OpenMode, Polyline

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_anchor_lines\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_anchor_lines_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

ANCHOR_LAYER = "inf_md_anchor"
BLUE = 5


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def layer_color_index(tx, db, name):
    try:
        lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
        for lid in lt:
            ltr = tx.GetObject(lid, OpenMode.ForRead)
            if ltr.Name == name:
                return ltr.Color.ColorIndex
    except Exception:
        pass
    return None


def describe(pl, tx, db):
    n = int(pl.NumberOfVertices)
    pts = [(pl.GetPoint2dAt(i).X, pl.GetPoint2dAt(i).Y) for i in range(n)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    eff_color = pl.Color.ColorIndex
    if pl.Color.IsByLayer:
        eff_color = layer_color_index(tx, db, pl.Layer)
    log(f"  handle      : {pl.Handle.ToString()}")
    log(f"  layer       : {pl.Layer}")
    log(
        f"  color index : {pl.Color.ColorIndex} (ByLayer={pl.Color.IsByLayer}, effective={eff_color})"
    )
    log(f"  elevation   : {pl.Elevation:.4f}")
    log(f"  closed      : {pl.Closed}")
    log(f"  vertices    : {n}")
    log(f"  length(2D)  : {pl.Length:.4f}")
    log(
        f"  extents X   : [{min(xs):.3f}, {max(xs):.3f}]  Y: [{min(ys):.3f}, {max(ys):.3f}]"
    )
    log(
        f"  midpoint    : ({(min(xs) + max(xs)) / 2:.3f}, {(min(ys) + max(ys)) / 2:.3f})"
    )
    show = pts if n <= 40 else pts[:20] + [("...", "...")] + pts[-20:]
    log("  vertices XY :")
    for p in show:
        if p[0] == "...":
            log("      ...")
        else:
            log(f"      ({p[0]:.3f}, {p[1]:.3f})")
    log("")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)

        anchors = []
        blues = []
        all_pl = 0
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not isinstance(ent, Polyline):
                continue
            all_pl += 1
            eff = ent.Color.ColorIndex
            if ent.Color.IsByLayer:
                eff = layer_color_index(tx, db, ent.Layer)
            if ent.Layer == ANCHOR_LAYER:
                anchors.append(ent)
            elif eff == BLUE:
                blues.append(ent)

        log(f"=== model space: {all_pl} polylines total ===\n")

        log(
            f"=== BLUE polylines (effective color {BLUE}, not on {ANCHOR_LAYER}): {len(blues)} ==="
        )
        for pl in blues:
            describe(pl, tx, db)

        log(f"=== ANCHOR horizontals (layer {ANCHOR_LAYER}): {len(anchors)} ===")
        anchors.sort(key=lambda p: p.Elevation)
        for pl in anchors:
            describe(pl, tx, db)

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
