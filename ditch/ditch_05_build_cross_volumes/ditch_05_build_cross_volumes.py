"""Recompute cross-ditch volume property sets from the current drawn geometry.

Run after manually editing marked ditches (inf_md_*) in the drawing: it re-reads
every tagged ditch's live geometry and rewrites the volume fields of its
Arhyz_CrossDitch property set, so the quantities match what is actually drawn.
Rates live in ditch_04_build_cross/volumes.py; this script never recomputes them
inline. The ведомость (ditch_06_report_cross) then sums the refreshed values.
"""

from __future__ import annotations

import clr
import datetime
import os
import sys
import traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("AecPropDataMgd")

_SCRIPTS_ROOT = r"C:\Arhyz\automation\scripts\ditch"
_AUTOMATION_ROOT = r"C:\Arhyz\automation"  # for `import civil.*` (Station/ThetaDeg)
for _p in (_SCRIPTS_ROOT, _AUTOMATION_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Drop cached package modules so edits to volumes.py / refresh.py take effect.
for _m in [
    m
    for m in list(sys.modules)
    if m.startswith("ditch_04_build_cross") or m.startswith("ditch_core")
]:
    del sys.modules[_m]

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, SymbolUtilityServices

from ditch_core.property_sets import ensure_cd_psd, ensure_part_psd
from ditch_04_build_cross.refresh import refresh_volumes

LOG_DIR = r"C:\Arhyz\automation\scripts\ditch\ditch_05_build_cross_volumes\logs"
os.makedirs(LOG_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"refresh_{TIMESTAMP}.log")


def log(msg: str = "", level: str = "INFO") -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{level}] {msg}\n")


log("=== ditch_05_build_cross_volumes (refresh PS from geometry) ===")

updated = 0
errors = 0
doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        psd_id = ensure_cd_psd(db, tx)
        part_psd_id = ensure_part_psd(db, tx)
        ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
        ms = tx.GetObject(ms_id, OpenMode.ForRead)
        updated = refresh_volumes(ms, tx, psd_id, log, part_psd_id)
        log(f"refreshed {updated} ditch(es) from current geometry")
        tx.Commit()
    except Exception as e:
        errors += 1
        log(f"ERROR: {e}\n{traceback.format_exc()}", "CRITICAL")
        try:
            tx.Abort()
        except Exception:
            pass
    finally:
        try:
            tx.Dispose()
        except Exception:
            pass
finally:
    try:
        lock.Dispose()
    except Exception:
        pass

log(f"=== DONE: updated={updated}, errors={errors} ===")
OUT = updated if errors == 0 else f"errors={errors}"
