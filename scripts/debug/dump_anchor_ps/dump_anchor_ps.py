"""Report same-row anchor gaps > 4 m, by anchor Number (from the PS)."""

from __future__ import annotations

import clr
import datetime
import math
import os
import traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("AecPropDataMgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode
import Autodesk.Aec.PropertyData.DatabaseServices as _PD

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_anchor_ps\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"ps_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
PTS_LAYER = "inf_md_anchor_pts"
PS_DEF = "Arhyz_Anchor"
LIMIT = 4.0


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        dpsd = _PD.DictionaryPropertySetDefinitions(db)
        psd_id = dpsd.GetAt(PS_DEF) if PS_DEF in list(dpsd.NamesInUse) else None

        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        items = []  # (z, x, y, number)
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not (isinstance(ent, Circle) and ent.Layer == PTS_LAYER):
                continue
            c = ent.Center
            num = None
            if psd_id is not None:
                try:
                    ps = tx.GetObject(
                        _PD.PropertyDataServices.GetPropertySet(ent, psd_id),
                        OpenMode.ForRead,
                    )
                    num = ps.GetAt(ps.PropertyNameToId("Number"))
                except Exception:
                    pass
            items.append((round(float(c.Z), 3), float(c.X), float(c.Y), num))

        log(f"circles: {len(items)}   limit: {LIMIT} m")
        rows = {}
        for z, x, y, num in items:
            rows.setdefault(z, []).append((x, y, num))

        total = 0
        for z in sorted(rows):
            pts = sorted(rows[z])  # west -> east
            over = []
            for i in range(len(pts) - 1):
                d = math.dist((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]))
                if d > LIMIT:
                    over.append((pts[i][2], pts[i + 1][2], d))
            if over:
                log(f"\nz{z}: {len(over)} gap(s) > {LIMIT} m")
                for a, b, d in over:
                    log(f"  #{a} -- #{b}:  {d:.2f} m")
                total += len(over)
        log(f"\ntotal gaps > {LIMIT} m: {total}")
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
