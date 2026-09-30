"""Dump NK-3A-1 gabion solids near plan PI 133.562 (volume/centroid/extents) to find a missing or degenerate loft span."""

from __future__ import annotations

import datetime
import math
import os
import traceback

import clr

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Solid3d,
    SymbolUtilityServices,
)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_pi_gap\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_pi_gap_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

# PI 133.562 of NK-3A-1 (world XY from canal JSON section_points)
PI_X, PI_Y = 255607.7, 516099.5
RADIUS = 12.0


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
        ms = tx.GetObject(ms_id, OpenMode.ForRead)
        found = []
        total = 0
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not isinstance(ent, Solid3d):
                continue
            total += 1
            try:
                mp = ent.MassProperties
                c = mp.Centroid
                cx, cy, cz = float(c.X), float(c.Y), float(c.Z)
            except Exception as e:
                log(f"handle={ent.Handle} layer={ent.Layer} MassProperties FAILED: {e}")
                continue
            if math.hypot(cx - PI_X, cy - PI_Y) > RADIUS:
                continue
            vol = float(mp.Volume)
            try:
                ext = ent.GeometricExtents
                mn, mx = ext.MinPoint, ext.MaxPoint
                bbox = (
                    f"bbox=({mn.X:.3f},{mn.Y:.3f},{mn.Z:.3f})-"
                    f"({mx.X:.3f},{mx.Y:.3f},{mx.Z:.3f})"
                )
                dims = f"dims=({mx.X - mn.X:.3f},{mx.Y - mn.Y:.3f},{mx.Z - mn.Z:.3f})"
            except Exception as e:
                bbox = f"extents FAILED: {e}"
                dims = ""
            found.append((cx, cy, vol, ent.Handle, ent.Layer, bbox, dims, cz))

        log(f"total Solid3d in model space: {total}")
        log(
            f"solids with centroid within {RADIUS}m of PI ({PI_X}, {PI_Y}): {len(found)}"
        )
        log("")
        # sort along the incoming tangent (+X-ish) to read spans in station order
        for cx, cy, vol, h, layer, bbox, dims, cz in sorted(found, key=lambda r: r[0]):
            log(
                f"handle={h} layer={layer} vol={vol:.4f} "
                f"centroid=({cx:.3f},{cy:.3f},{cz:.3f}) {bbox} {dims}"
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
