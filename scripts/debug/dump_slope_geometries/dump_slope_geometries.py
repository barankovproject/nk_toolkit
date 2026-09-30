"""Dump CorridorSlopePattern.GetGeometries() output for НК-1А-7.

Shows what the corridor slope patterns (бергштрихи) expose as geometry — object
types and counts — so we can copy them into the excavation drawing as real entities.
Requires draw_corridor_slope_hatches to have run (patterns must exist on the corridor).
"""

from __future__ import annotations

import clr, datetime, os, sys, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import safe_iter, safe_resolve  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_slope_geometries\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_slope_geometries_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

TARGET = "1A-7"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        cc = civil_db.CorridorCollection
        target = None
        for raw in safe_iter(cc):
            corr = safe_resolve(raw, tx)
            if corr is None:
                continue
            if (
                TARGET.replace("-", "") in corr.Name.replace("-", "").replace(" ", "")
                or "1А7" in corr.Name
            ):
                target = corr
                break
        if target is None:
            log(f"corridor {TARGET!r} not found")
        else:
            log(f"corridor: '{target.Name}'")
            sp_col = target.SlopePatterns
            log(f"SlopePatterns count: {sp_col.Count}")
            for i in range(min(sp_col.Count, 2)):
                sp = sp_col.get_Item(i)
                log(f"\n pattern[{i}]: style={sp.StyleName}")
                try:
                    geoms = sp.GetGeometries()
                    log(
                        f"   GetGeometries: type={type(geoms).__name__}  count={geoms.Count}"
                    )
                    types: dict = {}
                    for j in range(geoms.Count):
                        g = geoms[j]
                        tn = type(g).__name__
                        types[tn] = types.get(tn, 0) + 1
                    log(f"   object types: {types}")
                    # detail first 3
                    for j in range(min(geoms.Count, 3)):
                        g = geoms[j]
                        attrs = [
                            a
                            for a in (
                                "Layer",
                                "StartPoint",
                                "EndPoint",
                                "Length",
                                "NumberOfVertices",
                            )
                            if hasattr(g, a)
                        ]
                        vals = {}
                        for a in attrs:
                            try:
                                vals[a] = str(getattr(g, a))
                            except Exception:
                                pass
                        log(f"     [{j}] {type(g).__name__}: {vals}")
                except Exception as e:
                    log(f"   GetGeometries ERROR: {e}")
                    log(traceback.format_exc())

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
