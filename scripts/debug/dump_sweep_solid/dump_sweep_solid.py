"""Dump: does Solid3d.CreateSweptSolid handle a WIDE cross-section (~top_w) swept
along a curved arc path whose radius is comparable to that width -- the exact
scale that made Solid3d.CreateLoftedSolid(..., pathCurve, ...) throw
`eGeneralModelingFailure` on build_gsi_kv_trapezoid_faceted's В-5А-2 sharp PI
(top_w~9.4m, R~10.36m, defl~38.7 deg), regardless of how many intermediate
cross-sections were also passed. CreateSweptSolid is a different ACIS
operation (SWEEP, one profile carried along a path) from CreateLoftedSolid
(LOFT, blends between 2+ profiles) -- testing whether it tolerates this scale
where the loft-with-path approach did not.
"""

from __future__ import annotations

import datetime
import math
import os
import traceback

import clr

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (
    DBObjectCollection,
    Line,
    OpenMode,
    Poly3dType,
    Polyline3d,
    Region,
    Solid3d,
    SweepOptionsAlignOption,
    SweepOptionsBuilder,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.Geometry import Point3d, Point3dCollection

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_sweep_solid\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_sweep_solid_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def make_region(pts, ms, tx):
    n = len(pts)
    lines = []
    for i in range(n):
        ln = Line(pts[i], pts[(i + 1) % n])
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


def try_sweep(label, ms, tx, region, path_ent, align, bank):
    log(f"--- attempt: {label} (align={align}, bank={bank}) ---")
    try:
        builder = SweepOptionsBuilder()
        builder.Align = align
        builder.Bank = bank
        opts = builder.ToSweepOptions()
        solid = Solid3d()
        solid.CreateSweptSolid(region, path_ent, opts)
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
log(f"=== dump_sweep_solid {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===")

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite
        )

        R = 10.356
        phi = math.radians(38.7)
        half_w = 9.414 / 2.0
        depth = 1.0
        n_samples = 30

        def build_case(base_y, align, bank):
            cx, cy = 0.0, base_y
            start_ang = 0.0
            path_pts = Point3dCollection()
            for i in range(n_samples + 1):
                ang = start_ang + phi * i / n_samples
                path_pts.Add(
                    Point3d(cx + R * math.cos(ang), cy + R * math.sin(ang), 0.0)
                )
            path_ent = Polyline3d(Poly3dType.SimplePoly, path_pts, False)
            ms.AppendEntity(path_ent)
            tx.AddNewlyCreatedDBObject(path_ent, True)

            lx0, ly0 = math.cos(start_ang), math.sin(start_ang)
            x0, y0 = cx + R * lx0, cy + R * ly0
            p0 = Point3d(x0 - half_w * lx0, y0 - half_w * ly0, 0.0)
            p1 = Point3d(x0 + half_w * lx0, y0 + half_w * ly0, 0.0)
            p2 = Point3d(x0 + half_w * lx0, y0 + half_w * ly0, depth)
            p3 = Point3d(x0 - half_w * lx0, y0 - half_w * ly0, depth)
            region = make_region([p0, p1, p2, p3], ms, tx)

            return try_sweep(
                f"R={R} half_w={half_w} phi_deg=38.7",
                ms,
                tx,
                region,
                path_ent,
                align,
                bank,
            )

        ok1 = build_case(0.0, SweepOptionsAlignOption.AlignSweepEntityToPath, True)
        ok2 = build_case(30.0, SweepOptionsAlignOption.AlignSweepEntityToPath, False)
        ok3 = build_case(60.0, SweepOptionsAlignOption.NoAlignment, False)

        log("")
        log(
            f"summary: AlignToPath+Bank={ok1} AlignToPath+NoBank={ok2} NoAlignment={ok3}"
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
