"""Dump corridor feature-line codes to confirm excavation top/bottom edges.

For each corridor (first baseline) logs all FeatureLineCollectionMap codes and the
point count per code, so we can confirm: top edge = 'Daylight', pit bottom = 'Hinge'
(or whatever the real bottom code is).
"""

from __future__ import annotations

import clr, datetime, os, sys, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.Civil.ApplicationServices import CivilApplication

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import safe_iter, safe_resolve  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_excavation_fls\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_excavation_fls_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


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
        log(f"Corridors: {cc.Count}")

        shown = 0
        for raw in safe_iter(cc):
            corr = safe_resolve(raw, tx)
            if corr is None:
                continue
            log(f"\n=== corridor '{corr.Name}' ===")
            try:
                bls = list(corr.Baselines)
                log(f"  baselines: {len(bls)}")
                bl = bls[0]
                fl_map = bl.MainBaselineFeatureLines.FeatureLineCollectionMap
                keys = list(fl_map.CodeNames())
                log(f"  feature-line codes ({len(keys)}):")
                for code in keys:
                    try:
                        fls = list(fl_map[code])
                        npts = []
                        offs = []
                        for fl in fls:
                            pts = list(fl.FeatureLinePoints)
                            npts.append(len(pts))
                            if pts:
                                offs.append(round(float(pts[0].Offset), 3))
                        log(
                            f"    {code!r:18} FLs={len(fls)}  pts={npts}  first_offsets={offs}"
                        )
                    except Exception as e:
                        log(f"    {code!r:18} ERROR {e}")
            except Exception as e:
                log(f"  ERROR reading baseline: {e}")
            shown += 1
            if shown >= 3:  # first 3 corridors are enough to see the code set
                log("\n(stopping after 3 corridors)")
                break

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
