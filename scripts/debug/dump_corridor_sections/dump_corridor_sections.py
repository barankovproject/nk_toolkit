"""Dump corridor section stations from Daylight feature-line points (НК-1А-7).

Shows where the corridor places its cross-sections: the station of each Daylight
left/right feature-line point, the spacing, and whether left/right stations align —
so transverse pit lines (поперечины) can be drawn at exactly those stations.
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

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_corridor_sections\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_corridor_sections_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

TARGET = "1A-7"  # substring to match the corridor name


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def fl_pts(fl):
    return list(fl.FeatureLinePoints)


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
            n = corr.Name.replace("-", "").replace(" ", "")
            if TARGET.replace("-", "") in n or "1А7" in corr.Name:
                target = corr
                break
        if target is None:
            log(f"corridor matching {TARGET!r} not found")
        else:
            log(f"corridor: '{target.Name}'")
            bl = list(target.Baselines)[0]
            fl_map = bl.MainBaselineFeatureLines.FeatureLineCollectionMap
            fls = list(fl_map["Daylight"])
            log(f"Daylight FLs: {len(fls)}")
            main = sorted(fls, key=lambda fl: len(fl_pts(fl)), reverse=True)[:2]

            for idx, fl in enumerate(main):
                pts = fl_pts(fl)
                stas = [round(float(p.Station), 3) for p in pts]
                off0 = round(float(pts[0].Offset), 3) if pts else 0
                log(f"\n FL[{idx}] offset0={off0}  points={len(stas)}")
                log(f"   first 8 stations: {stas[:8]}")
                log(f"   last 5 stations:  {stas[-5:]}")
                diffs = [
                    round(stas[i + 1] - stas[i], 3)
                    for i in range(min(12, len(stas) - 1))
                ]
                log(f"   first spacings: {diffs}")

            # alignment check between the two main FLs
            a, b = main[0], main[1]
            sa = [round(float(p.Station), 3) for p in fl_pts(a)]
            sb = [round(float(p.Station), 3) for p in fl_pts(b)]
            log(
                f"\n left pts={len(sa)} right pts={len(sb)}  same_count={len(sa) == len(sb)}"
            )
            if len(sa) == len(sb):
                mism = sum(1 for i in range(len(sa)) if abs(sa[i] - sb[i]) > 0.01)
                log(f" station mismatches (by index): {mism}")

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
