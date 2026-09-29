"""Dump the point_number block geometry + the user's red circle marker so we learn where
the "red point" (leader/polka junction that must land on the offset rail) sits relative to
the block insertion and the Положение1 grip. One block + one red circle expected.
"""

from __future__ import annotations

import clr, datetime, math, os, sys, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    BlockReference,
    Circle,
    DBObjectCollection,
    Line,
    OpenMode,
    SymbolUtilityServices,
)

BASE = r"C:\Arhyz\automation\scripts\debug\dump_block_geom"
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
LOG = os.path.join(BASE, "logs", f"dump_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")


def log(m=""):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


def eff_name(br, tx):
    try:
        if br.IsDynamicBlock:
            return tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead).Name
    except Exception:
        pass
    return tx.GetObject(br.BlockTableRecord, OpenMode.ForRead).Name


def main(tx, db):
    ms = tx.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead)
    br = None
    red = None
    for oid in ms:
        o = tx.GetObject(oid, OpenMode.ForRead)
        if isinstance(o, BlockReference) and eff_name(o, tx) == "point_number":
            br = o
        elif isinstance(o, Circle):
            red = o  # the user's marker (assume the only circle)
    if br is None:
        log("no point_number block found")
        return
    ins = br.Position
    log(f"insertion: ({ins.X:.4f}, {ins.Y:.4f})")
    log(
        f"rotation_deg: {math.degrees(br.Rotation):.3f}  scale: {br.ScaleFactors.X:.4f}"
    )
    try:
        for p in br.DynamicBlockReferencePropertyCollection:
            log(f"  dyn '{p.PropertyName}' = {p.Value}")
    except Exception as e:
        log(f"dyn read error: {e}")
    # explode to see the polka + leader segments (world coords, and relative to insertion)
    objs = DBObjectCollection()
    try:
        br.Explode(objs)
        log("--- exploded segments (relative to insertion) ---")
        for o in objs:
            if isinstance(o, Line):
                s, e = o.StartPoint, o.EndPoint
                log(
                    f"  LINE rel ({s.X - ins.X:.3f},{s.Y - ins.Y:.3f}) -> "
                    f"({e.X - ins.X:.3f},{e.Y - ins.Y:.3f})  len={s.DistanceTo(e):.3f}"
                )
            else:
                log(f"  {o.GetType().Name}")
    except Exception as e:
        log(f"explode error: {e}")
    if red is not None:
        c = red.Center
        log(f"--- red circle center: ({c.X:.4f}, {c.Y:.4f}) ---")
        log(f"  red relative to insertion: ({c.X - ins.X:.3f}, {c.Y - ins.Y:.3f})")
    else:
        log("no red circle found")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== DUMP BLOCK GEOM ===")
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
