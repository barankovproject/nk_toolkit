"""Dump: does Solid3d.CreateLoftedSolid accept a degenerate point cross-section?

Tests whether lofting a closed Region down to a single point (DBPoint, then a
zero/near-zero-radius Circle as fallbacks) produces a valid tapering wedge
Solid3d -- needed for the sharp-PI fan-wedge fix in
build_gsi_kv_trapezoid_faceted (each facet piece would loft its own full outer
section down to one shared apex point instead of a hybrid/self-intersecting
9-point section).
"""

from __future__ import annotations

import datetime
import os
import traceback

import clr

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (
    Circle,
    DBObjectCollection,
    DBPoint,
    Line,
    LoftOptions,
    OpenMode,
    Region,
    Solid3d,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.Geometry import Point3d, Vector3d

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_loft_to_point\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_loft_to_point_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def make_square_region(ms, tx, cx, cy, cz, half=1.0):
    pts = [
        Point3d(cx - half, cy - half, cz),
        Point3d(cx + half, cy - half, cz),
        Point3d(cx + half, cy + half, cz),
        Point3d(cx - half, cy + half, cz),
    ]
    lines = []
    for i in range(4):
        ln = Line(pts[i], pts[(i + 1) % 4])
        ms.AppendEntity(ln)
        tx.AddNewlyCreatedDBObject(ln, True)
        lines.append(ln)
    col = DBObjectCollection()
    for ln in lines:
        col.Add(ln)
    region_col = Region.CreateFromCurves(col)
    region = region_col[0]
    ms.AppendEntity(region)
    tx.AddNewlyCreatedDBObject(region, True)
    for ln in lines:
        ln.Erase()
    return region


def try_loft(label, ms, tx, region, apex_entity, already_added=False):
    log(f"--- attempt: {label} ---")
    try:
        if not already_added:
            ms.AppendEntity(apex_entity)
            tx.AddNewlyCreatedDBObject(apex_entity, True)
        opts = LoftOptions()
        solid = Solid3d()
        solid.CreateLoftedSolid([region, apex_entity], [], None, opts)
        vol = None
        try:
            vol = float(solid.MassProperties.Volume)
        except Exception as ve:
            log(f"  MassProperties.Volume failed: {ve}")
        ms.AppendEntity(solid)
        tx.AddNewlyCreatedDBObject(solid, True)
        log(f"  SUCCESS: solid created, volume={vol}")
        return True
    except Exception as e:
        log(f"  FAILED: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return False


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
log(f"=== dump_loft_to_point {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===")

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite
        )

        base_x, base_y, base_z = 0.0, 0.0, 0.0
        apex_z = 3.0  # separate the two profiles along Z, NOT laterally in their own
        # plane -- two coplanar regions offset sideways in the same Z is a degenerate
        # loft (no transverse separation), which is what silently broke every earlier
        # attempt including plain region-to-region (2026-09-07 dump bug, not a real
        # CreateLoftedSolid limitation).

        region1 = make_square_region(ms, tx, base_x, base_y, base_z, half=1.0)
        pt_ent = DBPoint()
        pt_ent.Position = Point3d(base_x, base_y, apex_z)
        ok1 = try_loft("DBPoint straight above", ms, tx, region1, pt_ent)

        region2 = make_square_region(ms, tx, base_x, base_y + 5.0, base_z, half=1.0)
        circ_ent = Circle(Point3d(base_x, base_y + 5.0, apex_z), Vector3d.ZAxis, 0.0)
        ok2 = try_loft("zero-radius Circle", ms, tx, region2, circ_ent)

        region3 = make_square_region(ms, tx, base_x, base_y + 10.0, base_z, half=1.0)
        circ_ent2 = Circle(
            Point3d(base_x, base_y + 10.0, apex_z), Vector3d.ZAxis, 0.001
        )
        ok3 = try_loft("tiny-radius (0.001) Circle", ms, tx, region3, circ_ent2)

        region4 = make_square_region(ms, tx, base_x, base_y + 15.0, base_z, half=1.0)
        tiny_region = make_square_region(
            ms, tx, base_x, base_y + 15.0, apex_z, half=0.01
        )
        ok4 = try_loft(
            "tiny (half=0.01) square Region",
            ms,
            tx,
            region4,
            tiny_region,
            already_added=True,
        )

        region5 = make_square_region(ms, tx, base_x, base_y + 20.0, base_z, half=1.0)
        ok5 = try_loft(
            "plain region-to-region sanity check (half=1.0 to half=1.0, no taper)",
            ms,
            tx,
            region5,
            make_square_region(ms, tx, base_x, base_y + 20.0, apex_z, half=1.0),
            already_added=True,
        )

        log("")
        log(
            f"summary: DBPoint={ok1} zero-radius-Circle={ok2} "
            f"tiny-radius-Circle={ok3} tiny-region={ok4} plain-sanity={ok5}"
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
